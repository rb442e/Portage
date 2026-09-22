"""Rally (WSAPI) connector — the *source* side for live attachment fetch.

Reuses the download approach proven in the repo's add_attachments.py: look up a
work item by FormattedID, enumerate its Attachments collection (paged), and pull
each AttachmentContent (base64) as raw bytes.
"""
from __future__ import annotations

import base64
import time
from typing import Dict, List, Optional, Tuple

import requests

try:
    import truststore as _truststore

    _truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

from ..schemas import RallyConnection


def _api_base(base_url: str) -> str:
    base = (base_url or "https://rally1.rallydev.com").rstrip("/")
    if "/slm/webservice" not in base:
        base = base + "/slm/webservice/v2.0"
    return base


class RallyClient:
    def __init__(self, conn: RallyConnection):
        self.conn = conn
        self.api_base = _api_base(conn.base_url)
        self.session = requests.Session()
        if conn.api_key:
            self.session.headers.update({"ZSESSIONID": conn.api_key})

    def test(self) -> Tuple[bool, str, str]:
        try:
            resp = self.session.get(f"{self.api_base}/user", timeout=30)
            resp.raise_for_status()
            user = resp.json().get("User", {}) or {}
            who = user.get("UserName") or user.get("EmailAddress") or "Rally user"
            return True, "Authenticated", who
        except Exception as e:  # noqa: BLE001
            return False, str(e), ""

    def _scope(self) -> Dict[str, str]:
        """Restrict a query to a single Rally Project by ObjectID, when configured.

        Scopes strictly to that project (no parent/child projects) so a FormattedID
        that belongs to a different project is not matched.
        """
        pid = (getattr(self.conn, "project_object_id", "") or "").strip()
        if not pid:
            return {}
        return {
            "project": f"{self.api_base}/project/{pid}",
            "projectScopeUp": "false",
            "projectScopeDown": "false",
        }

    def _find_attachments_ref(self, formatted_id: str, retries: int = 3) -> Tuple[Optional[str], int]:
        url = f"{self.api_base}/artifact"
        params = {
            "query": f'(FormattedID = "{formatted_id}")',
            "fetch": "FormattedID,ObjectID,Attachments",
            "pagesize": 1,
        }
        params.update(self._scope())
        last: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=60)
                resp.raise_for_status()
                qr = resp.json().get("QueryResult", {}) or {}
                results = qr.get("Results", []) or []
                if not results:
                    return None, 0
                att = results[0].get("Attachments", {}) or {}
                return att.get("_ref"), int(att.get("Count", 0) or 0)
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"Rally lookup failed: {last}")

    def _list_attachments(self, ref: str, retries: int = 3, page_size: int = 100) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        start = 1
        while True:
            params = {"fetch": "Name,Content,ContentType,Size", "pagesize": page_size, "start": start}
            qr = None
            last: Optional[Exception] = None
            for attempt in range(1, retries + 1):
                try:
                    resp = self.session.get(ref, params=params, timeout=60)
                    resp.raise_for_status()
                    qr = resp.json().get("QueryResult", {}) or {}
                    break
                except Exception as e:  # noqa: BLE001
                    last = e
                    time.sleep(min(2 ** attempt, 8))
            if qr is None:
                raise RuntimeError(f"listing Rally attachments failed: {last}")
            results = qr.get("Results", []) or []
            for a in results:
                content = a.get("Content") or {}
                out.append({"name": a.get("Name") or "attachment", "content_ref": content.get("_ref") or ""})
            total = int(qr.get("TotalResultCount", len(out)) or 0)
            start += page_size
            if not results or start > total:
                break
        return out

    def discover_attachments(self, formatted_id: str) -> List[Dict[str, str]]:
        ref, count = self._find_attachments_ref(formatted_id)
        if not ref or not count:
            return []
        return self._list_attachments(ref)

    def fetch_description(self, formatted_id: str, retries: int = 3) -> str:
        """Return an artifact's Description as raw HTML (Rally stores rich text as
        HTML, including <table> markup that the CSV export flattens away)."""
        url = f"{self.api_base}/artifact"
        params = {
            "query": f'(FormattedID = "{formatted_id}")',
            "fetch": "FormattedID,ObjectID,Description",
            "pagesize": 1,
        }
        params.update(self._scope())
        last: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=60)
                resp.raise_for_status()
                qr = resp.json().get("QueryResult", {}) or {}
                results = qr.get("Results", []) or []
                if not results:
                    return ""
                return results[0].get("Description") or ""
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"Rally description fetch failed: {last}")

    def download(self, content_ref: str, retries: int = 3) -> bytes:
        last: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.get(content_ref, params={"fetch": "Content"}, timeout=120)
                resp.raise_for_status()
                data = resp.json().get("AttachmentContent", {}) or {}
                return base64.b64decode(data.get("Content") or "")
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"Rally download failed: {last}")

    def download_url(self, url: str, retries: int = 3) -> bytes:
        """Download an attachment that already has a direct URL (from a CSV export)."""
        last: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.get(url, timeout=120, stream=True)
                resp.raise_for_status()
                return resp.content
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"download failed: {last}")
