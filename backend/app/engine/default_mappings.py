"""Per-artifact-type Rally → Jira mapping profiles.

This encodes, as data, the mapping logic that lives in the repo's rally_to_jira
converter — one profile per artifact type (Epic / Feature / User Story / Bug /
Task / Test Case) — with the data type of BOTH the Rally source field and the
Jira destination field. The Mapping Studio renders and edits these; the product
never surfaces the underlying script name.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .legacy_import import DEFAULT_PRIORITY_MAP, DEFAULT_STATUS_MAP


def _m(sources: List[str], source_type: str, target: str, target_type: str,
       transform: str = "", note: str = "") -> Dict[str, object]:
    return {
        "source": sources[0] if sources else "",
        "sources": sources,
        "source_type": source_type,
        "target": target,
        "target_type": target_type,
        "transform": transform,
        "note": note,
    }


# Fields mapped for every artifact type (from _gather_common).
COMMON: List[Dict[str, object]] = [
    _m(["Issue Type", "Type", "Work Item Type"], "option", "issue_type", "option"),
    _m(["Name", "Title"], "string", "summary", "string"),
    _m(["Description"], "text", "description", "text", note="Notes appended as a footer"),
    _m(["Submitted By", "Created By", "Creator"], "user", "reporter", "user", note="first non-empty"),
    _m(["Owner", "Owner Email"], "user", "assignee", "user", note="first non-empty"),
    _m(["State", "Schedule State", "ScheduleState"], "option", "status", "option", note="via Status value map"),
    _m(["Severity", "Priority"], "option", "priority", "option", note="via Priority value map"),
    _m(["Tags"], "array", "labels", "array", "labels"),
    _m(["Iteration", "Iteration Name", "Iteration name"], "array", "fix_versions", "array", "labels", note="Iteration -> Fix Version/s via Sprint lookup"),
    _m(["Team", "Contributing Teams"], "string", "team", "id", note="via Team lookup"),
    _m(["Creation Date", "Created"], "datetime", "created", "datetime", "date"),
    _m(["Release"], "date", "start_date", "date", "date"),
    _m(["Planned End Date"], "date", "due_date", "date", "date"),
    _m(["Formatted ID", "FormattedID", "ObjectID"], "id", "external_id", "id"),
    _m(["Formatted ID", "FormattedID", "ObjectID"], "id", "row_id", "id", note="hierarchy id"),
]

_EPIC = [
    _m(["Name"], "string", "epic_name", "string", note="= Summary"),
    _m(["ITPR", "itpr"], "string", "itpr", "string"),
]
_FEATURE = [
    _m(["Refined Estimate"], "number", "story_points", "number", "number"),
    _m(["Refined Estimate"], "number", "original_estimate", "duration", note="hours → time estimate"),
    _m(["Parent Epic"], "string", "epic_id", "id", note="extract id from 'Epic F…'"),
    _m(["Parent Epic"], "string", "epic_name", "string"),
    _m(["Parent"], "string", "parent", "id"),
    _m(["State"], "option", "state", "option", note="via Feature state value map"),
    _m(["Schedule State", "State"], "option", "schedule_state", "option", note="raw passthrough"),
]
_STORY = [
    _m(["Plan Estimate", "PlanEstimate"], "number", "story_points", "number", "number"),
    _m(["Parent Feature", "Feature"], "string", "feature_id", "id"),
    _m(["Parent Feature"], "string", "feature_name", "string"),
    _m(["Parent Feature", "Parent", "Feature"], "string", "parent_row_id", "id", "idref", note="parent Feature (F####)"),
    _m(["Schedule State", "ScheduleState"], "option", "state", "option", note="via Story state value map"),
]
_TASK = [
    _m(["Parent", "User Story"], "string", "parent_row_id", "id", "idref", note="parent Story/Feature"),
    _m(["Link"], "url", "link", "url"),
]
_BUG = [
    _m(["Priority"], "option", "priority", "option", note="via Defect priority value map (not Severity)"),
    _m(["Severity"], "option", "severity", "option"),
    _m(["Opened Date"], "date", "start_date", "date", "date"),
    _m(["Target Date"], "date", "due_date", "date", "date"),
    _m(["Environment"], "string", "environment", "string"),
    _m(["RCA"], "text", "rca", "text"),
    _m(["Resolution"], "option", "root_cause", "option", note="via Defect root-cause value map"),
    _m(["State"], "option", "state", "option", note="via Defect state value map"),
    _m(["SNOW Incident Number"], "string", "labels", "array", "labels", note="appended to Labels"),
    _m(["Requirement", "Parent"], "string", "parent_row_id", "id", "idref", note="parent Story"),
    _m(["Link"], "url", "link", "url"),
]
_TESTCASE = [
    _m(["WorkProduct", "Requirement"], "string", "parent_row_id", "id", note="parent Story"),
]

_SPECIFIC: Dict[str, List[Dict[str, object]]] = {
    "Epic": _EPIC, "Feature": _FEATURE, "User Story": _STORY,
    "Task": _TASK, "Defect": _BUG,
}


def _merge(common: List[Dict], specific: List[Dict]) -> List[Dict]:
    """Common list, with type-specific entries overriding by target (in place)."""
    out: List[Dict] = [dict(m) for m in common]
    index = {m["target"]: i for i, m in enumerate(out)}
    for m in specific:
        if m["target"] in index:
            out[index[m["target"]]] = dict(m)
        else:
            out.append(dict(m))
            index[m["target"]] = len(out) - 1
    return out


def build_default_template(config_path: Optional[Path]) -> Dict[str, object]:
    status_map = dict(DEFAULT_STATUS_MAP)
    priority_map = dict(DEFAULT_PRIORITY_MAP)
    if config_path and config_path.exists():
        try:
            cfg = yaml.safe_load(config_path.read_text()) or {}
            status_map = cfg.get("status_map", status_map)
            priority_map = cfg.get("priority_map", priority_map)
        except Exception:  # noqa: BLE001
            pass

    profiles = {atype: _merge(COMMON, spec) for atype, spec in _SPECIFIC.items()}
    return {
        "name": "Default Rally → Jira mapping",
        "description": "Field mapping per artifact type, with source and destination data types.",
        "issue_type_field": "Issue Type",
        "field_maps": [dict(m) for m in COMMON],   # fallback for untyped rows
        "profiles": profiles,
        "value_maps": [
            {"field": "status", "values": {str(k): str(v) for k, v in status_map.items()}},
            {"field": "priority", "values": {str(k): str(v) for k, v in priority_map.items()}},
        ],
    }
