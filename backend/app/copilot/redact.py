"""Reversible PII redaction for text sent to the model.

Emails become stable placeholders (<email_1>) and are restored in anything the
model sends back (tool arguments, streamed answers). Secrets are masked one-way.
Names are not detectable by pattern, so they are not redacted.
"""
from __future__ import annotations

import re
from typing import Any, Dict

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_SECRET = re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+|(?:api[_-]?key|token|secret|password)\s*[:=]\s*)([^\s,;]+)|\b(ATATT[A-Za-z0-9_\-=]{20,})\b|\b(bearer|basic)\s+([A-Za-z0-9+/_=-]{12,})")
_PLACEHOLDER = re.compile(r"<email_(\d+)>")


class Redactor:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._fwd: Dict[str, str] = {}
        self._rev: Dict[str, str] = {}
        self._secret_fwd: Dict[str, str] = {}
        self._secret_rev: Dict[str, str] = {}

    def _secret(self, m: "re.Match[str]") -> str:
        secret = m.group(2) or m.group(3) or m.group(5)
        if secret not in self._secret_fwd:
            token = f"<secret_{len(self._secret_fwd) + 1}>"
            self._secret_fwd[secret] = token
            self._secret_rev[token] = secret
        prefix = m.group(1) or ((m.group(4) + " ") if m.group(4) else "")
        return prefix + self._secret_fwd[secret]

    def _email(self, m: "re.Match[str]") -> str:
        real = m.group(0)
        key = real.lower()
        if key not in self._fwd:
            token = f"<email_{len(self._fwd) + 1}>"
            self._fwd[key] = token
            self._rev[token] = real
        return self._fwd[key]

    def to_model(self, text: str) -> str:
        if not text:
            return text
        text = _SECRET.sub(self._secret, text)
        return _EMAIL.sub(self._email, text) if self.enabled else text

    def from_model(self, text: str) -> str:
        if not text:
            return text
        text = re.sub(r"<secret_(\d+)>", "[credential protected]", text)
        return _PLACEHOLDER.sub(lambda m: self._rev.get(m.group(0), m.group(0)), text) if self.enabled else text

    def _tool_from_model(self, text: str) -> str:
        if not text:
            return text
        text = re.sub(r"<secret_(\d+)>", lambda m: self._secret_rev.get(m.group(0), m.group(0)), text)
        return _PLACEHOLDER.sub(lambda m: self._rev.get(m.group(0), m.group(0)), text) if self.enabled else text

    def safe_to_store(self, text: str) -> str:
        """Persist messages with credential values masked, without changing existing email handling."""
        return _SECRET.sub(lambda m: (m.group(1) or ((m.group(4) + " ") if m.group(4) else "")) + "<redacted_secret>", text or "")

    def obj_to_model(self, obj: Any) -> Any:
        return self._walk(obj, self.to_model)

    def obj_from_model(self, obj: Any) -> Any:
        return self._walk(obj, self._tool_from_model)

    def _walk(self, obj: Any, fn) -> Any:
        if isinstance(obj, str):
            return fn(obj)
        if isinstance(obj, list):
            return [self._walk(x, fn) for x in obj]
        if isinstance(obj, dict):
            return {fn(k) if isinstance(k, str) else k: self._walk(v, fn) for k, v in obj.items()}
        return obj

    def stream(self) -> "StreamRestorer":
        return StreamRestorer(self)


class StreamRestorer:
    """Restores placeholders in streamed tokens, holding back a possible partial `<email_N>`."""

    def __init__(self, red: Redactor) -> None:
        self._red = red
        self._buf = ""

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        cut = self._buf.rfind("<")
        if cut != -1 and ">" not in self._buf[cut:] and len(self._buf) - cut <= 12:
            ready, self._buf = self._buf[:cut], self._buf[cut:]
        else:
            ready, self._buf = self._buf, ""
        return self._red.from_model(ready)

    def flush(self) -> str:
        ready, self._buf = self._buf, ""
        return self._red.from_model(ready)
