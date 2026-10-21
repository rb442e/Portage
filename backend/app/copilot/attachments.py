"""Files and screenshots a user attaches to a Sora message.

Text files are read into the prompt (masked like everything else). A screenshot is described once by a local
vision model and the description is what the tool-calling model sees, because vision models rarely support tools.
Files live under the data directory and are purged after a retention period; chat history keeps names only.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import settings as env_config

MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PER_MESSAGE = 5
CONTEXT_CHARS = 6000          # total attachment text per turn; the model context is only 8,192 tokens
TEXT_TYPES = (".txt", ".md", ".csv", ".tsv", ".json", ".log", ".yaml", ".yml", ".xml", ".sql")
_ID = re.compile(r"[0-9a-f]{32}")
_IMAGE_MAGIC = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpeg"), (b"GIF87a", "gif"), (b"GIF89a", "gif"))


class AttachmentError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _dir() -> Path:
    d = env_config.data_dir / "copilot_attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _image_kind(data: bytes) -> Optional[str]:
    for magic, kind in _IMAGE_MAGIC:
        if data.startswith(magic):
            return kind
    return "webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None


def _clean_name(filename: str) -> str:
    base = re.sub(r"[^\w.\- ()]", "_", Path(filename or "attachment").name).strip()
    return (base or "attachment")[:80]


def public(meta: Dict[str, Any]) -> Dict[str, Any]:
    return {k: meta[k] for k in ("id", "name", "kind", "size")}


def save(filename: str, data: bytes) -> Dict[str, Any]:
    """Validate by content (not by the claimed type) and store. Raises AttachmentError."""
    name = _clean_name(filename)
    if not data:
        raise AttachmentError("The file is empty")
    image = _image_kind(data)
    if image:
        if len(data) > MAX_IMAGE_BYTES:
            raise AttachmentError(f"Images can be up to {MAX_IMAGE_BYTES // 2**20} MB", 413)
        kind, mime = "image", f"image/{image}"
    elif Path(name).suffix.lower() in TEXT_TYPES:
        if len(data) > MAX_TEXT_BYTES:
            raise AttachmentError(f"Text files can be up to {MAX_TEXT_BYTES // 2**20} MB", 413)
        if b"\x00" in data[:8192]:
            raise AttachmentError("That file is binary, not text", 415)
        kind, mime = "text", "text/plain"
    else:
        raise AttachmentError("Unsupported file. Attach a screenshot (PNG, JPEG, GIF, WebP) or a text file ("
                              + ", ".join(TEXT_TYPES) + ")", 415)
    aid = uuid.uuid4().hex
    meta = {"id": aid, "name": name, "kind": kind, "mime": mime, "size": len(data), "created": time.time()}
    (_dir() / f"{aid}.bin").write_bytes(data)
    (_dir() / f"{aid}.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def get(aid: str) -> Optional[Dict[str, Any]]:
    if not _ID.fullmatch(aid or ""):                          # an id is never treated as a path
        return None
    try:
        return json.loads((_dir() / f"{aid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read(aid: str) -> bytes:
    return (_dir() / f"{aid}.bin").read_bytes()


def set_description(aid: str, text: str, version: int = 1) -> None:
    meta = get(aid)
    if meta:
        meta["description"] = text
        meta["vision_prompt_version"] = version
        (_dir() / f"{aid}.json").write_text(json.dumps(meta), encoding="utf-8")


def delete(aid: str) -> None:
    if _ID.fullmatch(aid or ""):
        for ext in ("bin", "json"):
            (_dir() / f"{aid}.{ext}").unlink(missing_ok=True)


def purge(days: int) -> int:
    """Delete attachments older than `days`. Returns how many were removed."""
    cutoff, removed = time.time() - days * 86400, 0
    for p in _dir().glob("*.json"):
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("created", 0) < cutoff:
                delete(p.stem)
                removed += 1
        except (OSError, ValueError):
            continue
    return removed


def clean_ids(ids: Optional[List[str]]) -> List[str]:
    seen: List[str] = []
    for i in ids or []:
        if isinstance(i, str) and _ID.fullmatch(i) and i not in seen:
            seen.append(i)
    return seen[:MAX_PER_MESSAGE]


def _csv_summary(text: str, delimiter: str) -> str:
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        return ""
    head, body = rows[0], rows[1:]
    sample = "\n".join(delimiter.join(r) for r in body[:5])
    return f"{len(body)} data rows. Columns: {', '.join(head)}\nFirst rows:\n{sample}"


def text_excerpt(meta: Dict[str, Any], limit: int) -> str:
    text = read(meta["id"]).decode("utf-8", errors="replace")
    suffix = Path(meta["name"]).suffix.lower()
    if suffix in (".csv", ".tsv"):
        text = _csv_summary(text, "\t" if suffix == ".tsv" else ",") or text
    if len(text) > limit:
        text = text[:limit] + f"\n... [truncated: showing {limit} of {len(text)} characters]"
    return text
