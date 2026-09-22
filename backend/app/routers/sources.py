"""Source upload + preview. Files are stored under the data dir keyed by id."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile

from ..config import settings
from ..engine.transform import (detect_artifact_type, detect_kind,
                                load_dataframe, validate_rally_file)
from ..schemas import BatchUploadItem, BatchUploadResult, SourcePreview

router = APIRouter(prefix="/api/sources", tags=["sources"])


async def _store_csv(file: UploadFile) -> Path:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail=f"{file.filename or 'file'}: please upload a .csv export.")
    source_id = uuid.uuid4().hex
    dest = settings.upload_dir / f"{source_id}.csv"
    dest.write_bytes(await file.read())
    return dest


@router.post("/upload", response_model=SourcePreview)
async def upload_source(file: UploadFile) -> SourcePreview:
    dest = await _store_csv(file)
    try:
        df = load_dataframe(dest)
    except Exception as e:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")

    sample = df.head(10).fillna("").to_dict(orient="records")
    return SourcePreview(
        source_id=dest.stem,
        filename=file.filename or "upload.csv",
        kind=detect_kind(df),
        row_count=int(len(df)),
        columns=list(df.columns),
        sample=sample,
    )


@router.post("/upload-batch", response_model=BatchUploadResult)
async def upload_batch(files: List[UploadFile]) -> BatchUploadResult:
    """Upload several per-artifact Rally exports; validate and detect each type."""
    items: List[BatchUploadItem] = []
    for file in files:
        dest = await _store_csv(file)
        try:
            df = load_dataframe(dest)
        except Exception as e:  # noqa: BLE001
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=f"{file.filename}: could not parse CSV: {e}")
        atype = detect_artifact_type(file.filename or "")
        items.append(BatchUploadItem(
            source_id=dest.stem,
            filename=file.filename or "upload.csv",
            artifact_type=atype,
            row_count=int(len(df)),
            columns=list(df.columns),
            warnings=validate_rally_file(df, atype),
        ))
    return BatchUploadResult(items=items)
