"""Accounts, sign-in, sessions and role-based access control for the Portage API.

Sign in with email + password (or a one-time emailed code). Sign-up and password reset prove inbox ownership with a
six-digit emailed code. Who may use Portage: users an admin added or approved, addresses in PORTAGE_ADMIN_EMAILS
(always admins), and anyone whose domain is in PORTAGE_ALLOWED_EMAIL_DOMAINS (viewers). Anyone else who signs up
waits for an admin to approve them (PORTAGE_SIGNUP=off turns that off).
Roles: admin > member > viewer. PORTAGE_AUTH_DISABLED=1 turns all of this off for local development.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import threading
import time
from email.message import EmailMessage
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import store
from .config import settings
from .store import _conn, _lock

log = logging.getLogger("portage.auth")

ROLES = ("admin", "member", "viewer")
RANK = {"viewer": 0, "member": 1, "admin": 2}
ROLE_LABELS = {"admin": "Admin", "member": "Team member", "viewer": "Viewer"}
COOKIE = "portage_session"
CODE_TTL = 10 * 60
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = 30
MAX_CODES_PER_HOUR = 5
IP_WINDOW, IP_LIMIT = 10 * 60, 60
LOGIN_WINDOW, MAX_LOGIN_FAILURES = 15 * 60, 5
PASSWORD_MIN, PASSWORD_MAX = 10, 128
STATUSES = ("active", "disabled", "pending", "rejected")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,}$")
LOCAL_USER = {"email": "local", "name": "Local user", "role": "admin", "status": "active", "auth_disabled": True}

PUBLIC = {("GET", "/api/health"), ("GET", "/api/auth/config"), ("GET", "/api/auth/me"),
          ("POST", "/api/auth/request-code"), ("POST", "/api/auth/verify"), ("POST", "/api/auth/logout"),
          ("POST", "/api/auth/login"), ("POST", "/api/auth/signup"), ("POST", "/api/auth/signup/verify"),
          ("POST", "/api/auth/password/forgot"), ("POST", "/api/auth/password/reset")}
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def enabled() -> bool:
    return not _flag("PORTAGE_AUTH_DISABLED")


def _csv(name: str) -> List[str]:
    return [x.strip().lower().lstrip("@") for x in os.environ.get(name, "").split(",") if x.strip()]


def admin_emails() -> List[str]:
    return _csv("PORTAGE_ADMIN_EMAILS")


def allowed_domains() -> List[str]:
    return _csv("PORTAGE_ALLOWED_EMAIL_DOMAINS")


def signup_open() -> bool:
    return os.environ.get("PORTAGE_SIGNUP", "request").strip().lower() != "off"


def session_hours() -> int:
    try:
        return max(1, min(int(os.environ.get("PORTAGE_SESSION_HOURS", "168")), 24 * 90))
    except ValueError:
        return 168


def normalize(email: str) -> str:
    email = (email or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise AuthError(400, "Enter a valid email address")
    return email


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Passwords (scrypt from the standard library)
# ---------------------------------------------------------------------------
_COMMON = {"password", "password1", "password12", "password123", "1234567890", "12345678910", "qwertyuiop",
           "letmein123", "welcome123", "portage123", "iloveyou12", "administrator", "changeme123", "abc1234567"}


def check_password(password: str, email: str = "") -> None:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN:
        raise AuthError(400, f"Use at least {PASSWORD_MIN} characters for your password")
    if len(password) > PASSWORD_MAX:
        raise AuthError(400, f"Use at most {PASSWORD_MAX} characters for your password")
    low = password.lower()
    local = email.split("@")[0].lower() if email else ""
    if low in _COMMON or len(set(password)) < 5 or (local and len(local) >= 4 and local in low):
        raise AuthError(400, "That password is too easy to guess. Try a longer phrase or mix in other words.")


def hash_password(password: str) -> str:
    salt, n, r, p = secrets.token_bytes(16), 2 ** 14, 8, 1
    key = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, key = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                              dklen=len(key) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc.hex(), key)


_DUMMY_HASH = hash_password(secrets.token_hex(16))   # keeps unknown-email logins as slow as real ones


def init_tables() -> None:
    with _lock, _conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'viewer',
            status TEXT NOT NULL DEFAULT 'active', invited_by TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')), last_login_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS auth_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, salt TEXT NOT NULL, code_hash TEXT NOT NULL,
            created_at REAL NOT NULL, expires_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            used INTEGER NOT NULL DEFAULT 0)""")
        conn.execute("CREATE INDEX IF NOT EXISTS auth_codes_email ON auth_codes(email, created_at)")
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, email TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
            user_agent TEXT NOT NULL DEFAULT '')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS signups (
            email TEXT PRIMARY KEY, name TEXT NOT NULL, password_hash TEXT NOT NULL, created_at REAL NOT NULL)""")
        conn.execute("CREATE TABLE IF NOT EXISTS login_failures (email TEXT NOT NULL, at REAL NOT NULL)")
        for ddl in ("ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''",
                    "ALTER TABLE auth_codes ADD COLUMN purpose TEXT NOT NULL DEFAULT 'signin'"):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def _user_row(email: str) -> Optional[Dict[str, Any]]:
    with _lock, _conn() as conn:
        r = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(r) if r else None


def _public(u: Dict[str, Any]) -> Dict[str, Any]:
    return {"email": u["email"], "name": u.get("name") or "", "role": u["role"], "status": u["status"],
            "invited_by": u.get("invited_by") or "", "created_at": u.get("created_at"),
            "last_login_at": u.get("last_login_at"), "has_password": bool(u.get("password_hash"))}


def sign_in_role(email: str) -> Optional[str]:
    """Role this address gets when signing in, or None if it may not sign in."""
    user = _user_row(email)
    if user and user["status"] != "active":
        return None
    if email in admin_emails():
        return "admin"
    if user:
        return user["role"]
    if email.rsplit("@", 1)[1] in allowed_domains():
        return "viewer"
    return None


def list_users() -> List[Dict[str, Any]]:
    with _lock, _conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY status = 'pending' DESC, role = 'admin' DESC, email").fetchall()
    return [_public(dict(r)) for r in rows]


def _active_admins() -> int:
    with _lock, _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'").fetchone()[0]


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise AuthError(400, f"Role must be one of: {', '.join(ROLES)}")
    return role


def add_user(email: str, role: str, actor: str, name: str = "") -> Dict[str, Any]:
    email, role = normalize(email), _check_role(role)
    if _user_row(email):
        raise AuthError(409, f"{email} already has access")
    with _lock, _conn() as conn:
        conn.execute("INSERT INTO users (email, name, role, invited_by) VALUES (?, ?, ?, ?)",
                     (email, name.strip()[:120], role, actor))
    store.audit("", "user_added", email, {"role": role, "by": actor})
    return _public(_user_row(email))


def update_user(email: str, actor: str, role: Optional[str] = None, status: Optional[str] = None) -> Dict[str, Any]:
    email = normalize(email)
    user = _user_row(email)
    if not user:
        raise AuthError(404, "User not found")
    if email == actor:
        raise AuthError(400, "You can't change your own access. Ask another admin.")
    if role is not None:
        _check_role(role)
        if email in admin_emails() and role != "admin":
            raise AuthError(400, "This address is listed in PORTAGE_ADMIN_EMAILS and is always an admin")
    if status is not None and status not in ("active", "disabled", "rejected"):
        raise AuthError(400, "Status must be active, disabled or rejected")
    new_role, new_status = role or user["role"], status or user["status"]
    if user["role"] == "admin" and user["status"] == "active" and (new_role != "admin" or new_status != "active") \
            and _active_admins() <= 1:
        raise AuthError(400, "Portage needs at least one active admin")
    with _lock, _conn() as conn:
        conn.execute("UPDATE users SET role = ?, status = ? WHERE email = ?", (new_role, new_status, email))
        if new_status != "active":
            conn.execute("DELETE FROM sessions WHERE email = ?", (email,))
    store.audit("", "user_updated", email, {"role": new_role, "status": new_status, "by": actor})
    if user["status"] == "pending" and new_status in ("active", "rejected"):
        _notify(email, "Your Portage account is ready" if new_status == "active" else "Your Portage access request",
                f"An admin approved your Portage account as {ROLE_LABELS[new_role]}. Sign in with your email and password.\n"
                if new_status == "active" else "An admin reviewed your request for Portage access and did not approve it.\n")
    return _public(_user_row(email))


def remove_user(email: str, actor: str) -> None:
    email = normalize(email)
    user = _user_row(email)
    if not user:
        raise AuthError(404, "User not found")
    if email == actor:
        raise AuthError(400, "You can't remove yourself. Ask another admin.")
    if user["role"] == "admin" and user["status"] == "active" and _active_admins() <= 1:
        raise AuthError(400, "Portage needs at least one active admin")
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM users WHERE email = ?", (email,))
        conn.execute("DELETE FROM sessions WHERE email = ?", (email,))
    store.audit("", "user_removed", email, {"by": actor})


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------
def dev_log_codes() -> bool:
    return _flag("PORTAGE_AUTH_DEV_LOG_CODES")


def email_configured() -> bool:
    return bool(os.environ.get("PORTAGE_SMTP_HOST", "").strip()) or dev_log_codes()


def _mail(to: str, subject: str, body: str) -> None:
    host = os.environ.get("PORTAGE_SMTP_HOST", "").strip()
    if not host:
        log.warning("Email to %s (PORTAGE_AUTH_DEV_LOG_CODES is on; never use it in production)\nSubject: %s\n%s",
                    to, subject, body)
        return
    use_ssl = _flag("PORTAGE_SMTP_SSL")
    port = int(os.environ.get("PORTAGE_SMTP_PORT", "465" if use_ssl else "587"))
    sender = os.environ.get("PORTAGE_SMTP_FROM", "").strip() or os.environ.get("PORTAGE_SMTP_USER", "").strip()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)
    context = ssl.create_default_context()
    smtp = smtplib.SMTP_SSL(host, port, timeout=15, context=context) if use_ssl else smtplib.SMTP(host, port, timeout=15)
    with smtp:
        if not use_ssl and os.environ.get("PORTAGE_SMTP_STARTTLS", "1") != "0":
            smtp.starttls(context=context)
        user = os.environ.get("PORTAGE_SMTP_USER", "").strip()
        if user:
            smtp.login(user, os.environ.get("PORTAGE_SMTP_PASSWORD", ""))
        smtp.send_message(msg)


_CODE_WORDS = {"signin": "sign-in code", "signup": "verification code", "reset": "password reset code"}


def _send(email: str, code: str, purpose: str = "signin") -> None:
    what = _CODE_WORDS[purpose]
    _mail(email, f"{code} is your Portage {what}",
          f"Your Portage {what} is {code}\n\nIt expires in {CODE_TTL // 60} minutes and can be used once. "
          "If you didn't request it, you can ignore this email.\n")


def _notify(to: str, subject: str, body: str) -> None:
    """Best-effort mail; a delivery failure is logged and never reveals anything to the caller."""
    if not email_configured():
        return
    try:
        _mail(to, subject, body)
    except Exception:
        log.exception("Could not send email to %s", to)


# ---------------------------------------------------------------------------
# Codes and sessions
# ---------------------------------------------------------------------------
_ip_hits: Dict[str, List[float]] = {}
_ip_lock = threading.Lock()


def _ip_allowed(ip: str) -> bool:
    now = time.time()
    with _ip_lock:
        hits = [t for t in _ip_hits.get(ip, []) if now - t < IP_WINDOW]
        if len(hits) >= IP_LIMIT:
            _ip_hits[ip] = hits
            return False
        _ip_hits[ip] = hits + [now]
        return True


def _guard(ip: str) -> None:
    if not email_configured():
        raise AuthError(503, "Email is not configured on this server. An administrator must set PORTAGE_SMTP_HOST.")
    if not _ip_allowed(ip):
        raise AuthError(429, "Too many attempts. Wait a few minutes and try again.")


def _issue_code(email: str, purpose: str) -> None:
    """Create and email a code, respecting per-address limits. Delivery failures are only logged."""
    now = time.time()
    with _lock, _conn() as conn:
        recent = conn.execute("SELECT created_at FROM auth_codes WHERE email = ? AND created_at > ? ORDER BY created_at DESC",
                              (email, now - 3600)).fetchall()
        if len(recent) >= MAX_CODES_PER_HOUR or (recent and now - recent[0][0] < RESEND_COOLDOWN):
            return
        code, salt = f"{secrets.randbelow(10 ** 6):06d}", secrets.token_hex(16)
        conn.execute("UPDATE auth_codes SET used = 1 WHERE email = ? AND used = 0", (email,))
        conn.execute("INSERT INTO auth_codes (email, salt, code_hash, created_at, expires_at, purpose) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (email, salt, _hash(salt, email, code), now, now + CODE_TTL, purpose))
    try:
        _send(email, code, purpose)
    except Exception:  # the answer to the browser must not reveal that this address exists
        log.exception("Could not send a %s code to %s", purpose, email)


def _consume_code(email: str, code: str, purpose: str) -> bool:
    code = re.sub(r"\s", "", code or "")
    now, ok = time.time(), False
    with _lock, _conn() as conn:  # raising inside would roll back the attempt counter, so callers raise afterwards
        row = conn.execute("SELECT * FROM auth_codes WHERE email = ? AND used = 0 AND expires_at > ? AND purpose = ? "
                           "ORDER BY created_at DESC LIMIT 1", (email, now, purpose)).fetchone()
        if row and re.fullmatch(r"\d{6}", code) and hmac.compare_digest(row["code_hash"], _hash(row["salt"], email, code)):
            conn.execute("UPDATE auth_codes SET used = 1 WHERE id = ?", (row["id"],))
            ok = True
        elif row:
            attempts = row["attempts"] + 1
            conn.execute("UPDATE auth_codes SET attempts = ?, used = ? WHERE id = ?",
                         (attempts, int(attempts >= MAX_ATTEMPTS), row["id"]))
    return ok


def _bad_code() -> AuthError:
    return AuthError(400, "That code is incorrect or has expired. Request a new one.")


def _start_session(email: str, role: str, user_agent: str, event: str = "signed_in") -> tuple:
    token, now = secrets.token_urlsafe(32), time.time()
    with _lock, _conn() as conn:
        conn.execute("UPDATE users SET role = ?, last_login_at = datetime('now') WHERE email = ?", (role, email))
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute("DELETE FROM login_failures WHERE email = ? OR at < ?", (email, now - LOGIN_WINDOW))
        conn.execute("INSERT INTO sessions (token_hash, email, created_at, expires_at, user_agent) VALUES (?, ?, ?, ?, ?)",
                     (_hash(token), email, now, now + session_hours() * 3600, user_agent[:200]))
    store.audit("", event, email, {"role": role})
    return token, _public(_user_row(email))


def _ensure_user(email: str, role: str, **fields: str) -> None:
    with _lock, _conn() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            conn.execute("INSERT INTO users (email, role, invited_by) VALUES (?, ?, ?)", (email, role, "self sign-up"))
        for key, value in fields.items():
            conn.execute(f"UPDATE users SET {key} = ? WHERE email = ?", (value, email))


# ---- one-time code sign-in -------------------------------------------------
def request_code(email: str, ip: str = "") -> None:
    """Send a sign-in code if the address may sign in. The answer never reveals whether it can."""
    email = normalize(email)
    _guard(ip)
    if sign_in_role(email) is not None:
        _issue_code(email, "signin")


def verify_code(email: str, code: str, user_agent: str = "") -> tuple:
    """Return (session_token, user). One active code per address, five attempts, ten minutes."""
    email = normalize(email)
    ok = _consume_code(email, code, "signin")
    role = sign_in_role(email) if ok else None
    if role is None:
        raise _bad_code()
    _ensure_user(email, role)
    return _start_session(email, role, user_agent)


# ---- password sign-in -------------------------------------------------------
def _recent_failures(email: str) -> int:
    with _lock, _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM login_failures WHERE email = ? AND at > ?",
                            (email, time.time() - LOGIN_WINDOW)).fetchone()[0]


def login(email: str, password: str, ip: str = "", user_agent: str = "") -> tuple:
    email = normalize(email)
    if not _ip_allowed(ip) or _recent_failures(email) >= MAX_LOGIN_FAILURES:
        raise AuthError(429, "Too many failed attempts. Wait 15 minutes or reset your password.")
    user = _user_row(email)
    stored = (user or {}).get("password_hash") or ""
    if not verify_password(password or "", stored or _DUMMY_HASH) or not stored:
        with _lock, _conn() as conn:
            conn.execute("INSERT INTO login_failures (email, at) VALUES (?, ?)", (email, time.time()))
        raise AuthError(401, "Incorrect email or password.")
    if user["status"] == "pending":
        raise AuthError(403, "Your account is waiting for an admin to approve it. We'll email you when it's ready.")
    role = sign_in_role(email)
    if role is None:
        raise AuthError(403, "This account doesn't have access to Portage. Contact your administrator.")
    return _start_session(email, role, user_agent)


# ---- sign-up ----------------------------------------------------------------
def _admin_recipients() -> List[str]:
    with _lock, _conn() as conn:
        rows = conn.execute("SELECT email FROM users WHERE role = 'admin' AND status = 'active'").fetchall()
    return list(dict.fromkeys([r[0] for r in rows] + admin_emails()))[:10]


def signup_start(email: str, password: str, ip: str = "", name: str = "") -> None:
    """Hold the new account and email a verification code. Same answer for every address."""
    email, name = normalize(email), (name or "").strip()[:120]
    check_password(password, email)
    _guard(ip)
    user = _user_row(email)
    if user and user["status"] in ("disabled", "rejected"):
        return
    if user and user["status"] == "pending":
        _notify(email, "Your Portage account is waiting for approval",
                "You already asked for a Portage account. An admin will review it and we'll email you.\n")
        return
    if user and user.get("password_hash"):
        _notify(email, "You already have a Portage account",
                "Someone tried to create a Portage account with this address, which already has one. Sign in, or use "
                "\"Forgot password\" if you need a new password. If it wasn't you, you can ignore this email.\n")
        return
    if not user and sign_in_role(email) is None and not signup_open():
        return
    with _lock, _conn() as conn:
        conn.execute("INSERT INTO signups (email, name, password_hash, created_at) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT(email) DO UPDATE SET name = excluded.name, password_hash = excluded.password_hash, "
                     "created_at = excluded.created_at", (email, name, hash_password(password), time.time()))
    _issue_code(email, "signup")


def signup_verify(email: str, code: str, user_agent: str = "") -> Dict[str, Any]:
    """Finish sign-up. Returns {"status": "signed_in", "token", "user"} or {"status": "pending"}."""
    email = normalize(email)
    ok = _consume_code(email, code, "signup")
    with _lock, _conn() as conn:
        held = conn.execute("SELECT * FROM signups WHERE email = ? AND created_at > ?",
                            (email, time.time() - 3600)).fetchone()
    if not ok or not held:
        raise _bad_code()
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM signups WHERE email = ?", (email,))
    role = sign_in_role(email)
    if role is not None:
        _ensure_user(email, role, name=held["name"], password_hash=held["password_hash"])
        token, user = _start_session(email, role, user_agent, "signed_up")
        return {"status": "signed_in", "token": token, "user": user}
    if not signup_open() or _user_row(email):
        raise _bad_code()
    with _lock, _conn() as conn:
        conn.execute("INSERT INTO users (email, name, role, status, invited_by, password_hash) "
                     "VALUES (?, ?, 'viewer', 'pending', 'sign-up request', ?)", (email, held["name"], held["password_hash"]))
    store.audit("", "signup_requested", email, {"name": held["name"]})
    who = f"{held['name']} ({email})" if held["name"] else email
    for admin in _admin_recipients():
        _notify(admin, "New Portage access request",
                f"{who} asked for access to Portage. Review it under Users in Portage.\n")
    return {"status": "pending"}


# ---- forgotten password ------------------------------------------------------
def forgot_password(email: str, ip: str = "") -> None:
    email = normalize(email)
    _guard(ip)
    user = _user_row(email)
    if user and user["status"] == "active" and sign_in_role(email) is not None:
        _issue_code(email, "reset")


def reset_password(email: str, code: str, password: str, user_agent: str = "") -> tuple:
    email = normalize(email)
    check_password(password, email)
    ok = _consume_code(email, code, "reset")
    role = sign_in_role(email) if ok else None
    if role is None or not _user_row(email):
        raise _bad_code()
    with _lock, _conn() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE email = ?", (hash_password(password), email))
        conn.execute("DELETE FROM sessions WHERE email = ?", (email,))   # sign out everywhere else
    _notify(email, "Your Portage password was changed",
            "Your Portage password was just changed. If this wasn't you, contact your administrator now.\n")
    return _start_session(email, role, user_agent, "password_reset")


def user_for_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token or len(token) > 100:
        return None
    with _lock, _conn() as conn:
        r = conn.execute("SELECT u.* FROM sessions s JOIN users u ON u.email = s.email "
                         "WHERE s.token_hash = ? AND s.expires_at > ? AND u.status = 'active'",
                         (_hash(token), time.time())).fetchone()
    return _public(dict(r)) if r else None


def logout(token: Optional[str]) -> None:
    if token:
        with _lock, _conn() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
def required_role(method: str, path: str) -> str:
    safe = method in SAFE_METHODS
    if path.startswith("/api/auth/users") or path == "/api/copilot/audit":
        return "admin"
    if not safe and (path.startswith("/api/settings") or path == "/api/copilot/settings"
                     or path in ("/api/connections/save", "/api/connections/saved")):
        return "admin"
    if safe or path == "/api/copilot/chat" or path.startswith("/api/copilot/attachments"):
        return "viewer"
    return "member"


def _origin_ok(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    return origin in settings.cors_origins or urlparse(origin).netloc == request.headers.get("host", "")


def current_user(request: Request) -> Dict[str, Any]:
    return getattr(request.state, "user", None) or LOCAL_USER


async def middleware(request: Request, call_next):
    path, method = request.url.path, request.method
    if not path.startswith("/api/") or method == "OPTIONS":
        return await call_next(request)
    if method not in SAFE_METHODS and not _origin_ok(request):
        return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    if not enabled():
        request.state.user = LOCAL_USER
        return await call_next(request)
    if (method, path) in PUBLIC:
        return await call_next(request)
    user = await run_in_threadpool(user_for_token, request.cookies.get(COOKIE))
    if not user:
        return JSONResponse({"detail": "Sign in to continue"}, status_code=401)
    need = required_role(method, path)
    if RANK[user["role"]] < RANK[need]:
        return JSONResponse({"detail": f"Your role ({ROLE_LABELS[user['role']]}) can't do this. "
                                       f"Ask an admin for {ROLE_LABELS[need]} access."}, status_code=403)
    request.state.user = user
    return await call_next(request)
