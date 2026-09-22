"""Pre-flight validation of Jira-ID-dependent mappings.

Before a migration is generated, every value that must resolve to a Jira id
(user email, team id, sprint/version id) is checked against the selected Jira
Catalog files. Values that are empty, or already in target form (email / UUID /
numeric id), pass through; anything else is reported so the user can add it to
the catalog first.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_NUMID = re.compile(r"^\d+$")

# (issue field, catalog kind, mapping file, human label, "already valid?" test)
_CHECKS = [
    ("assignee", "user", "user_mapping", "Assignee", lambda v: bool(_EMAIL.search(v))),
    ("reporter", "user", "user_mapping", "Reporter", lambda v: bool(_EMAIL.search(v))),
    ("team", "team", "team_mapping", "Team", lambda v: bool(_UUID.match(v))),
    ("fix_versions", "sprint", "sprint_mapping", "Fix Version/s (Iteration)", lambda v: bool(_NUMID.match(v))),
]


def _reverse_name(name: str) -> str:
    if "," not in name:
        return ""
    last, _, first = name.partition(",")
    first, last = first.strip(), last.strip()
    return f"{first} {last}".strip() if first and last else ""


def _catalog_keys(lookups: List[Dict[str, Any]]) -> Dict[str, set]:
    by_kind: Dict[str, set] = {}
    for lk in lookups or []:
        kind = lk.get("kind", "")
        keys = by_kind.setdefault(kind, set())
        for k in (lk.get("entries") or {}):
            keys.add(str(k).strip().lower())
            if kind == "user":
                rev = _reverse_name(str(k))
                if rev:
                    keys.add(rev.strip().lower())
    return by_kind


def validate_mappings(issues, lookups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return one issue record per field that has unmapped, non-empty values.

    `issues` must be transformed WITHOUT catalog lookups applied, so raw source
    values are visible.
    """
    keys_by_kind = _catalog_keys(lookups)
    out: List[Dict[str, Any]] = []
    for field, kind, mfile, label, is_ok in _CHECKS:
        catalog_keys = keys_by_kind.get(kind, set())
        catalog_loaded = kind in keys_by_kind
        missing: Dict[str, int] = {}
        for iss in issues:
            raw = getattr(iss, field, None)
            values = raw if isinstance(raw, list) else ([raw] if raw else [])
            for v in values:
                v = str(v).strip()
                if not v:               # empty -> pass on
                    continue
                if is_ok(v):            # already an email / UUID / numeric id
                    continue
                if v.lower() in catalog_keys:
                    continue
                missing[v] = missing.get(v, 0) + 1
        if missing:
            out.append({
                "catalog": kind,
                "field": label,
                "mapping_file": mfile,
                "catalog_loaded": catalog_loaded,
                "missing_values": sorted(missing.keys())[:50],
                "missing_count": len(missing),
                "affected_rows": sum(missing.values()),
            })
    return out
