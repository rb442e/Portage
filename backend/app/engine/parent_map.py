"""Parent Id VLOOKUP — resolve each work item's parent Rally reference to the
parent's Jira Issue id, using an uploaded parent.csv.

parent.csv is a Jira export mapping the Rally FormattedID to the Jira Issue id
(e.g. columns "Custom field (Rally ID)" and "Issue id"). Applied as the final
transformation before files are generated so ``Parent Id`` carries the real Jira
id the CSV importer needs. VLOOKUP semantics: first match wins on duplicates.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

import pandas as pd

from ..schemas import NormalizedIssue

# A Rally FormattedID token, e.g. F228109, US2209512, DE369021, E25855.
_FID_RE = re.compile(r"\b[A-Z]{1,3}\d+\b")
# Raw Rally columns that carry the parent reference, in priority order. The
# generic "Parent" column is authoritative (per the migration spec); the
# type-specific columns cover files that use them instead.
_RAW_PARENT_COLS = ("Parent", "Parent Feature", "Parent Epic", "Requirement", "WorkProduct")
# Mapped fields (in `extra`) that may also carry a parent reference — fallback.
_PARENT_EXTRA_KEYS = ("epic_id", "feature_id", "parent")

# Rally-ID key column candidates (case-insensitive).
KEY_COLS = [
    "Custom field (Rally ID)", "Rally ID", "Rally Id", "Formatted ID", "Formatted_ID",
    "ArtifactFormattedID", "FormattedID",
]
# Jira Issue-id value column candidates (case-insensitive).
VALUE_COLS = [
    "Issue id", "Issue Id", "Issue ID", "Parent Id", "Issue Key", "Issue key", "Key",
    "Jira ID", "Jira Id", "Jira Key",
]


def _first_col(df: pd.DataFrame, candidates: List[str]) -> str:
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return ""


def parse_parent_map(df: pd.DataFrame) -> Tuple[str, str, Dict[str, str]]:
    """Return (key_column, value_column, {rally_id: jira_issue_id}). First wins."""
    kcol = _first_col(df, KEY_COLS)
    vcol = _first_col(df, VALUE_COLS)
    if not kcol or not vcol:
        return kcol, vcol, {}
    out: Dict[str, str] = {}
    for _, r in df.iterrows():
        k = str(r.get(kcol, "")).strip()
        v = str(r.get(vcol, "")).strip()
        if k and v and k.lower() != "nan" and v.lower() != "nan":
            out.setdefault(k, v)   # VLOOKUP: first match wins on duplicate Rally IDs
    return kcol, vcol, out


def _resolve_key(candidate: str, pmap: Dict[str, str]) -> str:
    """Return the matching parent-map key for a reference, direct or by FormattedID."""
    c = (str(candidate) or "").strip()
    if not c:
        return ""
    if c in pmap:
        return c
    m = _FID_RE.search(c)          # e.g. "Epic E25855: ..." -> "E25855"
    if m and m.group(0) in pmap:
        return m.group(0)
    return ""


def _parent_candidates(issue: NormalizedIssue) -> List[str]:
    """All places a parent Rally reference may live, most-authoritative first.

    Step 1 of the spec: the raw Rally "Parent" column. Mapped fields and the
    hierarchy id are kept as fallbacks so converted exports still resolve.
    """
    raw = issue.raw or {}
    cands: List[str] = [str(raw.get(c, "")) for c in _RAW_PARENT_COLS]
    cands += [issue.parent_row_id or "", issue.parent_external_id or ""]
    extra = issue.extra or {}
    cands += [str(extra.get(k, "")) for k in _PARENT_EXTRA_KEYS]
    return cands


def apply_parent_map(issues: List[NormalizedIssue], pmap: Dict[str, str]) -> int:
    """Resolve each issue's parent Rally reference to its Jira Issue id in place.

    For each work item: extract the E#/F#/US# FormattedID from the raw "Parent"
    column (falling back to other parent references), VLOOKUP it in the parent
    map, and write the matched Jira Issue id onto ``parent_row_id`` (which the
    exporter emits as "Parent Id"). Returns the number resolved.
    """
    if not pmap:
        return 0
    resolved = 0
    for issue in issues:
        key = ""
        for c in _parent_candidates(issue):
            key = _resolve_key(c, pmap)
            if key:
                break
        if key:
            issue.parent_row_id = pmap[key]
            issue.parent_external_id = pmap[key]
            resolved += 1
    return resolved
