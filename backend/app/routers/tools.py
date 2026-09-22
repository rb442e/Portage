"""Standalone tools that live outside the migration workflow.

  * CSV file splitter — split a large CSV into header-preserving part files.
  * Copy Description — copy a Rally description (tables preserved) into a Jira
    issue, single or in bulk; a bulk dry-run doubles as a table-detection report.
"""
from __future__ import annotations

import csv
import io
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from .. import copydesc_jobs
from ..config import settings
from ..connectors.jira_client import JiraClient
from ..connectors.rally_client import RallyClient
from ..engine.attachments import extract_rally_ids
from ..engine.richtext import count_tables, html_to_wiki
from ..engine.splitter import split_csv_file
from ..engine.transform import load_dataframe
from ..schemas import (CopyDescBulkRequest, CopyDescIdsResult, CopyDescJob,
                       CopyDescriptionRequest, CopyDescriptionResult,
                       SplitPart, SplitResult)

router = APIRouter(prefix="/api/tools", tags=["tools"])

_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CHUNK = 1024 * 1024  # 1 MiB streaming copy so large uploads never load fully into memory.


def _splits_root() -> Path:
    d = settings.data_dir / "splits"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _split_dir(split_id: str) -> Path:
    if not _ID_RE.match(split_id):
        raise HTTPException(status_code=404, detail="Split not found.")
    return _splits_root() / split_id


@router.post("/split", response_model=SplitResult)
async def split_file(
    file: UploadFile = File(...),
    max_rows: int = Form(1000),
    has_header: bool = Form(True),
) -> SplitResult:
    """Split an uploaded CSV into part files that each retain the header row."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please attach a .csv file.")
    if max_rows <= 0:
        raise HTTPException(status_code=400, detail="Rows per file must be greater than 0.")

    split_id = uuid.uuid4().hex
    work = _split_dir(split_id)
    work.mkdir(parents=True, exist_ok=True)

    # Stream the (potentially large) upload to disk in chunks, then split from disk.
    source = work / "_source.csv"
    try:
        with source.open("wb") as out:
            shutil.copyfileobj(file.file, out, _CHUNK)
        parts = split_csv_file(
            source, out_dir=work, max_rows=max_rows,
            base=Path(file.filename).stem, has_header=has_header,
        )
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(work, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Could not split CSV: {e}")
    finally:
        source.unlink(missing_ok=True)

    total = sum(int(p["rows"]) for p in parts)
    split_parts = []
    for p in parts:
        size = Path(str(p["path"])).stat().st_size if p.get("path") else 0
        split_parts.append(SplitPart(name=str(p["name"]), rows=int(p["rows"]), size=int(size)))
    return SplitResult(
        split_id=split_id,
        filename=file.filename,
        parts=split_parts,
        total_rows=total,
        total_size=sum(p.size for p in split_parts),
    )


@router.get("/splits/{split_id}.zip")
def download_split_zip(split_id: str) -> StreamingResponse:
    d = _split_dir(split_id)
    if not d.exists():
        raise HTTPException(status_code=404, detail="Split not found.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(d.glob("*.csv")):
            zf.write(p, arcname=p.name)
    buf.seek(0)
    fname = f"portage_split_{split_id[:8]}.zip"
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/splits/{split_id}/{filename}")
def download_split_file(split_id: str, filename: str) -> FileResponse:
    safe = Path(filename).name  # strip any path components
    fp = _split_dir(split_id) / safe
    if not fp.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(fp, media_type="text/csv", filename=safe)


# ---------------------------------------------------------------------------
# Copy a Rally description (tables preserved) into a Jira issue's description.
# ---------------------------------------------------------------------------
def _fetch_rally_html(req: CopyDescriptionRequest) -> str:
    if not req.rally.api_key:
        raise HTTPException(status_code=400, detail="A Rally API key is required to read the description.")
    rally_id = (req.rally_id or "").strip()
    if not rally_id:
        raise HTTPException(status_code=400, detail="Enter a Rally Formatted ID (e.g. F139943).")
    try:
        return RallyClient(req.rally).fetch_description(rally_id) or ""
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Rally read failed: {e}")


@router.post("/copy-description/preview", response_model=CopyDescriptionResult)
def copy_description_preview(req: CopyDescriptionRequest) -> CopyDescriptionResult:
    """Fetch the Rally description and show how it will be copied — no write."""
    html = _fetch_rally_html(req)
    fmt = "adf" if req.jira.deployment == "cloud" else "wiki"
    return CopyDescriptionResult(
        rally_id=req.rally_id.strip(),
        jira_key=req.jira_key.strip(),
        format=fmt,
        tables_found=count_tables(html),
        has_source=bool(html.strip()),
        applied=False,
        message="Nothing to copy — the Rally description is empty." if not html.strip()
                else "Preview ready. Tables are preserved when applied.",
        text_preview=html_to_wiki(html),
    )


@router.post("/copy-description/apply", response_model=CopyDescriptionResult)
def copy_description_apply(req: CopyDescriptionRequest) -> CopyDescriptionResult:
    """Fetch the Rally description, convert it (ADF/wiki), and write it to the
    target Jira issue's description field — tables in the same grid format."""
    jira_key = (req.jira_key or "").strip()
    if not jira_key:
        raise HTTPException(status_code=400, detail="Enter the target Jira issue key (e.g. PN-123).")
    if not (req.jira.base_url and req.jira.api_token):
        raise HTTPException(status_code=400, detail="Jira base URL and API token are required.")

    html = _fetch_rally_html(req)
    fmt = "adf" if req.jira.deployment == "cloud" else "wiki"
    if not html.strip():
        return CopyDescriptionResult(rally_id=req.rally_id.strip(), jira_key=jira_key, format=fmt,
                                     tables_found=0, has_source=False, applied=False,
                                     message="Nothing to copy — the Rally description is empty.",
                                     text_preview="")

    jira = JiraClient(req.jira)
    ok, err = jira.set_description(jira_key, jira.description_from_html(html))
    if not ok:
        raise HTTPException(status_code=502, detail=f"Jira update failed: {err}")
    tables = count_tables(html)
    return CopyDescriptionResult(
        rally_id=req.rally_id.strip(), jira_key=jira_key, format=fmt,
        tables_found=tables, has_source=True, applied=True,
        message=f"Copied {req.rally_id.strip()} → {jira_key}"
                + (f" · {tables} table(s) preserved." if tables else "."),
        text_preview=html_to_wiki(html),
    )


# --- bulk copy over a list of Rally IDs (dry-run = table-detection report) ---
# Columns (case-insensitive) that may hold the Jira key/id in a post-import map.
_JIRA_KEY_COLS = ["Jira Key", "Jira Issue Key", "Issue key", "Key",
                  "Jira ID", "Jira Id", "Jira Issue Id", "Issue id"]
_JIRA_KEYISH = re.compile(r"^[A-Za-z][A-Za-z0-9]+-\d+$")
_JIRA_NUMID = re.compile(r"^\d+$")


def _find_key_column(df, exclude: str) -> str:
    lower = {c.lower(): c for c in df.columns}
    for cand in _JIRA_KEY_COLS:
        c = lower.get(cand.lower())
        if c and c != exclude:
            return c
    return ""


@router.post("/copy-description/upload-ids", response_model=CopyDescIdsResult)
async def copy_description_upload_ids(file: UploadFile) -> CopyDescIdsResult:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv containing Rally IDs.")
    tmp = settings.upload_dir / f"cdids_{uuid.uuid4().hex}.csv"
    tmp.write_bytes(await file.read())
    try:
        df = load_dataframe(tmp)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")
    finally:
        tmp.unlink(missing_ok=True)

    col, ids = extract_rally_ids(df)
    if not col:
        raise HTTPException(status_code=400, detail=f"No Rally ID column found (columns: {list(df.columns)}).")
    if not ids:
        raise HTTPException(status_code=400, detail=f"Column '{col}' has no Rally IDs.")

    # If the CSV is a post-import map (Rally ID + Jira key/id), build the direct
    # mapping so identification needs no JQL. Validated so a Rally-derived
    # "Issue Id" (e.g. STORY-US123) is not mistaken for a Jira key.
    key_col = _find_key_column(df, exclude=col)
    id_map: dict = {}
    if key_col:
        ok = tot = 0
        for _, r in df.iterrows():
            rid = str(r[col]).strip()
            kv = re.sub(r"\.0$", "", str(r[key_col]).strip())
            if not rid or rid.lower() == "nan" or not kv or kv.lower() == "nan":
                continue
            tot += 1
            if _JIRA_KEYISH.match(kv) or _JIRA_NUMID.match(kv):
                ok += 1
                id_map.setdefault(rid, kv)
        if not tot or ok / tot < 0.5:   # values don't look like Jira keys/ids
            id_map, key_col = {}, ""

    return CopyDescIdsResult(filename=file.filename, row_count=int(len(df)), id_column=col,
                             key_column=key_col, rally_ids=ids, id_map=id_map)


@router.post("/copy-description/bulk", response_model=CopyDescJob)
def copy_description_bulk(req: CopyDescBulkRequest) -> CopyDescJob:
    if not req.rally_ids:
        raise HTTPException(status_code=400, detail="No Rally IDs to process — upload a CSV first.")
    if not req.rally.api_key:
        raise HTTPException(status_code=400, detail="A Rally API key is required to read descriptions.")
    if not req.rally_id_field:
        raise HTTPException(status_code=400, detail="Set the Jira field that stores the Rally ID.")
    if not req.dry_run and not (req.jira.base_url and req.jira.api_token):
        raise HTTPException(status_code=400, detail="Jira base URL and API token are required to apply.")
    return copydesc_jobs.start(req)


@router.get("/copy-description/jobs/{job_id}", response_model=CopyDescJob)
def copy_description_job(job_id: str) -> CopyDescJob:
    job = copydesc_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.get("/copy-description/jobs/{job_id}/report.csv")
def copy_description_report(job_id: str) -> StreamingResponse:
    job = copydesc_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["rally_id", "jira_key", "tables_found", "status", "detail"])
    for it in job.items:
        writer.writerow([it.rally_id, it.jira_key, it.tables_found, it.status, it.detail])
    buf.seek(0)
    fname = f"copy_description_report_{job_id[:8]}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})
