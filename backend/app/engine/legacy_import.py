"""Lift the rally_to_jira.py mapping recipe into a visual Studio template.

This is the "flagship" on-ramp: the proven, hand-written rules in
rally_to_jira.py become seed data for the product — coalesce chains, transforms
and value maps — pre-filled so the org edits a spec instead of Python. Value
maps are read from the repo's config.yaml when present, else the script's
built-in defaults are used.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml

# Mirrors rally_to_jira.py's DEFAULT_STATUS_MAP / DEFAULT_PRIORITY_MAP so the
# import works even without a config.yaml on disk.
DEFAULT_STATUS_MAP = {
    "Defined": "To Do", "Prepare": "Ready", "In-Progress": "In Progress",
    "Completed": "In Review", "Done": "Accepted",
}
DEFAULT_PRIORITY_MAP = {
    "Crash / Blocker": "Highest", "Blocker": "Highest", "Critical": "Highest",
    "Major": "High", "High": "High", "Normal": "Medium", "Medium": "Medium",
    "Minor": "Low", "Low": "Low", "Trivial": "Lowest",
}

# The column-coalesce + transform recipe encoded in rally_to_jira.py's
# _gather_common(). Each entry mirrors a get_col(..., get_col(...)) fallback chain.
LEGACY_FIELD_MAPS: List[Dict[str, object]] = [
    {"sources": ["Issue Type", "Type", "Work Item Type"], "target": "issue_type"},
    {"sources": ["Name", "Title"], "target": "summary"},
    {"sources": ["Description"], "target": "description"},
    {"sources": ["Submitted By", "Created By", "Creator"], "target": "reporter"},
    {"sources": ["Owner", "Owner Email"], "target": "assignee"},
    {"sources": ["State", "Schedule State", "ScheduleState"], "target": "status"},
    {"sources": ["Severity", "Priority"], "target": "priority"},
    {"sources": ["Tags"], "target": "labels", "transform": "labels"},
    {"sources": ["Iteration Name", "Iteration name", "Iteration"], "target": "sprint"},
    {"sources": ["Team", "Contributing Teams"], "target": "team"},
    {"sources": ["Milestones", "Milestones/Release ID", "Release"], "target": "fix_versions", "transform": "labels"},
    {"sources": ["Plan Estimate", "PlanEstimate", "Refined Estimate"], "target": "story_points", "transform": "number"},
    {"sources": ["Planned End Date", "Target Date"], "target": "due_date", "transform": "date"},
    {"sources": ["Opened Date", "Release"], "target": "start_date", "transform": "date"},
    {"sources": ["Formatted ID", "FormattedID", "ObjectID"], "target": "row_id"},
    {"sources": ["Formatted ID", "FormattedID", "ObjectID"], "target": "external_id"},
    {"sources": ["Parent", "Parent Feature", "Parent Epic"], "target": "parent_row_id"},
]


def build_legacy_template(config_path: Optional[Path]) -> Dict[str, object]:
    status_map = dict(DEFAULT_STATUS_MAP)
    priority_map = dict(DEFAULT_PRIORITY_MAP)
    notes: List[str] = []

    if config_path and config_path.exists():
        try:
            cfg = yaml.safe_load(config_path.read_text()) or {}
            status_map = cfg.get("status_map", status_map)
            priority_map = cfg.get("priority_map", priority_map)
            notes.append(f"Loaded status/priority value maps from {config_path.name}.")
        except Exception as e:  # noqa: BLE001
            notes.append(f"Could not parse {config_path.name} ({e}); used built-in defaults.")
    else:
        notes.append("config.yaml not found; used rally_to_jira.py's built-in status/priority maps.")

    notes.append("Reporter/assignee/status/priority use coalesce (first non-empty column).")
    notes.append("Date fields normalize to ISO; labels/versions split into arrays.")

    template = {
        "name": "Rally → Jira (imported from rally_to_jira.py)",
        "description": "Field mapping, transforms and value maps lifted from rally_to_jira.py.",
        "issue_type_field": "Issue Type",
        "field_maps": [dict(fm) for fm in LEGACY_FIELD_MAPS],
        "value_maps": [
            {"field": "status", "values": {str(k): str(v) for k, v in status_map.items()}},
            {"field": "priority", "values": {str(k): str(v) for k, v in priority_map.items()}},
        ],
    }
    return {"template": template, "notes": notes}
