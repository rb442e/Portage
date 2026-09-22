"""Symmetric encryption for secrets stored at rest (Jira/Rally API tokens).

Uses Fernet (AES-128-CBC + HMAC). The key comes from ``PORTAGE_SECRET_KEY`` if
set — either a valid urlsafe-base64 Fernet key or any passphrase (derived via
SHA-256) — otherwise a key is generated once and stored in the data dir with
0600 permissions. Rotating/losing the key makes previously stored secrets
undecryptable (they're returned as empty and must be re-entered).
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


def _derive_key(passphrase: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(passphrase.encode()).digest())


def _load_key() -> bytes:
    env = os.environ.get("PORTAGE_SECRET_KEY", "").strip()
    if env:
        try:
            Fernet(env.encode())      # already a valid Fernet key
            return env.encode()
        except Exception:             # noqa: BLE001 - treat as a passphrase
            return _derive_key(env)
    key_path: Path = settings.data_dir / ".secret.key"
    if key_path.exists():
        return key_path.read_bytes().strip()
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key


_fernet = Fernet(_load_key())


def encrypt(text: str) -> str:
    return _fernet.encrypt(text.encode()).decode() if text else ""


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet.decrypt(token.encode()).decode()
    except (InvalidToken, Exception):  # noqa: BLE001 - unreadable -> treat as absent
        return ""
