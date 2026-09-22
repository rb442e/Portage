"""Tiny SQLite persistence for mapping templates and finished job reports.

Deliberately dependency-free (stdlib sqlite3). Single-tenant, self-hosted MVP;
swap for Postgres + SQLAlchemy when multi-tenant.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from .config import settings

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                payload TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exports (
                export_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lookups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                side TEXT NOT NULL DEFAULT 'rally_to_jira',
                entries TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        # Add `side` to lookups created before the two-layer split (best-effort).
        try:
            conn.execute("ALTER TABLE lookups ADD COLUMN side TEXT NOT NULL DEFAULT 'rally_to_jira'")
        except sqlite3.OperationalError:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )


# ---------------------------------------------------------------------------
# Key/value settings (e.g. the saved connection profile; secrets encrypted)
# ---------------------------------------------------------------------------
def set_setting(key: str, value: str) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
            (key, value),
        )


def get_setting(key: str) -> Optional[Dict[str, str]]:
    with _lock, _conn() as conn:
        r = conn.execute(
            "SELECT value, updated_at FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    return {"value": r["value"], "updated_at": r["updated_at"]} if r else None


def delete_setting(key: str) -> None:
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))


# ---------------------------------------------------------------------------
# Mapping templates
# ---------------------------------------------------------------------------
def list_mappings() -> List[Dict[str, Any]]:
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT id, name, description, payload FROM mappings ORDER BY updated_at DESC"
        ).fetchall()
    out = []
    for r in rows:
        data = json.loads(r["payload"])
        data["id"] = r["id"]
        data["name"] = r["name"]
        data["description"] = r["description"]
        out.append(data)
    return out


def get_mapping(mapping_id: int) -> Optional[Dict[str, Any]]:
    with _lock, _conn() as conn:
        r = conn.execute(
            "SELECT id, name, description, payload FROM mappings WHERE id = ?",
            (mapping_id,),
        ).fetchone()
    if not r:
        return None
    data = json.loads(r["payload"])
    data["id"] = r["id"]
    data["name"] = r["name"]
    data["description"] = r["description"]
    return data


def save_mapping(payload: Dict[str, Any]) -> Dict[str, Any]:
    body = json.dumps(payload)
    name = payload.get("name", "Untitled mapping")
    description = payload.get("description", "")
    with _lock, _conn() as conn:
        if payload.get("id"):
            conn.execute(
                "UPDATE mappings SET name=?, description=?, payload=?, "
                "updated_at=datetime('now') WHERE id=?",
                (name, description, body, payload["id"]),
            )
            mapping_id = int(payload["id"])
        else:
            cur = conn.execute(
                "INSERT INTO mappings (name, description, payload) VALUES (?, ?, ?)",
                (name, description, body),
            )
            mapping_id = int(cur.lastrowid)
    result = dict(payload)
    result["id"] = mapping_id
    return result


def delete_mapping(mapping_id: int) -> None:
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM mappings WHERE id = ?", (mapping_id,))


# ---------------------------------------------------------------------------
# Job reports (persisted on completion)
# ---------------------------------------------------------------------------
def upsert_job(job_id: str, state: str, payload: Dict[str, Any]) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO jobs (job_id, state, payload) VALUES (?, ?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET state=excluded.state, payload=excluded.payload",
            (job_id, state, json.dumps(payload)),
        )


def list_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT payload FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [json.loads(r["payload"]) for r in rows]


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _lock, _conn() as conn:
        r = conn.execute(
            "SELECT payload FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
    return json.loads(r["payload"]) if r else None


# ---------------------------------------------------------------------------
# Exports (generated Jira import file sets — saved so they can be viewed later)
# ---------------------------------------------------------------------------
def _export_row(r) -> Dict[str, Any]:
    data = json.loads(r["payload"])
    data["export_id"] = r["export_id"]
    data.setdefault("created_at", r["created_at"])
    return data


def save_export(export_id: str, payload: Dict[str, Any]) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO exports (export_id, payload) VALUES (?, ?) "
            "ON CONFLICT(export_id) DO UPDATE SET payload = excluded.payload",
            (export_id, json.dumps(payload)),
        )


def list_exports(limit: int = 100) -> List[Dict[str, Any]]:
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT export_id, payload, created_at FROM exports ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_export_row(r) for r in rows]


def get_export(export_id: str) -> Optional[Dict[str, Any]]:
    with _lock, _conn() as conn:
        r = conn.execute(
            "SELECT export_id, payload, created_at FROM exports WHERE export_id = ?",
            (export_id,),
        ).fetchone()
    return _export_row(r) if r else None


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def _lookup_row(r) -> Dict[str, Any]:
    return {"id": r["id"], "name": r["name"], "kind": r["kind"],
            "side": r["side"] if "side" in r.keys() else "rally_to_jira",
            "entries": json.loads(r["entries"])}


def list_lookups(kind: Optional[str] = None, side: Optional[str] = None) -> List[Dict[str, Any]]:
    clauses, params = [], []
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if side:
        clauses.append("side = ?")
        params.append(side)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _lock, _conn() as conn:
        rows = conn.execute(
            f"SELECT id, name, kind, side, entries FROM lookups{where} ORDER BY updated_at DESC",
            tuple(params),
        ).fetchall()
    return [_lookup_row(r) for r in rows]


def get_lookup(lookup_id: int) -> Optional[Dict[str, Any]]:
    with _lock, _conn() as conn:
        r = conn.execute(
            "SELECT id, name, kind, side, entries FROM lookups WHERE id = ?", (lookup_id,)
        ).fetchone()
    return _lookup_row(r) if r else None


def get_lookups(ids: List[int]) -> List[Dict[str, Any]]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _lock, _conn() as conn:
        rows = conn.execute(
            f"SELECT id, name, kind, side, entries FROM lookups WHERE id IN ({placeholders})",
            tuple(ids),
        ).fetchall()
    return [_lookup_row(r) for r in rows]


def save_lookup(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = payload.get("name", "Untitled lookup")
    kind = payload.get("kind", "")
    side = payload.get("side", "rally_to_jira")
    entries = json.dumps(payload.get("entries", {}))
    with _lock, _conn() as conn:
        if payload.get("id"):
            conn.execute(
                "UPDATE lookups SET name=?, kind=?, side=?, entries=?, updated_at=datetime('now') WHERE id=?",
                (name, kind, side, entries, payload["id"]),
            )
            lookup_id = int(payload["id"])
        else:
            cur = conn.execute(
                "INSERT INTO lookups (name, kind, side, entries) VALUES (?, ?, ?, ?)",
                (name, kind, side, entries),
            )
            lookup_id = int(cur.lastrowid)
    result = dict(payload)
    result["id"] = lookup_id
    return result


def delete_lookup(lookup_id: int) -> None:
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM lookups WHERE id = ?", (lookup_id,))
