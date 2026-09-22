"""Turn an uploaded source document into canonical NormalizedIssue records.

Two input shapes are supported:
  * "jira_all_issues" — the converted file produced by the repo's proven
    rally_to_jira.py engine (recommended fast path: zero manual mapping).
  * "rally_export"    — a raw Rally CSV, mapped via a user-defined template in
    the Mapping Studio.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..schemas import NormalizedIssue
from .description import format_for_type
from .mapping import (DEFAULT_JIRA_ALL_TEMPLATE, merge_lookups,
                      normalize_artifact_type)

# Signal columns that identify a converted jira_all_issues.csv.
_JIRA_ALL_SIGNALS = {"Issue Id", "Issue Type", "Summary"}
# Attachment URL columns emitted by the converter.
_ATTACHMENT_COLS = [f"Attachment {i}" for i in range(1, 6)]


def load_dataframe(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    except Exception:
        return pd.read_csv(path, encoding="utf-8-sig", dtype=str, engine="python", keep_default_na=False)


def detect_kind(df: pd.DataFrame) -> str:
    cols = set(df.columns)
    return "jira_all_issues" if _JIRA_ALL_SIGNALS.issubset(cols) else "rally_export"


def _cell(row: pd.Series, col: str) -> str:
    if not col or col not in row.index:
        return ""
    v = row[col]
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _split_labels(value: str) -> List[str]:
    if not value:
        return []
    # Labels emitted by the converter are space-separated; also accept ; and ,.
    parts = re.split(r"[;,]", value)
    if len(parts) == 1:
        parts = value.split()
    return [p.strip() for p in parts if p.strip()]


def _to_number(value: str) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_iso_date(value: str) -> str:
    """Normalize a variety of date strings to ISO (YYYY-MM-DD); passthrough on miss."""
    if not value:
        return ""
    clean = re.sub(r"_+", " ", value).strip()
    clean = re.sub(r"\s+(EDT|EST|PST|CST|MST|MDT|UTC)$", "", clean).strip()
    dt = pd.to_datetime(clean, errors="coerce")
    return dt.strftime("%Y-%m-%d") if pd.notna(dt) else value


def _extract_idref(value: str) -> str:
    """Pull the bare Rally id token from a parent ref.

    Handles both 'F132418: SF: ...' and Rally's type-prefixed
    'Feature F228109: ...' by matching the FormattedID token (e.g. F228109,
    US2165890, DE369021) wherever it sits.
    """
    if not value:
        return ""
    s = str(value)
    m = re.search(r"\b[A-Z]{1,3}\d+\b", s)
    if m:
        return m.group(0)
    token = s.split(":")[0].strip()
    return token.split()[0] if " " in token else token


def _apply_transform(name: str, value: str):
    if name == "labels":
        return _split_labels(value)
    if name == "number":
        return _to_number(value)
    if name == "date":
        return _to_iso_date(value)
    if name == "idref":
        return _extract_idref(value)
    return value


def _extract_attachments(row: pd.Series) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for col in _ATTACHMENT_COLS:
        url = _cell(row, col)
        if url:
            name = url.rsplit("/", 1)[-1].split("?")[0] or "attachment"
            out.append({"name": name, "url": url})
    return out


def _norm_col(name: str) -> str:
    return re.sub(r"[\s_]+", " ", str(name or "")).strip().lower()


def _translate_value(value, vm_ci: Dict[str, str]):
    """Case-insensitive value-map lookup for a scalar or each element of a list."""
    if isinstance(value, list):
        return [vm_ci.get(str(x).strip().lower(), x) for x in value]
    if isinstance(value, str):
        return vm_ci.get(value.strip().lower(), value)
    return value


def apply_mapping(df: pd.DataFrame, template: Dict[str, Any],
                  force_type: Optional[str] = None) -> List[NormalizedIssue]:
    base_maps = template.get("field_maps", [])
    profiles = template.get("profiles", {}) or {}
    issue_type_field = template.get("issue_type_field", "Issue Type")
    value_maps = {vm["field"]: vm.get("values", {}) for vm in template.get("value_maps", [])}
    # Case-insensitive index so catalog/value-map keys match regardless of case.
    value_maps_ci = {f: {str(k).strip().lower(): v for k, v in (m or {}).items()}
                     for f, m in value_maps.items()}
    list_fields = {"labels", "components", "fix_versions", "links"}
    core_fields = set(NormalizedIssue.model_fields.keys())
    # Resolve source columns tolerant of separators/case (e.g. "Formatted_ID").
    colmap = {_norm_col(c): c for c in df.columns}

    def col(name: str) -> str:
        return colmap.get(_norm_col(name), name)

    def maps_for(row: pd.Series) -> List[Dict[str, Any]]:
        if not profiles:
            return base_maps
        atype = force_type or normalize_artifact_type(_cell(row, col(issue_type_field)))
        return profiles.get(atype) or base_maps

    issues: List[NormalizedIssue] = []
    for _, row in df.iterrows():
        data: Dict[str, Any] = {}
        extra: Dict[str, Any] = {}
        for fm in maps_for(row):
            tgt = fm.get("target")
            if not tgt:
                continue
            # Coalesce: first non-empty column across `sources`, else `source`.
            srcs = fm.get("sources") or ([fm["source"]] if fm.get("source") else [])
            raw = ""
            for s in srcs:
                v = _cell(row, col(s))
                if v:
                    raw = v
                    break
            val = _apply_transform(fm.get("transform", ""), raw)
            # Route core fields onto the model; everything else onto `extra`.
            if tgt in core_fields:
                data[tgt] = val
            else:
                extra[tgt] = val

        # Skip empty padding rows.
        if not (data.get("summary") or data.get("row_id") or data.get("external_id")):
            continue

        # One source id column can feed both hierarchy (row_id) and the Rally-ID
        # stamp (external_id); default one from the other when only one is mapped.
        if not data.get("external_id") and data.get("row_id"):
            data["external_id"] = data["row_id"]
        if not data.get("row_id") and data.get("external_id"):
            data["row_id"] = data["external_id"]

        # Ensure the issue type is set (column value, forced type, or profile key).
        if not data.get("issue_type"):
            data["issue_type"] = force_type or normalize_artifact_type(_cell(row, col(issue_type_field)))

        # Reformat embedded section headings in the description for Feature /
        # User Story / Defect (mirrors rally_to_jira.format_description).
        if data.get("description"):
            data["description"] = format_for_type(data["description"], data.get("issue_type", ""))

        # Normalize core list fields into lists before translation.
        for lf in list_fields:
            if lf in data and not isinstance(data[lf], list):
                data[lf] = _split_labels(str(data[lf])) if data[lf] else []

        # Apply value-map / Jira Catalog translations (case-insensitive) across
        # every mapped field — core and extra, scalars and lists.
        for bucket in (data, extra):
            for field, vm_ci in value_maps_ci.items():
                if field in bucket:
                    bucket[field] = _translate_value(bucket[field], vm_ci)

        data["extra"] = extra
        data["attachments"] = _extract_attachments(row)
        data["raw"] = {c: _cell(row, c) for c in df.columns}
        issues.append(NormalizedIssue(**data))
    return issues


# ---------------------------------------------------------------------------
# Multi-file (per-artifact) Rally extract -> normalized issues with hierarchy.
# Mirrors rally_to_jira.py: each file is one artifact type; parents resolve
# across files by Rally Formatted ID.
# ---------------------------------------------------------------------------

# Which already-loaded artifact types can be a valid parent of each child type.
_PARENT_TYPES: Dict[str, Tuple[str, ...]] = {
    "User Story": ("Feature",),
    "Task": ("User Story", "Feature"),
    "Defect": ("User Story", "Feature"),
}


def detect_artifact_type(filename: str) -> str:
    """Best-effort artifact type from a per-type export filename."""
    n = (filename or "").lower()
    if "epic" in n:
        return "Epic"
    if "feature" in n:
        return "Feature"
    if "defect" in n or "bug" in n:
        return "Defect"
    if "task" in n:
        return "Task"
    if "stor" in n:  # story / stories / userstories
        return "User Story"
    return ""


def validate_rally_file(df: pd.DataFrame, artifact_type: str) -> List[str]:
    """Lightweight input validation for a per-type Rally export."""
    cols = {_norm_col(c) for c in df.columns}
    warns: List[str] = []
    if not ({"formatted id", "formattedid", "objectid"} & cols):
        warns.append("No 'Formatted ID' column — hierarchy ids may be missing.")
    if not ({"name", "title"} & cols):
        warns.append("No 'Name'/'Title' column — summaries may be empty.")
    if len(df) == 0:
        warns.append("File has no data rows.")
    if not artifact_type:
        warns.append("Could not detect the artifact type from the filename — set it manually.")
    return warns


def transform_batch(files: List[Tuple[str, Path]], template: Dict[str, Any],
                    lookups: Optional[List[Dict[str, Any]]] = None) -> List[NormalizedIssue]:
    """Transform several per-type Rally files, resolving parent links across them.

    `files` is a list of (artifact_type, csv_path). The template's per-artifact
    profile is applied to each file; Jira Catalog `lookups` are folded in first.
    A child issue keeps its parent link only when the parent Formatted ID exists
    in the matching parent file (unresolved links are dropped, like the script).
    """
    tpl = merge_lookups(template, lookups) if lookups else template
    grouped: List[Tuple[str, List[NormalizedIssue]]] = []
    for atype, path in files:
        df = load_dataframe(Path(path))
        grouped.append((atype, apply_mapping(df, tpl, force_type=atype)))

    ids_by_type: Dict[str, set] = {}
    for atype, issues in grouped:
        bucket = ids_by_type.setdefault(atype, set())
        for it in issues:
            if it.row_id:
                bucket.add(it.row_id)

    out: List[NormalizedIssue] = []
    for atype, issues in grouped:
        parent_types = _PARENT_TYPES.get(atype)
        valid_parents: set = set()
        for pt in parent_types or ():
            valid_parents |= ids_by_type.get(pt, set())
        for it in issues:
            if it.parent_row_id and parent_types and it.parent_row_id not in valid_parents:
                it.parent_row_id = ""       # unresolved parent -> no link
            if not parent_types:
                it.parent_row_id = ""        # top-level type (Epic / Feature)
            out.append(it)
    return out


def transform_source(path: Path, template: Optional[Dict[str, Any]],
                     force_type: Optional[str] = None) -> List[NormalizedIssue]:
    df = load_dataframe(path)
    kind = detect_kind(df)
    tpl = template
    if tpl is None:
        tpl = DEFAULT_JIRA_ALL_TEMPLATE if kind == "jira_all_issues" else None
    if tpl is None:
        raise ValueError(
            "This looks like a raw Rally export. Choose or create a mapping template "
            "in the Mapping Studio before migrating."
        )
    return apply_mapping(df, tpl, force_type=force_type)
