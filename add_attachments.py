#!/usr/bin/env python3
"""
add_attachments.py

Attach files to ALREADY-CREATED Jira work items (post-migration step).

The CSV bulk importer can only attach files during the initial issue creation.
This script covers the follow-up case: the issues already exist in Jira and we
need to push their Rally attachments onto them via the Jira REST API.

Flow
----
1. Read the Rally attachments export (columns: ArtifactFormattedID, FileURL,
   and optionally a file name column). Group attachment URLs by Rally ID.
2. Resolve each Rally ID -> Jira issue key using one or more mapping CSVs
   (e.g. mappings/rally_jira_id.csv with columns "Rally ID,Jira Key")
   OR by JQL lookup against the "Rally ID" custom field.
3. For each attachment: download the bytes from Rally (or read from a local
   --files-dir), then upload to Jira with an idempotency check that skips
   files already attached to the issue.
4. Write a per-file result report CSV.

Secrets are read from environment variables ONLY (never hard-coded):
  JIRA_BASE_URL     e.g. https://your-org.atlassian.net
  JIRA_EMAIL        Jira account email (Cloud basic auth username)
  JIRA_API_TOKEN    Jira API token (Cloud) or PAT (Data Center)
  RALLY_API_KEY     Rally API key (used to download attachments from Rally).
  RALLY_BASE_URL    Rally server base URL (optional; default
                    https://rally1.rallydev.com).

Usage
-----
  # Discover attachments directly from Rally (no CSV export needed) for ANY
  # work item type. Provide a single mapping CSV with columns:
  #     Rally ID,Jira Key
  # (features F####, user stories US####, defects DE####, tasks TA####, ...).
  # For each Rally ID the script finds its Rally work item, downloads every
  # attachment into --save-dir, then uploads to the mapped Jira issue.
  python3 add_attachments.py \
      --from-rally \
      --map mappings/rally_jira_id.csv \
      --save-dir rally_exports \
      --report jira_output/attachment_upload_report.csv

  # Alternatively, source Rally IDs from a migration output CSV (a column named
  # "Rally ID") and resolve Jira keys by JQL on the Rally ID custom field:
  python3 add_attachments.py \
      --from-rally \
      --rally-ids jira_output/jira_story_dp_1.csv \
      --jql-lookup --rally-id-field "Rally ID" \
      --save-dir rally_exports \
      --report jira_output/attachment_upload_report.csv

  # Download from a Rally attachments export CSV and upload to Jira
  python3 add_attachments.py \
      --attachments rally_exports/attachments.csv \
      --map mappings/rally_jira_id.csv \
      --report jira_output/attachment_upload_report.csv

  # Use already-downloaded local files instead of pulling from Rally
  python3 add_attachments.py \
      --attachments rally_exports/attachments.csv \
      --map mappings/rally_jira_id.csv \
      --files-dir rally_exports/attachment_files

  # Resolve Jira keys by querying the Rally ID custom field instead of a map
  python3 add_attachments.py \
      --attachments rally_exports/attachments.csv \
      --jql-lookup --rally-id-field "customfield_12345"

  # Preview only (no downloads, no uploads)
  python3 add_attachments.py --attachments rally_exports/attachments.csv \
      --map mappings/rally_jira_id.csv --dry-run

Dependencies: pandas, requests
"""
import argparse
import base64
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import pandas as pd

try:
    import requests
except ImportError:  # pragma: no cover
    sys.stderr.write("This script requires the 'requests' package: pip install requests\n")
    raise

# Prefer the operating system's trust store (macOS Keychain / Windows cert
# store) for TLS verification when available. This lets the script work behind
# corporate TLS-inspection proxies (ZTNA/VPN) whose root CA is trusted by the OS
# but rejected by OpenSSL 3 (e.g. "Basic Constraints of CA cert not marked
# critical"). Safe no-op if the optional 'truststore' package isn't installed.
try:
    import truststore as _truststore

    _truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 - optional; fall back to default OpenSSL trust
    pass


# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------
def load_env_file(path: Path = Path(".env")) -> None:
    """Populate os.environ from a simple KEY=VALUE .env file (if present).

    Lines starting with '#' and blank lines are ignored. Existing environment
    variables take precedence and are never overwritten. No external
    dependency required.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# ---------------------------------------------------------------------------
# CSV helpers (mirrors the conventions used in rally_to_jira.py)
# ---------------------------------------------------------------------------
def read_csv_if_exists(path: Path) -> Optional[pd.DataFrame]:
    if path.exists():
        try:
            return pd.read_csv(path, encoding="utf-8-sig", dtype=str)
        except Exception:
            return pd.read_csv(path, encoding="utf-8-sig", engine="python", dtype=str)
    return None


def get_col(r: pd.Series, key: str, default: str = "") -> str:
    v = r.get(key, default)
    return default if pd.isna(v) else str(v).strip()


def first_present_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """Return the first column name from candidates that exists in df (case-insensitive)."""
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


# ---------------------------------------------------------------------------
# Rally ID -> Jira key mapping
# ---------------------------------------------------------------------------
RALLY_ID_COLS = [
    "Rally ID", "Custom field (Rally ID)", "Feature ID", "Story ID", "Defect ID",
    "US ID", "DE ID", "ArtifactFormattedID", "FormattedID", "Formatted ID",
]
JIRA_KEY_COLS = ["Jira Key", "Issue key", "Issue Key", "Key"]


def build_id_map(map_paths: List[Path]) -> Dict[str, str]:
    """Merge one or more mapping CSVs into a single Rally-ID -> Jira-key dict."""
    id_map: Dict[str, str] = {}
    for path in map_paths:
        df = read_csv_if_exists(path)
        if df is None:
            sys.stderr.write(f"WARNING: mapping file not found, skipping: {path}\n")
            continue
        rally_col = first_present_column(df, RALLY_ID_COLS)
        key_col = first_present_column(df, JIRA_KEY_COLS)
        if not key_col:
            # Rally-ID-only file: keys are resolved via the Jira Rally ID field.
            continue
        if not rally_col:
            sys.stderr.write(
                f"WARNING: could not find a Rally-ID column in {path} "
                f"(have: {list(df.columns)}); skipping\n"
            )
            continue
        added = 0
        for _, r in df.iterrows():
            rally_id = get_col(r, rally_col)
            jira_key = get_col(r, key_col)
            if rally_id and jira_key:
                id_map.setdefault(rally_id, jira_key)
                added += 1
        print(f"  loaded {added} mappings from {path.name} ({rally_col} -> {key_col})")
    return id_map


def read_rally_ids(paths: List[Path]) -> List[str]:
    """Collect distinct Rally work-item IDs from one or more CSVs (order preserved)."""
    ids: List[str] = []
    seen: set = set()
    for path in paths:
        df = read_csv_if_exists(path)
        if df is None:
            sys.stderr.write(f"WARNING: rally-ids file not found, skipping: {path}\n")
            continue
        col = first_present_column(df, RALLY_ID_COLS)
        if not col:
            sys.stderr.write(
                f"WARNING: no Rally-ID column in {path} (have: {list(df.columns)}); skipping\n"
            )
            continue
        added = 0
        for _, r in df.iterrows():
            rid = get_col(r, col)
            if rid and rid not in seen:
                seen.add(rid)
                ids.append(rid)
                added += 1
        print(f"  loaded {added} Rally IDs from {path.name} ({col})")
    return ids


# ---------------------------------------------------------------------------
# Attachment grouping
# ---------------------------------------------------------------------------
def build_attachment_map(df: pd.DataFrame) -> Dict[str, List[Tuple[str, str]]]:
    """Group (file_name, file_url) tuples by Rally ArtifactFormattedID."""
    art_col = first_present_column(df, ["ArtifactFormattedID", "Formatted ID", "Rally ID"])
    url_col = first_present_column(df, ["FileURL", "File URL", "Url", "URL", "Content"])
    name_col = first_present_column(df, ["Name", "FileName", "File Name"])
    if not art_col or not url_col:
        raise ValueError(
            f"attachments CSV must contain an artifact-id column and a URL column. "
            f"Found columns: {list(df.columns)}"
        )
    grouped: Dict[str, List[Tuple[str, str]]] = {}
    for _, r in df.iterrows():
        art = get_col(r, art_col)
        url = get_col(r, url_col)
        if not art or not url:
            continue
        name = get_col(r, name_col) if name_col else ""
        if not name:
            name = filename_from_url(url)
        grouped.setdefault(art, []).append((name, url))
    return grouped


def filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = unquote(Path(path).name) if path else ""
    return name or "attachment"


# ---------------------------------------------------------------------------
# HTTP: Rally download + Jira upload
# ---------------------------------------------------------------------------
def make_rally_session(api_key: str) -> requests.Session:
    s = requests.Session()
    if api_key:
        # Rally accepts the API key via the ZSESSIONID header.
        s.headers.update({"ZSESSIONID": api_key})
    return s


def make_jira_session(email: str, token: str) -> requests.Session:
    s = requests.Session()
    s.auth = (email, token)
    # Required by Jira to allow programmatic attachment uploads.
    s.headers.update({"X-Atlassian-Token": "no-check", "Accept": "application/json"})
    return s


def download_from_rally(session: requests.Session, url: str, retries: int = 3) -> bytes:
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=60, stream=True)
            resp.raise_for_status()
            return resp.content
        except Exception as e:  # noqa: BLE001 - surface as failure in report
            last_err = e
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"download failed after {retries} attempts: {last_err}")


# ---------------------------------------------------------------------------
# Rally WSAPI: discover + download attachments directly from a work item
# ---------------------------------------------------------------------------
def rally_api_base(base_url: str) -> str:
    """Normalise a Rally base URL to its WSAPI v2.0 root."""
    base = (base_url or "https://rally1.rallydev.com").rstrip("/")
    if "/slm/webservice" not in base:
        base = base + "/slm/webservice/v2.0"
    return base


def rally_find_attachments_ref(
    session: requests.Session, api_base: str, formatted_id: str, retries: int = 3
) -> Tuple[Optional[str], int]:
    """Look up a Rally artifact by FormattedID; return (attachments_ref, count)."""
    url = f"{api_base}/artifact"
    params = {
        "query": f'(FormattedID = "{formatted_id}")',
        "fetch": "FormattedID,ObjectID,Attachments",
        "pagesize": 1,
    }
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, timeout=60)
            resp.raise_for_status()
            qr = resp.json().get("QueryResult", {}) or {}
            results = qr.get("Results", []) or []
            if not results:
                return None, 0
            att = results[0].get("Attachments", {}) or {}
            return att.get("_ref"), int(att.get("Count", 0) or 0)
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"Rally lookup failed after {retries} attempts: {last_err}")


def rally_list_attachments(
    session: requests.Session, attachments_ref: str, retries: int = 3, page_size: int = 100
) -> List[Dict[str, str]]:
    """Return [{name, content_ref, content_type, size}] for an Attachments collection.

    Rally paging is followed so work items with more than one page of
    attachments (> page_size) are fully enumerated.
    """
    out: List[Dict[str, str]] = []
    start = 1  # Rally paging is 1-based
    while True:
        params = {
            "fetch": "Name,Content,ContentType,Size",
            "pagesize": page_size,
            "start": start,
        }
        last_err: Optional[Exception] = None
        qr: Optional[Dict] = None
        for attempt in range(1, retries + 1):
            try:
                resp = session.get(attachments_ref, params=params, timeout=60)
                resp.raise_for_status()
                qr = resp.json().get("QueryResult", {}) or {}
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(min(2 ** attempt, 10))
        if qr is None:
            raise RuntimeError(
                f"listing Rally attachments failed after {retries} attempts: {last_err}"
            )
        results = qr.get("Results", []) or []
        for a in results:
            content = a.get("Content") or {}
            out.append(
                {
                    "name": a.get("Name") or "attachment",
                    "content_ref": content.get("_ref") or "",
                    "content_type": a.get("ContentType") or "",
                    "size": a.get("Size") or 0,
                }
            )
        total = int(qr.get("TotalResultCount", len(out)) or 0)
        start += page_size
        if not results or start > total:
            break
    return out


def rally_download_attachment(session: requests.Session, content_ref: str, retries: int = 3) -> bytes:
    """Download an AttachmentContent object (base64) and return the raw bytes."""
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(content_ref, params={"fetch": "Content"}, timeout=120)
            resp.raise_for_status()
            data = resp.json().get("AttachmentContent", {}) or {}
            return base64.b64decode(data.get("Content") or "")
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"Rally attachment download failed after {retries} attempts: {last_err}")


def _dedupe_name(name: str, seen: Dict[str, int]) -> str:
    """Return a unique file name within one work item; suffix duplicates as 'name (2).ext'."""
    base = name or "attachment"
    if base not in seen:
        seen[base] = 1
        return base
    seen[base] += 1
    stem, dot, ext = base.rpartition(".")
    if dot:
        return f"{stem} ({seen[base]}).{ext}"
    return f"{base} ({seen[base]})"


def discover_rally_attachments(
    session: requests.Session, api_base: str, rally_ids: List[str]
) -> Dict[str, List[Tuple[str, str]]]:
    """For each Rally ID, return {rally_id: [(file_name, content_ref), ...]}.

    Every attachment on a work item is returned (Rally paging is followed).
    Duplicate file names within the same work item are disambiguated so each
    attachment is downloaded and uploaded (no silent overwrite or skip).
    """
    grouped: Dict[str, List[Tuple[str, str]]] = {}
    scanned = 0
    for rid in rally_ids:
        scanned += 1
        try:
            att_ref, count = rally_find_attachments_ref(session, api_base, rid)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"  Rally lookup failed for {rid}: {e}\n")
            continue
        if not att_ref or not count:
            continue
        try:
            attachments = rally_list_attachments(session, att_ref)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"  could not list Rally attachments for {rid}: {e}\n")
            continue
        seen: Dict[str, int] = {}
        items: List[Tuple[str, str]] = []
        for a in attachments:
            ref = a.get("content_ref")
            if not ref:
                continue
            items.append((_dedupe_name(a.get("name", ""), seen), ref))
        if items:
            grouped[rid] = items
            print(f"  {rid}: {len(items)} attachment(s)")
    print(f"  scanned {scanned} work item(s); {len(grouped)} have attachments")
    return grouped


def existing_attachment_names(session: requests.Session, base_url: str, issue_key: str) -> set:
    url = f"{base_url}/rest/api/3/issue/{issue_key}?fields=attachment"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {a.get("filename", "") for a in data.get("fields", {}).get("attachment", []) or []}


def upload_to_jira(
    session: requests.Session,
    base_url: str,
    issue_key: str,
    file_name: str,
    content: bytes,
    retries: int = 3,
) -> None:
    url = f"{base_url}/rest/api/3/issue/{issue_key}/attachments"
    # Any file format is supported. Send the correct MIME type so Jira previews
    # images/PDFs/etc.; unknown/binary types fall back to octet-stream, which
    # Jira stores and serves as-is (e.g. .zip, .xlsx, .md).
    content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.post(
                url,
                files={"file": (file_name, content, content_type)},
                timeout=300,  # generous for large attachments
            )
        except Exception as e:  # noqa: BLE001 - network error, retry
            last_err = e
            time.sleep(min(2 ** attempt, 10))
            continue
        if resp.status_code == 429:  # rate limited
            wait = int(resp.headers.get("Retry-After", min(2 ** attempt, 30)))
            time.sleep(wait)
            continue
        if resp.status_code == 413:  # exceeds the Jira attachment size limit
            raise RuntimeError(
                f"file exceeds the Jira attachment size limit "
                f"({len(content):,} bytes); raise the limit in Jira admin "
                f"(Settings > System > Attachments) or exclude this file"
            )
        try:
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001 - server error, retry
            last_err = e
            time.sleep(min(2 ** attempt, 10))
            continue
        return
    raise RuntimeError(f"upload failed after {retries} attempts: {last_err}")


def lookup_key_by_jql(
    session: requests.Session, base_url: str, rally_id_field: str, rally_id: str
) -> Optional[str]:
    field_ref = rally_id_field if rally_id_field.startswith("customfield_") else f'"{rally_id_field}"'
    jql = f'{field_ref} ~ "{rally_id}"'
    # Jira Cloud replaced GET /rest/api/3/search with GET /rest/api/3/search/jql.
    url = f"{base_url}/rest/api/3/search/jql"
    resp = session.get(url, params={"jql": jql, "fields": "key", "maxResults": 5}, timeout=30)
    resp.raise_for_status()
    issues = resp.json().get("issues", []) or []
    if len(issues) == 1:
        return issues[0]["key"]
    if len(issues) > 1:
        sys.stderr.write(
            f"  JQL for {rally_id} returned {len(issues)} issues; skipping (ambiguous match).\n"
        )
    return None


# ---------------------------------------------------------------------------
# Resumable batch state
# ---------------------------------------------------------------------------
STATE_COLUMNS = ["rally_id", "files", "uploaded", "exists", "errors", "skipped", "status", "run_at"]


def load_processed_ids(state_path: Path) -> set:
    """Return the set of Rally IDs already completed per the batch state file.

    A Rally ID counts as done only when its most recent state row has
    status == "done" (everything uploaded/already-present, no errors and no
    unresolved key). Items recorded as "partial" are eligible for retry.
    """
    if not state_path.exists():
        return set()
    try:
        df = pd.read_csv(state_path, dtype=str, keep_default_na=False)
    except Exception:  # noqa: BLE001
        return set()
    if "rally_id" not in df.columns or "status" not in df.columns:
        return set()
    done: set = set()
    for _, r in df.iterrows():  # chronological order: last row per id wins
        rid = str(r.get("rally_id", "")).strip()
        if not rid:
            continue
        if str(r.get("status", "")).strip().lower() == "done":
            done.add(rid)
        else:
            done.discard(rid)
    return done


def append_state_rows(state_path: Path, rows: List[dict]) -> None:
    """Append batch state rows, writing a header only when the file is new."""
    if not rows:
        return
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not state_path.exists()
    pd.DataFrame(rows, columns=STATE_COLUMNS).to_csv(
        state_path, mode="a", header=write_header, index=False, encoding="utf-8-sig"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Attach Rally files to existing Jira issues.")
    p.add_argument("--attachments", help="Rally attachments export CSV (columns: ArtifactFormattedID, FileURL). "
                                         "Not required when using --from-rally.")
    p.add_argument("--from-rally", action="store_true",
                   help="Discover attachments directly from Rally via the WSAPI for the Rally IDs supplied "
                        "through --map and/or --rally-ids (features, user stories, defects, tasks, etc.), "
                        "download them into --save-dir, then upload to the mapped Jira issue.")
    p.add_argument("--save-dir", default="rally_exports",
                   help="Directory where attachments downloaded from Rally are saved (used with --from-rally). "
                        "Files are stored under <save-dir>/<rally-id>/<name>. Default: rally_exports.")
    p.add_argument("--map", action="append", default=[], help="Rally-ID -> Jira-key mapping CSV (repeatable).")
    p.add_argument("--rally-ids", action="append", default=[],
                   help="CSV file(s) providing Rally work-item IDs to scan (e.g. a migration output CSV with a "
                        "'Rally ID' column for stories/defects). Combine with --jql-lookup to resolve Jira keys, "
                        "or with --map for pre-known keys. Repeatable.")
    p.add_argument("--files-dir", help="Directory of already-downloaded files (matched by file name). "
                                       "If set, files are read locally instead of downloaded from Rally.")
    p.add_argument("--jql-lookup", action="store_true", help="Resolve Jira keys via JQL on the Rally ID field.")
    p.add_argument("--rally-id-field", default="Rally ID",
                   help="Jira field name/id holding the Rally ID (for --jql-lookup).")
    p.add_argument("--report", default="attachment_upload_report.csv", help="Per-file result report CSV.")
    p.add_argument("--limit", type=int, default=0, help="Process at most N attachments (0 = no limit).")
    p.add_argument("--batch-size", type=int, default=0,
                   help="Process at most N Rally work items per run (0 = all). Enables resumable batching: "
                        "each run handles the next N not-yet-completed items and records progress in the "
                        "state file, so re-running the same command continues where it left off.")
    p.add_argument("--state-file",
                   help="CSV tracking completed Rally IDs for resumable batching. "
                        "Default: <report dir>/attachment_batch_state.csv. Delete it to start over.")
    p.add_argument("--no-idempotency", action="store_true",
                   help="Skip the 'already attached' check (may create duplicates).")
    p.add_argument("--dry-run", action="store_true", help="Preview only; no downloads or uploads.")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    load_env_file()

    if not args.from_rally and not args.attachments:
        sys.stderr.write("ERROR: provide --attachments <csv> or use --from-rally.\n")
        return 2

    print("Loading Rally->Jira id mappings...")
    id_map = build_id_map([Path(m) for m in args.map])
    print(f"  total mapped ids: {len(id_map)}")

    base_url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    jira_email = os.environ.get("JIRA_EMAIL", "")
    jira_token = os.environ.get("JIRA_API_TOKEN", "")
    rally_key = os.environ.get("RALLY_API_KEY", "")
    rally_base = rally_api_base(os.environ.get("RALLY_BASE_URL", "https://rally1.rallydev.com"))

    need_jira = not args.dry_run
    if need_jira and not (base_url and jira_email and jira_token):
        sys.stderr.write("ERROR: set JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN env vars.\n")
        return 2

    files_dir = Path(args.files_dir) if args.files_dir else None
    save_dir = Path(args.save_dir) if args.save_dir else Path("rally_exports")

    # Determine how attachment bytes are obtained.
    if args.from_rally:
        source_mode = "rally_api"   # discover + download from Rally WSAPI
    elif files_dir is not None:
        source_mode = "local"       # read already-downloaded files locally
    else:
        source_mode = "fileurl"     # download from FileURL in an attachments CSV

    need_rally = source_mode in ("rally_api", "fileurl")
    if need_rally and not rally_key:
        if source_mode == "rally_api" and not args.dry_run:
            sys.stderr.write("ERROR: RALLY_API_KEY is required for --from-rally.\n")
            return 2
        if source_mode == "fileurl":
            sys.stderr.write("WARNING: RALLY_API_KEY not set; Rally downloads may fail. "
                             "Use --files-dir for local files.\n")

    # A Jira session is needed for uploads and to resolve the Jira issue by its
    # Rally ID field (also useful for --dry-run previews).
    want_jira_session = bool(base_url and jira_email and jira_token)
    jira = make_jira_session(jira_email, jira_token) if want_jira_session else None
    rally = make_rally_session(rally_key) if (need_rally and rally_key) else None

    key_cache: Dict[str, Optional[str]] = {}

    def resolve_target_key(rally_id: str) -> Optional[str]:
        """Resolve a Rally work-item ID to the Jira issue that carries the same
        value in its Rally ID field (looked up via JQL).
        """
        if rally_id in key_cache:
            return key_cache[rally_id]
        resolved: Optional[str] = None
        if jira is not None:
            try:
                resolved = lookup_key_by_jql(jira, base_url, args.rally_id_field, rally_id)
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"  Rally ID lookup failed for {rally_id}: {e}\n")
                resolved = None
        key_cache[rally_id] = resolved
        return resolved

    if source_mode == "rally_api":
        # The control file(s) supplied via --map and/or --rally-ids are the ONLY
        # source of Rally IDs to process (features, stories, defects, test cases).
        control_paths = [Path(p) for p in args.map] + [Path(p) for p in args.rally_ids]
        scan_ids: List[str] = read_rally_ids(control_paths) if control_paths else list(id_map.keys())
        if not scan_ids:
            sys.stderr.write("ERROR: --from-rally needs Rally IDs via --map and/or --rally-ids.\n")
            return 2
        if rally is None:
            # Dry-run without a Rally API key: preview Rally->Jira key resolution
            # only (cannot reach Rally to discover or download attachments).
            print("RALLY_API_KEY not set: previewing Rally->Jira key resolution only "
                  "(no Rally discovery or download).")
            resolved = 0
            for rid in scan_ids:
                jira_key = resolve_target_key(rid)
                if jira_key:
                    resolved += 1
                    print(f"  {rid} -> {jira_key}")
                else:
                    print(f"  {rid} -> <unresolved>")
            print(f"\nPlanned: {len(scan_ids)} work item(s); "
                  f"{resolved} resolved, {len(scan_ids) - resolved} unresolved.")
            print("Set RALLY_API_KEY and re-run without --dry-run to download and upload.")
            return 0
        print(f"Discovering attachments in Rally via WSAPI for {len(scan_ids)} work item(s)...")
        grouped = discover_rally_attachments(rally, rally_base, scan_ids)
    else:
        attach_df = read_csv_if_exists(Path(args.attachments))
        if attach_df is None:
            sys.stderr.write(f"ERROR: attachments file not found: {args.attachments}\n")
            return 2
        grouped = build_attachment_map(attach_df)
    total_files = sum(len(v) for v in grouped.values())
    print(f"Attachments to process: {len(grouped)} artifacts, {total_files} files.")

    # -- Resumable batching -------------------------------------------------
    # Activated when --batch-size or --state-file is supplied. Skip Rally IDs
    # already completed (per the state file), then take the next N items.
    use_state = (args.batch_size and args.batch_size > 0) or bool(args.state_file)
    state_file = Path(args.state_file) if args.state_file else (
        Path(args.report).parent / "attachment_batch_state.csv"
    )
    done_ids = load_processed_ids(state_file) if use_state else set()
    pending_ids = [rid for rid in grouped if rid not in done_ids]
    if use_state and done_ids:
        print(f"Resuming: {len(grouped) - len(pending_ids)} item(s) already completed "
              f"(per {state_file}); {len(pending_ids)} pending.")
    if args.batch_size and args.batch_size > 0:
        batch_ids = pending_ids[:args.batch_size]
        remaining_after = len(pending_ids) - len(batch_ids)
        print(f"This batch: {len(batch_ids)} of {len(pending_ids)} pending work item(s) "
              f"(batch size {args.batch_size}; {remaining_after} will remain after this run).")
    else:
        batch_ids = pending_ids
    # Restrict processing to the selected batch, preserving order.
    grouped = {rid: grouped[rid] for rid in batch_ids}
    total_files = sum(len(v) for v in grouped.values())

    results: List[dict] = []
    existing_cache: Dict[str, set] = {}
    processed = 0

    for rally_id, files in grouped.items():
        jira_key = resolve_target_key(rally_id)

        for file_name, file_url in files:
            if args.limit and processed >= args.limit:
                break
            processed += 1
            row = {
                "rally_id": rally_id,
                "jira_key": jira_key or "",
                "file_name": file_name,
                "source": (
                    str(save_dir / rally_id / file_name) if source_mode == "rally_api"
                    else str(files_dir / file_name) if files_dir else file_url
                ),
                "status": "",
                "detail": "",
            }

            if not jira_key:
                row["status"] = "skipped"
                row["detail"] = "no Jira key for Rally id"
                results.append(row)
                print(f"  SKIP {rally_id} / {file_name}: no Jira key")
                continue

            if args.dry_run:
                row["status"] = "dry-run"
                results.append(row)
                print(f"  DRY  {rally_id} -> {jira_key} : {file_name}")
                continue

            # Idempotency check
            if not args.no_idempotency:
                if jira_key not in existing_cache:
                    try:
                        existing_cache[jira_key] = existing_attachment_names(jira, base_url, jira_key)
                    except Exception as e:  # noqa: BLE001
                        existing_cache[jira_key] = set()
                        sys.stderr.write(f"  could not list attachments for {jira_key}: {e}\n")
                if file_name in existing_cache[jira_key]:
                    row["status"] = "exists"
                    row["detail"] = "already attached"
                    results.append(row)
                    print(f"  EXIST {jira_key} : {file_name}")
                    continue

            # Obtain bytes
            try:
                if source_mode == "rally_api":
                    # file_url holds the Rally AttachmentContent _ref here.
                    content = rally_download_attachment(rally, file_url)
                    dest = save_dir / rally_id / file_name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(content)
                    row["source"] = str(dest)
                elif source_mode == "local":
                    fpath = files_dir / file_name
                    if not fpath.exists():
                        raise FileNotFoundError(f"local file missing: {fpath}")
                    content = fpath.read_bytes()
                else:  # fileurl
                    content = download_from_rally(rally, file_url)
            except Exception as e:  # noqa: BLE001
                row["status"] = "error"
                row["detail"] = f"fetch: {e}"
                results.append(row)
                sys.stderr.write(f"  ERROR fetch {rally_id} / {file_name}: {e}\n")
                continue

            # Upload via the Jira REST API.
            try:
                upload_to_jira(jira, base_url, jira_key, file_name, content)
                existing_cache.setdefault(jira_key, set()).add(file_name)
                row["status"] = "uploaded"
                results.append(row)
                print(f"  OK   {jira_key} : {file_name}")
            except Exception as e:  # noqa: BLE001
                row["status"] = "error"
                row["detail"] = f"upload: {e}"
                results.append(row)
                sys.stderr.write(f"  ERROR upload {jira_key} / {file_name}: {e}\n")

        if args.limit and processed >= args.limit:
            break

    # Update resumable batch state (never during dry-run).
    if use_state and not args.dry_run and batch_ids:
        item_stats: Dict[str, Dict[str, int]] = {
            rid: {"files": 0, "uploaded": 0, "exists": 0, "errors": 0, "skipped": 0}
            for rid in batch_ids
        }
        for row in results:
            st = item_stats.get(row["rally_id"])
            if st is None:
                continue
            st["files"] += 1
            if row["status"] in st:
                st[row["status"]] += 1
        run_at = time.strftime("%Y-%m-%d %H:%M:%S")
        state_rows: List[dict] = []
        for rid in batch_ids:
            st = item_stats[rid]
            if st["files"] == 0:
                continue  # not reached this run (e.g. cut short by --limit)
            complete = st["errors"] == 0 and st["skipped"] == 0
            state_rows.append({
                "rally_id": rid,
                "files": st["files"],
                "uploaded": st["uploaded"],
                "exists": st["exists"],
                "errors": st["errors"],
                "skipped": st["skipped"],
                "status": "done" if complete else "partial",
                "run_at": run_at,
            })
        append_state_rows(state_file, state_rows)
        done_now = sum(1 for r in state_rows if r["status"] == "done")
        remaining = len(pending_ids) - len([r for r in state_rows if r["status"] == "done"])
        print(f"\nBatch state updated: {state_file}")
        print(f"  {done_now} item(s) marked done this run; ~{remaining} pending for next run.")
        if remaining > 0:
            print("  Re-run the same command to process the next batch.")

    # Write report
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results, columns=["rally_id", "jira_key", "file_name", "source", "status", "detail"]).to_csv(
        report_path, index=False, encoding="utf-8-sig"
    )

    summary: Dict[str, int] = {}
    for row in results:
        summary[row["status"]] = summary.get(row["status"], 0) + 1
    print("\nSummary:")
    for status, count in sorted(summary.items()):
        print(f"  {status}: {count}")
    print(f"Report written to: {report_path}")

    had_errors = summary.get("error", 0) > 0
    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
