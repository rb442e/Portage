"""Mapping model + built-in templates.

A mapping template translates *any* source document (a Rally CSV export, or the
already-converted jira_all_issues.csv) into Portage's canonical NormalizedIssue.
The UI's Mapping Studio edits these templates; power users can also just point
Portage at a pre-converted jira_all_issues.csv and use the built-in template.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Canonical target fields the migrator understands.
CANONICAL_FIELDS: List[str] = [
    "row_id", "parent_row_id", "external_id", "parent_external_id", "issue_type",
    "summary", "description", "status", "priority", "assignee", "reporter",
    "labels", "components", "story_points", "sprint", "team", "fix_versions",
    "start_date", "due_date", "links",
]

# Typed catalog of canonical fields (ConnectALL-style data types). The data type
# drives the default transform, UI hints and light validation.
#   string | text | number | date | datetime | duration | user | option | array | id | url
CANONICAL_FIELD_DEFS: List[Dict[str, str]] = [
    {"field": "issue_type", "label": "Issue Type", "data_type": "option"},
    {"field": "summary", "label": "Summary", "data_type": "string"},
    {"field": "description", "label": "Description", "data_type": "text"},
    {"field": "status", "label": "Status", "data_type": "option"},
    {"field": "priority", "label": "Priority", "data_type": "option"},
    {"field": "assignee", "label": "Assignee", "data_type": "user"},
    {"field": "reporter", "label": "Reporter", "data_type": "user"},
    {"field": "labels", "label": "Labels", "data_type": "array"},
    {"field": "components", "label": "Components", "data_type": "array"},
    {"field": "sprint", "label": "Sprint", "data_type": "id"},
    {"field": "story_points", "label": "Story Points", "data_type": "number"},
    {"field": "original_estimate", "label": "Original Estimate", "data_type": "duration"},
    {"field": "team", "label": "Team", "data_type": "id"},
    {"field": "fix_versions", "label": "Fix Version/s", "data_type": "array"},
    {"field": "milestones", "label": "Milestones", "data_type": "array"},
    {"field": "start_date", "label": "Start Date", "data_type": "date"},
    {"field": "due_date", "label": "Due Date", "data_type": "date"},
    {"field": "created", "label": "Created", "data_type": "datetime"},
    {"field": "row_id", "label": "Issue Id (hierarchy)", "data_type": "id"},
    {"field": "parent_row_id", "label": "Parent Id (hierarchy)", "data_type": "id"},
    {"field": "external_id", "label": "Rally ID", "data_type": "id"},
    {"field": "links", "label": "Issue Links", "data_type": "array"},
    # Extended Jira fields (carried through 'extra'; used in file export).
    {"field": "epic_name", "label": "Epic Name", "data_type": "string"},
    {"field": "epic_id", "label": "Epic ID", "data_type": "id"},
    {"field": "feature_name", "label": "Feature Name", "data_type": "string"},
    {"field": "feature_id", "label": "Feature ID", "data_type": "id"},
    {"field": "severity", "label": "Severity", "data_type": "option"},
    {"field": "environment", "label": "Environment", "data_type": "string"},
    {"field": "rca", "label": "RCA", "data_type": "text"},
    {"field": "root_cause", "label": "Root Cause", "data_type": "option"},
    {"field": "state", "label": "State", "data_type": "option"},
    {"field": "schedule_state", "label": "Schedule State", "data_type": "option"},
    {"field": "itpr", "label": "ITPR", "data_type": "string"},
    {"field": "parent", "label": "Parent", "data_type": "id"},
    {"field": "link", "label": "Link", "data_type": "url"},
]

FIELD_TYPE: Dict[str, str] = {d["field"]: d["data_type"] for d in CANONICAL_FIELD_DEFS}
FIELD_LABEL: Dict[str, str] = {d["field"]: d["label"] for d in CANONICAL_FIELD_DEFS}

# All data types the UI offers for source/destination fields.
DATA_TYPES: List[str] = [
    "string", "text", "number", "date", "datetime", "duration",
    "user", "option", "array", "id", "url",
]

# The transform implied by a field's data type (used for auto-assignment).
TYPE_DEFAULT_TRANSFORM: Dict[str, str] = {
    "array": "labels", "number": "number", "date": "date",
}

# Artifact types shown in the Mapping Studio, and how raw source values normalize
# to those profile keys.
ARTIFACT_TYPES: List[str] = ["Epic", "Feature", "User Story", "Task", "Defect"]
TYPE_ALIASES: Dict[str, str] = {
    "story": "User Story", "user story": "User Story", "userstory": "User Story",
    "defect": "Defect", "bug": "Defect", "epic": "Epic", "feature": "Feature",
    "task": "Task", "sub-task": "Task", "subtask": "Task",
}


def normalize_artifact_type(value: str) -> str:
    return TYPE_ALIASES.get((value or "").strip().lower(), (value or "").strip())

# Built-in template for the repo's converted jira_all_issues.csv. Because that
# file is produced by the existing, battle-tested rally_to_jira.py engine, this
# gives an out-of-the-box "live create" path with zero manual mapping.
DEFAULT_JIRA_ALL_TEMPLATE: Dict[str, Any] = {
    "name": "Jira converted export (built-in)",
    "description": "Maps the columns of jira_all_issues.csv produced by rally_to_jira.py.",
    "issue_type_field": "Issue Type",
    "field_maps": [
        {"source": "Issue Id", "target": "row_id"},
        {"source": "Parent Id", "target": "parent_row_id"},
        {"source": "Rally ID", "target": "external_id"},
        {"source": "Issue Type", "target": "issue_type"},
        {"source": "Summary", "target": "summary"},
        {"source": "Description", "target": "description"},
        {"source": "Status", "target": "status"},
        {"source": "Priority", "target": "priority"},
        {"source": "Assignee", "target": "assignee"},
        {"source": "Reporter", "target": "reporter"},
        {"source": "Labels", "target": "labels", "transform": "labels"},
        {"source": "Components", "target": "components", "transform": "labels"},
        {"source": "Story Points", "target": "story_points", "transform": "number"},
        {"source": "Sprint", "target": "sprint"},
        {"source": "Team", "target": "team"},
        {"source": "Fix Version/s", "target": "fix_versions", "transform": "labels"},
        {"source": "Start Date", "target": "start_date"},
        {"source": "Due Date", "target": "due_date"},
        {"source": "Issue Links", "target": "links", "transform": "labels"},
    ],
    "value_maps": [],
}

# Reasonable default normalized-type -> Jira issue-type name mapping.
DEFAULT_TYPE_MAP: Dict[str, str] = {
    "Epic": "Epic",
    "Feature": "Feature",
    "Story": "Story",
    "User Story": "Story",
    "Task": "Sub-task",
    "Sub-task": "Sub-task",
    "Bug": "Bug",
    "Defect": "Bug",
    "Test Case": "Test",
    "Test Set": "Test",
}

# Processing order guarantees parents exist before their children are created.
TYPE_ORDER = ["Epic", "Feature", "Story", "User Story", "Bug", "Defect", "Task", "Sub-task", "Test Case", "Test Set"]


def order_index(issue_type: str) -> int:
    try:
        return TYPE_ORDER.index(issue_type)
    except ValueError:
        return len(TYPE_ORDER)


# Which canonical field(s) each Jira Catalog kind translates.
#   user    -> assignee/reporter (via user_mapping: Name -> Email)
#   sprint  -> Iteration values, which land in Fix Version/s (via sprint_mapping)
#   team    -> team (via team_mapping)
#   version -> unused for now (do not apply version_mapping)
LOOKUP_FIELDS: Dict[str, List[str]] = {
    "sprint": ["sprint", "fix_versions"],
    "team": ["team"],
    "version": [],
    "user": ["assignee", "reporter"],
}


def _reverse_name(name: str) -> str:
    """'Last, First M' -> 'First M Last' so 'First Last' Rally values still match."""
    if "," not in name:
        return ""
    last, _, first = name.partition(",")
    first, last = first.strip(), last.strip()
    return f"{first} {last}".strip() if first and last else ""


def merge_lookups(template: Dict[str, Any], lookups: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fold Jira Catalog value mappings into the template's value_maps.

    Each catalog is one simple source-value -> target-value table for a kind
    (sprint/version/user/team). Its entries are applied to that kind's canonical
    field(s) at transform time, translating Rally values to their Jira
    equivalents (sprint/version names or IDs, user emails, team IDs).
    """
    merged: Dict[str, Dict[str, str]] = {}
    for vm in template.get("value_maps", []) or []:
        field = vm.get("field")
        if field:
            merged.setdefault(field, {}).update(vm.get("values", {}) or {})
    for lk in lookups or []:
        kind = lk.get("kind", "")
        entries = lk.get("entries", {}) or {}
        if kind == "user":
            # Also accept the reversed 'First Last' form of each 'Last, First' key.
            expanded = dict(entries)
            for k, v in entries.items():
                rev = _reverse_name(k)
                if rev:
                    expanded.setdefault(rev, v)
            entries = expanded
        for field in LOOKUP_FIELDS.get(kind, []):
            merged.setdefault(field, {}).update(entries)

    out = dict(template)
    out["value_maps"] = [{"field": f, "values": v} for f, v in merged.items()]
    return out
