"""Attachments: push Rally attachments onto already-created Jira issues.

Upload a CSV of Rally IDs, then run a background job that resolves each ID to a
Jira issue and transfers its Rally attachments across (idempotent).
"""
from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .. import attachment_jobs
from ..config import settings
from ..engine.attachments import extract_rally_ids
from ..engine.transform import load_dataframe
from ..schemas import AttachmentIdsResult, AttachmentJob, AttachmentRunRequest

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


@router.post("/upload-ids", response_model=AttachmentIdsResult)
async def upload_ids(file: UploadFile) -> AttachmentIdsResult:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv containing Rally IDs.")
    tmp = settings.upload_dir / f"attids_{uuid.uuid4().hex}.csv"
    tmp.write_bytes(await file.read())
    try:
        df = load_dataframe(tmp)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")
    finally:
        tmp.unlink(missing_ok=True)

    col, ids = extract_rally_ids(df)
    if not col:
        raise HTTPException(
            status_code=400,
            detail=f"No Rally ID column found. Expected one of 'Rally ID', 'Formatted ID', "
                   f"'ArtifactFormattedID'… (found: {list(df.columns)}).",
        )
    if not ids:
        raise HTTPException(status_code=400, detail=f"Column '{col}' has no Rally IDs.")
    return AttachmentIdsResult(filename=file.filename, row_count=int(len(df)),
                               id_column=col, rally_ids=ids)


@router.post("/run", response_model=AttachmentJob)
def run(req: AttachmentRunRequest) -> AttachmentJob:
    if not req.rally_ids:
        raise HTTPException(status_code=400, detail="No Rally IDs to process — upload a CSV first.")
    if not req.rally_id_field:
        raise HTTPException(status_code=400, detail="Set the Jira field that stores the Rally ID.")
    if not req.dry_run:
        if not (req.jira.base_url and req.jira.email and req.jira.api_token):
            raise HTTPException(status_code=400, detail="Jira base URL, email and API token are required.")
        if not req.rally.api_key:
            raise HTTPException(status_code=400, detail="A Rally API key is required to read attachments.")
    return attachment_jobs.start(req)


@router.get("/jobs/{job_id}", response_model=AttachmentJob)
def job_status(job_id: str) -> AttachmentJob:
    job = attachment_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Attachment job not found.")
    return job


@router.get("/jobs/{job_id}/report.csv")
def job_report(job_id: str) -> StreamingResponse:
    """Per-file result report for a run (rally_id, jira_key, file_name, source, status, detail)."""
    job = attachment_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Attachment job not found.")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["rally_id", "jira_key", "file_name", "source", "status", "detail"])
    for it in job.items:
        writer.writerow([it.rally_id, it.jira_key, it.file_name, it.source, it.status, it.detail])
    buf.seek(0)
    fname = f"attachment_report_{job_id[:8]}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
