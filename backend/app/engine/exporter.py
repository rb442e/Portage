"""Generate Jira CSV-importer files from normalized issues.

The live path creates work items through the API; this path writes the same
mapped + looked-up data as downloadable CSVs for Jira's built-in CSV importer.
Produces a consolidated jira_all_issues.csv plus one file per issue type, so the
output mirrors the layout the repo's rally_to_jira.py already emits.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from ..schemas import NormalizedIssue
from .mapping import DEFAULT_TYPE_MAP, FIELD_LABEL

BASE_COLUMNS = [
    "Issue Id", "Parent Id", "Issue Type", "Summary", "Description", "Status",
    "Priority", "Labels", "Components", "Sprint", "Story Points", "Assignee",
    "Reporter", "Fix Version/s", "Team", "Start Date", "Due Date", "Issue Links",
    "Rally ID",
]


def _resolve_type(issue_type: str, type_map: Dict[str, str]) -> str:
    return (type_map or {}).get(issue_type) or DEFAULT_TYPE_MAP.get(issue_type) or issue_type or "Task"


def _attachment_urls(issue: NormalizedIssue) -> List[str]:
    return [a.get("url", "") for a in issue.attachments if a.get("url")]


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value)


def build_dataframe(issues: List[NormalizedIssue], type_map: Dict[str, str]) -> pd.DataFrame:
    # Attachment URLs go in repeated "Attachment N" columns (Jira importer maps
    # each to Attachments), matching the existing jira_output layout.
    max_att = max((len(_attachment_urls(i)) for i in issues), default=0)
    att_cols = [f"Attachment {n}" for n in range(1, max_att + 1)]

    # Any non-core Jira fields mapped via a profile (Epic Name, Severity, …) become
    # extra columns, labelled from the canonical field catalog.
    extra_keys: List[str] = []
    for i in issues:
        for k in (i.extra or {}):
            if k not in extra_keys:
                extra_keys.append(k)
    extra_cols = [FIELD_LABEL.get(k, k) for k in extra_keys]

    rows = []
    for i in issues:
        row = {
            "Issue Id": i.row_id or i.external_id,
            "Parent Id": i.parent_row_id,
            "Issue Type": _resolve_type(i.issue_type, type_map),
            "Summary": i.summary,
            "Description": i.description,
            "Status": i.status,
            "Priority": i.priority,
            "Labels": " ".join(i.labels),
            "Components": ";".join(i.components),
            "Sprint": i.sprint,
            "Story Points": "" if i.story_points is None else i.story_points,
            "Assignee": i.assignee,
            "Reporter": i.reporter,
            "Fix Version/s": ";".join(i.fix_versions),
            "Team": i.team,
            "Start Date": i.start_date,
            "Due Date": i.due_date,
            "Issue Links": " ".join(i.links),
            "Rally ID": i.external_id,
        }
        for k, col in zip(extra_keys, extra_cols):
            row[col] = _fmt((i.extra or {}).get(k, ""))
        urls = _attachment_urls(i)
        for n, col in enumerate(att_cols):
            row[col] = urls[n] if n < len(urls) else ""
        rows.append(row)
    return pd.DataFrame(rows, columns=BASE_COLUMNS + extra_cols + att_cols)


def _write_csv(df: pd.DataFrame, out_dir: Path, base: str, max_rows: int,
               files: List[Dict[str, object]]) -> None:
    """Write ``<base>.csv``, or split into ``<base>_partNN.csv`` chunks (each with
    the full header) when the row count exceeds ``max_rows``."""
    n = int(len(df))
    if max_rows and max_rows > 0 and n > max_rows:
        parts = -(-n // max_rows)  # ceil division
        for p in range(parts):
            chunk = df.iloc[p * max_rows:(p + 1) * max_rows]
            fname = f"{base}_part{p + 1:02d}.csv"
            (out_dir / fname).write_text(chunk.to_csv(index=False), encoding="utf-8-sig")
            files.append({"name": fname, "rows": int(len(chunk))})
    else:
        fname = f"{base}.csv"
        (out_dir / fname).write_text(df.to_csv(index=False), encoding="utf-8-sig")
        files.append({"name": fname, "rows": n})


def write_export(issues: List[NormalizedIssue], type_map: Dict[str, str], out_dir: Path,
                 split_by_type: bool = True, max_rows: int = 0) -> List[Dict[str, object]]:
    """Write CSVs to out_dir; return [{name, rows}] for each file produced.

    When ``max_rows`` > 0, any file exceeding it is split into part files so
    each stays within the Jira CSV importer's per-file limit.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    df = build_dataframe(issues, type_map)
    files: List[Dict[str, object]] = []

    # The consolidated reference file is kept whole; only the per-type files that
    # are imported into Jira are split to stay within the importer's row limit.
    _write_csv(df, out_dir, "jira_all_issues", 0, files)

    if split_by_type and not df.empty:
        for issue_type, group in df.groupby("Issue Type"):
            token = str(issue_type).lower().replace(" ", "_").replace("-", "_") or "unknown"
            _write_csv(group, out_dir, f"jira_{token}", max_rows, files)
    return files
