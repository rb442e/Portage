"""Attachments engine — helpers for the post-migration attachment step.

Reads the Rally work-item IDs from an uploaded CSV so they can be resolved to
Jira issues and have their Rally attachments pushed across. Mirrors the column
conventions used by the repo's add_attachments.py.
"""
from __future__ import annotations

import re
from typing import List, Tuple

import pandas as pd

# Column names (case-insensitive) that may hold a Rally FormattedID.
RALLY_ID_COLS = [
    "Rally ID", "Custom field (Rally ID)", "Feature ID", "Story ID", "Defect ID",
    "US ID", "DE ID", "ArtifactFormattedID", "FormattedID", "Formatted ID", "Formatted_ID",
]


def _first_col(df: pd.DataFrame, candidates: List[str]) -> str:
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return ""


def _dedupe_name(name: str, seen: dict) -> str:
    """Disambiguate duplicate file names within one work item ('name (2).ext')."""
    base = name or "attachment"
    if base not in seen:
        seen[base] = 1
        return base
    seen[base] += 1
    stem, dot, ext = base.rpartition(".")
    return f"{stem} ({seen[base]}).{ext}" if dot else f"{base} ({seen[base]})"


def extract_rally_ids(df: pd.DataFrame) -> Tuple[str, List[str]]:
    """Return (id_column, distinct Rally IDs in order) from a Rally-ID CSV.

    A single cell may hold several IDs separated by spaces, commas, semicolons or
    newlines (e.g. a pasted list); each is split out into its own Rally ID so it
    is looked up individually instead of as one giant, unmatchable string.
    """
    col = _first_col(df, RALLY_ID_COLS)
    if not col:
        return "", []
    ids: List[str] = []
    seen: set = set()
    for raw in df[col].astype(str):
        cell = raw.strip()
        if not cell or cell.lower() == "nan":
            continue
        for token in re.split(r"[\s,;]+", cell):
            rid = token.strip()
            if not rid or rid.lower() == "nan" or rid in seen:
                continue
            seen.add(rid)
            ids.append(rid)
    return col, ids
