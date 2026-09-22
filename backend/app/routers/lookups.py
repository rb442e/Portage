"""Jira Catalog — reusable value mappings (sprint / version / user / team).

Each catalog is one named source-value -> target-value table for a kind. Load it
from an existing CSV by picking the source (Rally) and target (Jira) columns, edit
it inline, and save. At migration time the catalogs translate Rally values to
their Jira equivalents (sprint/version names or IDs, user emails, team IDs).
"""
from __future__ import annotations

import io
from typing import Dict, List, Optional, Tuple

import pandas as pd
from fastapi import APIRouter, Form, HTTPException, UploadFile

from .. import store
from ..schemas import LOOKUP_KINDS, LookupCsvPreview, LookupTable

router = APIRouter(prefix="/api/lookups", tags=["lookups"])

# Best-guess source (Rally) and target (Jira) columns per kind, matching the
# column names the repo's existing mapping CSVs use.
_SUGGESTED: Dict[str, Tuple[List[str], List[str]]] = {
    "sprint": (["Rally Iteration", "Iteration Name", "Iteration", "Rally Sprint", "Sprint Name", "Name"],
               ["Sprint ID", "Sprint Id", "Jira Sprint", "Sprint Name", "Id", "Name"]),
    "version": (["Milestone ID", "Milestone", "Rally Release", "Release", "Version Name", "Name"],
                ["Version ID", "Version Id", "Jira Version", "Version Name", "Id", "Name"]),
    "user": (["Rally Name", "Full Name", "Rally User", "Name"],
             ["Email", "Account Id", "accountId", "Jira User", "Id"]),
    "team": (["Rally Team", "Team", "Team Name", "Name"],
             ["Atlassian Team ID", "Team ID", "Jira Team", "Team Name", "Id", "Name"]),
}


def _read_csv(data: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(data), encoding="utf-8-sig", dtype=str, keep_default_na=False)


def _first_match(columns: List[str], candidates: List[str]) -> str:
    lower = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return ""


def _entries_from(df: pd.DataFrame, source_col: str, target_col: str) -> Dict[str, str]:
    if source_col not in df.columns or target_col not in df.columns:
        raise HTTPException(status_code=400, detail="source/target column not found in CSV")
    entries: Dict[str, str] = {}
    for _, r in df.iterrows():
        src = str(r[source_col]).strip()
        tgt = str(r[target_col]).strip()
        if src and tgt:
            entries.setdefault(src, tgt)  # first occurrence wins
    return entries


@router.get("/kinds", response_model=List[str])
def kinds() -> List[str]:
    return list(LOOKUP_KINDS)


@router.get("", response_model=List[LookupTable])
def list_lookups(kind: Optional[str] = None, side: Optional[str] = None) -> List[LookupTable]:
    return [LookupTable(**lk) for lk in store.list_lookups(kind, side)]


@router.get("/{lookup_id}", response_model=LookupTable)
def get_lookup(lookup_id: int) -> LookupTable:
    lk = store.get_lookup(lookup_id)
    if not lk:
        raise HTTPException(status_code=404, detail="Lookup not found")
    return LookupTable(**lk)


@router.post("", response_model=LookupTable)
def save_lookup(lookup: LookupTable) -> LookupTable:
    if lookup.kind not in LOOKUP_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {LOOKUP_KINDS}")
    return LookupTable(**store.save_lookup(lookup.model_dump()))


@router.delete("/{lookup_id}")
def delete_lookup(lookup_id: int) -> dict:
    store.delete_lookup(lookup_id)
    return {"deleted": lookup_id}


@router.post("/parse", response_model=LookupCsvPreview)
async def parse_csv(file: UploadFile, kind: str = Form("")) -> LookupCsvPreview:
    """Inspect an uploaded CSV: return its columns + a suggested source/target pair."""
    try:
        df = _read_csv(await file.read())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")
    cols = list(df.columns)
    src_cands, tgt_cands = _SUGGESTED.get(kind, ([], []))
    return LookupCsvPreview(
        columns=cols,
        sample=df.head(8).to_dict(orient="records"),
        suggested_source=_first_match(cols, src_cands),
        suggested_target=_first_match(cols, tgt_cands),
    )


@router.post("/extract")
async def extract_csv(
    file: UploadFile,
    source_col: str = Form(...),
    target_col: str = Form(...),
) -> Dict[str, Dict[str, str]]:
    """Return all source -> target entries from a CSV without persisting them.

    Feeds the catalog editor so the user can review/edit before saving.
    """
    try:
        df = _read_csv(await file.read())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")
    return {"entries": _entries_from(df, source_col, target_col)}
