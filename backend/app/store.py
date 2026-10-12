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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entity_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                payload TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT 'user',
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE (entity_type, entity_id, version)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS copilot_conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS copilot_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                meta TEXT NOT NULL DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS copilot_proposals (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL DEFAULT '',
                tool TEXT NOT NULL,
                risk TEXT NOT NULL DEFAULT 'write',
                args TEXT NOT NULL,
                preview TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT NOT NULL DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now')),
                resolved_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS copilot_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT '',
                event TEXT NOT NULL,
                tool TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now'))
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


def save_lookup(payload: Dict[str, Any], author: str = "user", message: str = "") -> Dict[str, Any]:
    name = payload.get("name", "Untitled lookup")
    kind = payload.get("kind", "")
    side = payload.get("side", "rally_to_jira")
    entries = json.dumps(payload.get("entries", {}))
    with _lock, _conn() as conn:
        if payload.get("id"):
            prev = conn.execute("SELECT name, kind, side, entries FROM lookups WHERE id=?",
                                (payload["id"],)).fetchone()
            has_history = conn.execute(
                "SELECT 1 FROM entity_versions WHERE entity_type='lookup' AND entity_id=?",
                (payload["id"],)).fetchone()
            if prev and not has_history:  # preserve pre-versioning state as the baseline
                _snapshot(conn, "lookup", int(payload["id"]),
                          {"name": prev["name"], "kind": prev["kind"], "side": prev["side"],
                           "entries": json.loads(prev["entries"])}, "user", "Baseline")
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
        _snapshot(conn, "lookup", lookup_id,
                  {"name": name, "kind": kind, "side": side, "entries": json.loads(entries)},
                  author, message)
    result = dict(payload)
    result["id"] = lookup_id
    return result


def delete_lookup(lookup_id: int) -> None:
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM lookups WHERE id = ?", (lookup_id,))


# ---------------------------------------------------------------------------
# Entity versions (catalog history; powers diff / restore / copilot undo)
# ---------------------------------------------------------------------------
def _snapshot(conn: sqlite3.Connection, entity_type: str, entity_id: int,
              payload: Dict[str, Any], author: str, message: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS v FROM entity_versions WHERE entity_type=? AND entity_id=?",
        (entity_type, entity_id),
    ).fetchone()
    last = conn.execute(
        "SELECT payload FROM entity_versions WHERE entity_type=? AND entity_id=? AND version=?",
        (entity_type, entity_id, row["v"]),
    ).fetchone()
    body = json.dumps(payload, sort_keys=True)
    if last and last["payload"] == body:
        return int(row["v"])  # identical to the latest snapshot; skip
    version = int(row["v"]) + 1
    conn.execute(
        "INSERT INTO entity_versions (entity_type, entity_id, version, payload, author, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (entity_type, entity_id, version, body, author, message),
    )
    return version


def list_versions(entity_type: str, entity_id: int) -> List[Dict[str, Any]]:
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT version, author, message, created_at, payload FROM entity_versions "
            "WHERE entity_type=? AND entity_id=? ORDER BY version DESC",
            (entity_type, entity_id),
        ).fetchall()
    out = []
    for r in rows:
        data = json.loads(r["payload"])
        out.append({"version": r["version"], "author": r["author"], "message": r["message"],
                    "created_at": r["created_at"], "size": len(data.get("entries", data))})
    return out


def get_version(entity_type: str, entity_id: int, version: int) -> Optional[Dict[str, Any]]:
    with _lock, _conn() as conn:
        r = conn.execute(
            "SELECT version, author, message, created_at, payload FROM entity_versions "
            "WHERE entity_type=? AND entity_id=? AND version=?",
            (entity_type, entity_id, version),
        ).fetchone()
    if not r:
        return None
    return {"version": r["version"], "author": r["author"], "message": r["message"],
            "created_at": r["created_at"], "payload": json.loads(r["payload"])}


# ---------------------------------------------------------------------------
# Copilot: conversations, proposals, audit
# ---------------------------------------------------------------------------
def ensure_conversation(conv_id: str, title: str = "") -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO copilot_conversations (id, title) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET updated_at=datetime('now')",
            (conv_id, title[:80]),
        )


def add_message(conv_id: str, role: str, content: str, meta: Optional[Dict[str, Any]] = None) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO copilot_messages (conversation_id, role, content, meta) VALUES (?, ?, ?, ?)",
            (conv_id, role, content, json.dumps(meta or {})),
        )


def list_conversations(limit: int = 30) -> List[Dict[str, Any]]:
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT id, title, updated_at FROM copilot_conversations ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_conversation(conv_id: str) -> Optional[Dict[str, Any]]:
    with _lock, _conn() as conn:
        c = conn.execute("SELECT id, title, updated_at FROM copilot_conversations WHERE id=?",
                         (conv_id,)).fetchone()
        if not c:
            return None
        msgs = conn.execute(
            "SELECT role, content, meta, created_at FROM copilot_messages WHERE conversation_id=? ORDER BY id",
            (conv_id,),
        ).fetchall()
    return {**dict(c), "messages": [{**dict(m), "meta": json.loads(m["meta"])} for m in msgs]}


def delete_conversation(conv_id: str) -> None:
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM copilot_messages WHERE conversation_id=?", (conv_id,))
        conn.execute("DELETE FROM copilot_conversations WHERE id=?", (conv_id,))


def save_proposal(pid: str, conv_id: str, tool: str, risk: str,
                  args: Dict[str, Any], preview: Dict[str, Any]) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO copilot_proposals (id, conversation_id, tool, risk, args, preview) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pid, conv_id, tool, risk, json.dumps(args), json.dumps(preview)),
        )


def _proposal_row(r) -> Dict[str, Any]:
    return {"id": r["id"], "conversation_id": r["conversation_id"], "tool": r["tool"],
            "risk": r["risk"], "args": json.loads(r["args"]), "preview": json.loads(r["preview"]),
            "status": r["status"], "result": json.loads(r["result"]), "created_at": r["created_at"],
            "resolved_at": r["resolved_at"]}


def get_proposal(pid: str) -> Optional[Dict[str, Any]]:
    with _lock, _conn() as conn:
        r = conn.execute("SELECT * FROM copilot_proposals WHERE id=?", (pid,)).fetchone()
    return _proposal_row(r) if r else None


def list_proposals(conv_id: str) -> List[Dict[str, Any]]:
    with _lock, _conn() as conn:
        rows = conn.execute("SELECT * FROM copilot_proposals WHERE conversation_id=? ORDER BY created_at",
                            (conv_id,)).fetchall()
    return [_proposal_row(r) for r in rows]


def resolve_proposal(pid: str, status: str, result: Optional[Dict[str, Any]] = None) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE copilot_proposals SET status=?, result=?, resolved_at=datetime('now') WHERE id=?",
            (status, json.dumps(result or {}), pid),
        )


def audit(conv_id: str, event: str, tool: str = "", detail: Optional[Dict[str, Any]] = None) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO copilot_audit (conversation_id, event, tool, detail) VALUES (?, ?, ?, ?)",
            (conv_id, event, tool, json.dumps(detail or {}, default=str)),
        )


def list_audit(limit: int = 100) -> List[Dict[str, Any]]:
    with _lock, _conn() as conn:
        rows = conn.execute("SELECT * FROM copilot_audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]


# ---------------------------------------------------------------------------
# Knowledge index (SQLite FTS5) for the copilot's documentation search
# ---------------------------------------------------------------------------
def knowledge_rebuild(rows: List[Dict[str, str]]) -> bool:
    """Replace the index. Returns False when this SQLite build lacks FTS5."""
    with _lock, _conn() as conn:
        try:
            conn.execute("DROP TABLE IF EXISTS knowledge")
            conn.execute("CREATE VIRTUAL TABLE knowledge USING fts5(source, heading, body)")
        except sqlite3.OperationalError:
            return False
        conn.executemany("INSERT INTO knowledge (source, heading, body) VALUES (?, ?, ?)",
                         [(r["source"], r["heading"], r["body"]) for r in rows])
    return True


def knowledge_search(match: str, limit: int = 4) -> List[Dict[str, str]]:
    with _lock, _conn() as conn:
        try:
            rows = conn.execute(
                "SELECT source, heading, body FROM knowledge WHERE knowledge MATCH ? ORDER BY bm25(knowledge) LIMIT ?",
                (match, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(r) for r in rows]
