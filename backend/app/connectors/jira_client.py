"""Jira REST connector — the *live* target side of Portage.

Creates work items directly through the Jira API (no CSV importer), links them,
and uploads attachments. The attachment upload + idempotency logic mirrors the
proven approach in the repo's add_attachments.py.
"""
from __future__ import annotations

import mimetypes
import time
from typing import Dict, List, Optional, Tuple

import requests

try:  # Prefer OS trust store for corporate TLS-inspection proxies.
    import truststore as _truststore

    _truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 - optional
    pass

from ..schemas import JiraConnection


def _dedupe_types(types: List[dict]) -> List[dict]:
    seen: set = set()
    out: List[dict] = []
    for t in types:
        name = t.get("name", "")
        if name and name not in seen:
            seen.add(name)
            out.append(t)
    return out


def _suggest_fields(fields: List[dict]) -> Dict[str, str]:
    """Best-guess custom-field IDs from field names + Greenhopper schema markers."""
    sugg = {"sprint_field": "", "story_points_field": "", "team_field": "",
            "epic_link_field": "", "rally_id_field": ""}
    for f in fields:
        cid = f.get("id", "")
        name = (f.get("name") or "").lower().strip()
        sc = f.get("schema_custom") or ""
        if not sugg["sprint_field"] and sc.endswith("gh-sprint"):
            sugg["sprint_field"] = cid
        if not sugg["epic_link_field"] and sc.endswith("gh-epic-link"):
            sugg["epic_link_field"] = cid
        if not sugg["story_points_field"] and (
            name in ("story points", "story point estimate")
            or sc.endswith("story-points") or sc.endswith("jsw-story-points")
        ):
            sugg["story_points_field"] = cid
        if not sugg["team_field"] and (
            name == "team" or sc.endswith(":team") or sc.endswith("atlassian-team")
        ):
            sugg["team_field"] = cid
        if not sugg["rally_id_field"] and "rally" in name:
            sugg["rally_id_field"] = cid
    return sugg


def text_to_adf(text: str) -> dict:
    """Convert plain text into a minimal Atlassian Document Format doc.

    Jira Cloud REST v3 requires ADF for the description field. Blank lines split
    paragraphs; empty input yields an empty (but valid) document.
    """
    content = []
    for block in (text or "").split("\n\n"):
        block = block.strip("\n")
        if not block.strip():
            continue
        lines = block.split("\n")
        para = {"type": "paragraph", "content": []}
        for i, line in enumerate(lines):
            if i:
                para["content"].append({"type": "hardBreak"})
            if line:
                para["content"].append({"type": "text", "text": line})
        content.append(para)
    return {"type": "doc", "version": 1, "content": content}


class JiraClient:
    def __init__(self, conn: JiraConnection):
        self.conn = conn
        self.base_url = conn.base_url.rstrip("/")
        self.api = "3" if conn.deployment == "cloud" else "2"
        self.session = requests.Session()
        # Cloud: HTTP basic (account email + API token). Server/DC: basic when an
        # email/username is supplied, otherwise a Personal Access Token sent as a
        # Bearer header — the standard DC auth that plain basic auth rejects (401).
        if conn.deployment != "cloud" and not conn.email:
            self.session.headers["Authorization"] = f"Bearer {conn.api_token}"
        else:
            self.session.auth = (conn.email, conn.api_token)
        self.session.headers.update(
            {"X-Atlassian-Token": "no-check", "Accept": "application/json"}
        )

    # -- connection test ---------------------------------------------------
    def test(self) -> Tuple[bool, str, str]:
        url = f"{self.base_url}/rest/api/{self.api}/myself"
        try:
            resp = self.session.get(url, timeout=30)
        except requests.exceptions.SSLError as e:
            return False, (f"TLS/SSL error reaching {self.base_url} — a corporate proxy or "
                           f"untrusted certificate is likely. ({e})"), ""
        except requests.exceptions.ConnectionError:
            return False, (f"Could not reach {self.base_url}. Check the Base URL, VPN/network, "
                           f"and that it is the Jira site root."), ""
        except requests.exceptions.RequestException as e:  # timeouts, etc.
            return False, str(e), ""
        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                return False, (f"Reached {self.base_url} but the response was not JSON — this may "
                               f"not be the Jira API root (check the Base URL)."), ""
            who = data.get("displayName") or data.get("name") or data.get("emailAddress", "")
            return True, "Authenticated", who
        hints = {
            401: ("401 Unauthorized — credentials rejected. Jira Cloud needs your account email + an "
                  "API token (id.atlassian.com → API tokens), not a password. Server/DC needs a valid "
                  "Personal Access Token — leave Email blank to send it as a Bearer token."),
            403: ("403 Forbidden — credentials accepted but access denied (missing permission, or a "
                  "CAPTCHA after failed logins; sign in via the browser once to clear it)."),
            404: (f"404 Not Found at {url} — check the Base URL and Deployment (Cloud uses /rest/api/3, "
                  f"Server/DC uses /rest/api/2)."),
        }
        if resp.status_code in hints:
            return False, hints[resp.status_code], ""
        body = (resp.text or "").strip().replace("\n", " ")[:200]
        return False, f"HTTP {resp.status_code}: {body}", ""

    def account_id(self, email: str) -> Optional[str]:
        """Best-effort user lookup for Cloud (create needs accountId, not email)."""
        if not email or "@" not in email:
            return email or None
        try:
            resp = self.session.get(
                f"{self.base_url}/rest/api/{self.api}/user/search",
                params={"query": email},
                timeout=30,
            )
            resp.raise_for_status()
            users = resp.json() or []
            if users:
                return users[0].get("accountId")
        except Exception:  # noqa: BLE001
            return None
        return None

    # -- schema discovery --------------------------------------------------
    def list_fields(self) -> List[dict]:
        """Return the instance field catalog: [{id, name, custom, schema_custom}]."""
        resp = self.session.get(f"{self.base_url}/rest/api/{self.api}/field", timeout=30)
        resp.raise_for_status()
        out: List[dict] = []
        for f in resp.json() or []:
            schema = f.get("schema") or {}
            out.append({
                "id": f.get("id", ""),
                "name": f.get("name", ""),
                "custom": bool(f.get("custom", False)),
                "schema_custom": schema.get("custom", "") or "",
            })
        return out

    def project_issue_types(self) -> List[dict]:
        """Return [{id, name, subtask}] creatable in the configured project.

        Tries the newer Cloud createmeta endpoint first (the classic one was
        removed on recent Jira Cloud), then falls back to the classic expand
        form used by Server/Data Center.
        """
        key = self.conn.project_key
        if not key:
            return []
        # Newer Cloud endpoint (paged).
        types: List[dict] = []
        start = 0
        try:
            while True:
                resp = self.session.get(
                    f"{self.base_url}/rest/api/{self.api}/issue/createmeta/{key}/issuetypes",
                    params={"startAt": start, "maxResults": 50}, timeout=30,
                )
                if resp.status_code != 200:
                    break
                data = resp.json() or {}
                values = data.get("values") or data.get("issueTypes") or []
                for it in values:
                    types.append({"id": str(it.get("id", "")), "name": it.get("name", ""),
                                  "subtask": bool(it.get("subtask", False))})
                if data.get("isLast", True) or not values:
                    break
                start += len(values)
            if types:
                return _dedupe_types(types)
        except Exception:  # noqa: BLE001 - fall through to classic
            pass
        # Classic form (Server/DC and older Cloud).
        try:
            resp = self.session.get(
                f"{self.base_url}/rest/api/{self.api}/issue/createmeta",
                params={"projectKeys": key, "expand": "projects.issuetypes"}, timeout=30,
            )
            resp.raise_for_status()
            projects = resp.json().get("projects", []) or []
            if projects:
                for it in projects[0].get("issuetypes", []) or []:
                    types.append({"id": str(it.get("id", "")), "name": it.get("name", ""),
                                  "subtask": bool(it.get("subtask", False))})
        except Exception:  # noqa: BLE001
            pass
        return _dedupe_types(types)

    def discover(self) -> dict:
        """One call for the UI: issue types + custom-field catalog + best-guess IDs."""
        warnings: List[str] = []
        fields: List[dict] = []
        try:
            fields = self.list_fields()
        except Exception as e:  # noqa: BLE001
            warnings.append(f"could not read field catalog: {e}")
        try:
            issue_types = self.project_issue_types()
        except Exception as e:  # noqa: BLE001
            issue_types = []
            warnings.append(f"could not read issue types: {e}")
        if not self.conn.project_key:
            warnings.append("Set a project key to discover issue types.")
        custom_fields = [f for f in fields if f["custom"]]
        return {
            "issue_types": issue_types,
            "custom_fields": custom_fields,
            "suggestions": _suggest_fields(fields),
            "warnings": warnings,
        }

    # -- create ------------------------------------------------------------
    def build_fields(self, issue_type: str, summary: str, description: str,
                     priority: str = "", labels: Optional[List[str]] = None,
                     components: Optional[List[str]] = None,
                     assignee_id: str = "", parent_key: str = "",
                     is_subtask: bool = False, story_points: Optional[float] = None,
                     sprint: str = "", team: str = "", fix_versions: Optional[List[str]] = None,
                     due_date: str = "", external_id: str = "") -> dict:
        c = self.conn
        fields: Dict[str, object] = {
            "project": {"key": c.project_key},
            "issuetype": {"name": issue_type},
            "summary": summary[:255] if summary else "(no summary)",
        }
        if description:
            fields["description"] = (
                text_to_adf(description) if self.api == "3" else description
            )
        if priority:
            fields["priority"] = {"name": priority}
        if labels:
            fields["labels"] = labels
        if components:
            fields["components"] = [{"name": comp} for comp in components]
        if assignee_id:
            fields["assignee"] = (
                {"accountId": assignee_id} if c.deployment == "cloud" else {"name": assignee_id}
            )
        if due_date:
            fields["duedate"] = due_date
        if fix_versions:
            fields["fixVersions"] = [{"name": v} for v in fix_versions]
        # Hierarchy: subtasks always use `parent`; epic children use the configured
        # epic-link field when set, otherwise the team-managed `parent` field.
        if parent_key:
            if is_subtask or not c.epic_link_field:
                fields["parent"] = {"key": parent_key}
            else:
                fields[c.epic_link_field] = parent_key
        if sprint and c.sprint_field:
            try:
                fields[c.sprint_field] = int(sprint)
            except ValueError:
                fields[c.sprint_field] = sprint
        if story_points is not None and c.story_points_field:
            fields[c.story_points_field] = story_points
        if team and c.team_field:
            fields[c.team_field] = team
        if external_id and c.rally_id_field:
            fields[c.rally_id_field] = external_id
        return fields

    def create_issue(self, fields: dict, retries: int = 3) -> Tuple[Optional[str], str]:
        url = f"{self.base_url}/rest/api/{self.api}/issue"
        last = ""
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.post(url, json={"fields": fields}, timeout=60)
            except Exception as e:  # noqa: BLE001
                last = str(e)
                time.sleep(min(2 ** attempt, 8))
                continue
            if resp.status_code == 429:
                time.sleep(int(resp.headers.get("Retry-After", min(2 ** attempt, 20))))
                continue
            if resp.status_code in (200, 201):
                return resp.json().get("key"), ""
            # Surface Jira's validation errors verbatim; they're very specific.
            last = f"HTTP {resp.status_code}: {resp.text[:600]}"
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                break
            time.sleep(min(2 ** attempt, 8))
        return None, last

    # -- description (rich text: Rally HTML -> ADF/wiki) --------------------
    def description_from_html(self, html: str):
        """Convert Rally Description HTML to this instance's description format:
        ADF (Cloud, v3) or wiki markup (Server/DC, v2). Tables are preserved."""
        from ..engine.richtext import html_to_adf, html_to_wiki
        return html_to_adf(html) if self.api == "3" else html_to_wiki(html)

    def set_description(self, issue_key: str, value, retries: int = 3) -> Tuple[bool, str]:
        """PUT a new description onto an existing issue. `value` is an ADF dict
        (Cloud) or a wiki-markup string (Server/DC)."""
        url = f"{self.base_url}/rest/api/{self.api}/issue/{issue_key}"
        body = {"fields": {"description": value}}
        last = ""
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.put(url, json=body, timeout=60)
            except Exception as e:  # noqa: BLE001
                last = str(e)
                time.sleep(min(2 ** attempt, 8))
                continue
            if resp.status_code == 429:
                time.sleep(int(resp.headers.get("Retry-After", min(2 ** attempt, 20))))
                continue
            if resp.status_code in (200, 204):
                return True, ""
            last = f"HTTP {resp.status_code}: {resp.text[:600]}"
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                break
            time.sleep(min(2 ** attempt, 8))
        return False, last


        url = f"{self.base_url}/rest/api/{self.api}/issueLink"
        body = {
            "type": {"name": link_type},
            "inwardIssue": {"key": inward_key},
            "outwardIssue": {"key": outward_key},
        }
        try:
            resp = self.session.post(url, json=body, timeout=30)
            if resp.status_code in (200, 201, 204):
                return ""
            return f"link {inward_key}->{outward_key}: HTTP {resp.status_code}"
        except Exception as e:  # noqa: BLE001
            return f"link {inward_key}->{outward_key}: {e}"

    # -- attachments (mirrors add_attachments.py) --------------------------
    def existing_attachment_names(self, issue_key: str) -> set:
        try:
            url = f"{self.base_url}/rest/api/{self.api}/issue/{issue_key}?fields=attachment"
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return {a.get("filename", "") for a in data.get("fields", {}).get("attachment", []) or []}
        except Exception:  # noqa: BLE001
            return set()

    def upload_attachment(self, issue_key: str, file_name: str, content: bytes,
                          retries: int = 3) -> str:
        url = f"{self.base_url}/rest/api/{self.api}/issue/{issue_key}/attachments"
        content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        last = ""
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.post(
                    url, files={"file": (file_name, content, content_type)}, timeout=300
                )
            except Exception as e:  # noqa: BLE001
                last = str(e)
                time.sleep(min(2 ** attempt, 10))
                continue
            if resp.status_code == 429:
                time.sleep(int(resp.headers.get("Retry-After", min(2 ** attempt, 30))))
                continue
            if resp.status_code == 413:
                return "file exceeds the Jira attachment size limit"
            if resp.status_code in (200, 201):
                return ""
            last = f"HTTP {resp.status_code}: {resp.text[:300]}"
            time.sleep(min(2 ** attempt, 10))
        return last or "upload failed"

    def find_key_by_rally_id(self, rally_id_field: str, rally_id: str) -> Optional[str]:
        """Resolve a Rally FormattedID to the Jira issue key whose Rally-ID field
        matches it (JQL). Returns None when there is no unambiguous single match.
        """
        if not rally_id_field or not rally_id:
            return None
        field_ref = rally_id_field if rally_id_field.startswith("customfield_") else f'"{rally_id_field}"'
        jql = f'{field_ref} ~ "{rally_id}"'
        # Jira Cloud replaced GET /search with GET /search/jql; Server/DC keep /search.
        url = (f"{self.base_url}/rest/api/3/search/jql" if self.api == "3"
               else f"{self.base_url}/rest/api/2/search")
        try:
            resp = self.session.get(url, params={"jql": jql, "fields": "key", "maxResults": 5}, timeout=30)
            resp.raise_for_status()
            issues = resp.json().get("issues", []) or []
            if len(issues) == 1:
                return issues[0].get("key")
            return None
        except Exception:  # noqa: BLE001
            return None
