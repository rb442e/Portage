"""Field catalog for the visual Mapping Studio.

Supplies the Rally (source) and Jira (destination) fields for each artifact type,
split into COMMON (shown for every artifact) and per-artifact specifics (shown
only when that artifact is selected), plus a clean set of default connections.
"""
from __future__ import annotations

from typing import Dict, List


def _f(key: str, label: str, data_type: str) -> Dict[str, str]:
    return {"key": key, "label": label, "data_type": data_type}


# ---- Rally (source) fields: key = the Rally CSV column name -----------------
RALLY_COMMON: List[Dict[str, str]] = [
    _f("Formatted ID", "Formatted ID", "id"),
    _f("Name", "Name", "string"),
    _f("Description", "Description", "text"),
    _f("Owner", "Owner", "user"),
    _f("Submitted By", "Submitted By", "user"),
    _f("State", "State", "option"),
    _f("Tags", "Tags", "array"),
    _f("Iteration", "Iteration", "array"),
    _f("Team", "Team", "string"),
    _f("Creation Date", "Creation Date", "datetime"),
    _f("Planned End Date", "Planned End Date", "date"),
]
RALLY_SPECIFIC: Dict[str, List[Dict[str, str]]] = {
    "Epic": [_f("ITPR", "ITPR", "string")],
    "Feature": [
        _f("Parent Epic", "Parent Epic", "string"),
        _f("Refined Estimate", "Refined Estimate", "number"),
        _f("Parent", "Parent", "string"),
    ],
    "User Story": [
        _f("Parent Feature", "Parent Feature", "string"),
        _f("Plan Estimate", "Plan Estimate", "number"),
    ],
    "Task": [
        _f("Parent", "Parent", "string"),
        _f("User Story", "User Story", "string"),
        _f("Link", "Link", "url"),
    ],
    "Defect": [
        _f("Severity", "Severity", "option"),
        _f("Priority", "Priority", "option"),
        _f("Resolution", "Resolution", "option"),
        _f("Environment", "Environment", "string"),
        _f("RCA", "RCA", "text"),
        _f("Opened Date", "Opened Date", "date"),
        _f("Target Date", "Target Date", "date"),
        _f("SNOW Incident Number", "SNOW Incident Number", "string"),
        _f("Link", "Link", "url"),
    ],
}

# ---- Jira (destination) fields: key = canonical field name ------------------
JIRA_COMMON: List[Dict[str, str]] = [
    _f("summary", "Summary", "string"),
    _f("description", "Description", "text"),
    _f("assignee", "Assignee", "user"),
    _f("reporter", "Reporter", "user"),
    _f("status", "Status", "option"),
    _f("priority", "Priority", "option"),
    _f("labels", "Labels", "array"),
    _f("sprint", "Sprint", "id"),
    _f("team", "Team", "id"),
    _f("fix_versions", "Fix Version/s", "array"),
    _f("components", "Components", "array"),
    _f("story_points", "Story Points", "number"),
    _f("start_date", "Start Date", "date"),
    _f("due_date", "Due Date", "date"),
    _f("row_id", "Issue Id", "id"),
    _f("parent_row_id", "Parent Id", "id"),
    _f("external_id", "Rally ID", "id"),
]
JIRA_SPECIFIC: Dict[str, List[Dict[str, str]]] = {
    "Epic": [_f("epic_name", "Epic Name", "string"), _f("itpr", "ITPR", "string")],
    "Feature": [
        _f("epic_name", "Epic Name", "string"),
        _f("epic_id", "Epic ID", "id"),
        _f("original_estimate", "Original Estimate", "duration"),
    ],
    "User Story": [
        _f("feature_name", "Feature Name", "string"),
        _f("feature_id", "Feature ID", "id"),
    ],
    "Task": [_f("link", "Link", "url")],
    "Defect": [
        _f("severity", "Severity", "option"),
        _f("root_cause", "Root Cause", "option"),
        _f("environment", "Environment", "string"),
        _f("rca", "RCA", "text"),
        _f("link", "Link", "url"),
    ],
}

# ---- A clean default set of connections (Rally column -> Jira field) --------
_COMMON_CONNS = [
    ("Name", "summary"), ("Description", "description"), ("Owner", "assignee"),
    ("Submitted By", "reporter"), ("State", "status"), ("Tags", "labels"),
    ("Iteration", "fix_versions"), ("Team", "team"),
    ("Planned End Date", "due_date"), ("Formatted ID", "row_id"),
]
DEFAULT_CONNECTIONS: Dict[str, List[Dict[str, str]]] = {
    "Epic": [{"source": s, "target": t} for s, t in _COMMON_CONNS + [("ITPR", "itpr")]],
    "Feature": [{"source": s, "target": t} for s, t in _COMMON_CONNS + [
        ("Parent Epic", "epic_id"), ("Refined Estimate", "story_points")]],
    "User Story": [{"source": s, "target": t} for s, t in _COMMON_CONNS + [
        ("Parent Feature", "parent_row_id"), ("Plan Estimate", "story_points")]],
    "Task": [{"source": s, "target": t} for s, t in _COMMON_CONNS + [
        ("Parent", "parent_row_id"), ("Link", "link")]],
    "Defect": [{"source": s, "target": t} for s, t in _COMMON_CONNS + [
        ("Priority", "priority"), ("Severity", "severity"), ("Resolution", "root_cause"),
        ("Environment", "environment"), ("Opened Date", "start_date"), ("Target Date", "due_date")]],
}


def build_catalog() -> Dict[str, object]:
    from .mapping import ARTIFACT_TYPES

    return {
        "artifacts": ARTIFACT_TYPES,
        "common": {"rally": RALLY_COMMON, "jira": JIRA_COMMON},
        "specific": {
            a: {"rally": RALLY_SPECIFIC.get(a, []), "jira": JIRA_SPECIFIC.get(a, [])}
            for a in ARTIFACT_TYPES
        },
        "defaults": {a: DEFAULT_CONNECTIONS.get(a, []) for a in ARTIFACT_TYPES},
    }
