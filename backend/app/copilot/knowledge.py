"""Documentation search for the copilot: README/PRODUCT.md plus a built-in glossary (SQLite FTS5)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from .. import store

_ROOT = Path(__file__).resolve().parents[3]

GLOSSARY = [
    ("Mapping Studio", "Mappings connect Rally columns to Jira fields per artifact type (Epic, Feature, User Story, Task, "
     "Defect). Two Rally fields into one Jira field is a fallback: the first non-empty value wins. 'Save as new version' "
     "never overwrites: it creates a new saved mapping named jira_<artifact>_mapping_v<N> (for example jira_us_mapping_v3). "
     "Artifact slugs: Epic=epic, Feature=feature, User Story=us, Task=task, Defect=defect."),
    ("Jira Catalog", "Catalogs translate Rally values into Jira values during migration. Four kinds: sprint (Rally iteration "
     "to Jira sprint name or ID), version (Rally release/milestone to Jira fix version), user (Rally user to Jira email or "
     "accountId), team (Rally team to Jira team name or Atlassian Team ID). Each is a source-to-target table. Catalog "
     "changes are versioned; any version can be restored."),
    ("Value maps", "Value maps translate field values such as status or priority (for example Rally State 'In-Progress' to "
     "Jira status 'In Progress'). They are stored inside a mapping template."),
    ("Migration", "Upload a Rally CSV, choose a mapping, run a dry-run preview (counts by type and warnings), then either "
     "create issues live in Jira (hierarchy and attachments preserved) or export Jira import CSV files. Every run is "
     "recorded in Reports."),
    ("Connections", "Jira needs base URL, email, API token and project key. Rally needs an API key only for live "
     "attachment transfer. Use Discover fields to auto-fill Sprint, Story Points, Team, Epic Link and Rally-ID custom "
     "field IDs. Tokens are never shown to Sora."),
    ("Sora", "Sora is Portage's built-in assistant (open it from the Ask Sora button or with Ctrl/Cmd+K). It answers questions about your mappings, catalogs, source files and migration jobs. Changes it "
     "proposes (mapping edits, catalog additions, restores) are never applied until you click Apply. Applied changes can "
     "be undone by restoring the previous version. Emails are masked before reaching the local model."),
]


def _chunks(source: str, text: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    heading = source
    buf: List[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        for i in range(0, len(body), 1200):
            part = body[i:i + 1200].strip()
            if part:
                out.append({"source": source, "heading": heading, "body": part})
        buf.clear()

    for line in text.splitlines():
        if re.match(r"^#{1,3}\s", line):
            flush()
            heading = line.lstrip("# ").strip()
        else:
            buf.append(line)
    flush()
    return out


def rebuild() -> None:
    rows = [{"source": "Portage guide", "heading": h, "body": b} for h, b in GLOSSARY]
    for name in ("README.md", "PRODUCT.md"):
        p = _ROOT / name
        if p.exists():
            rows.extend(_chunks(name, p.read_text(encoding="utf-8", errors="ignore")))
    store.knowledge_rebuild(rows)


def search(query: str, limit: int = 4) -> List[Dict[str, str]]:
    terms = [t for t in re.findall(r"[A-Za-z0-9_]{3,}", query)][:8]
    if not terms:
        return []
    results = store.knowledge_search(" OR ".join(f'"{t}"' for t in terms), limit)
    return [{"source": r["source"], "heading": r["heading"], "text": r["body"][:700]} for r in results]
