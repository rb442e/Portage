"""In-memory job registry with a background worker thread.

Single-tenant, self-hosted MVP: jobs live in memory while running and are
persisted to SQLite on completion (see store.upsert_job). For horizontal scale,
swap this for Celery/RQ + Redis without touching the routers.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import store
from .engine.migrator import Migrator
from .schemas import JobStatus, MigrationRequest, NormalizedIssue

_JOBS: Dict[str, JobStatus] = {}
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_job(dry_run: bool, total: int, migration_id: str = "") -> JobStatus:
    job = JobStatus(job_id=uuid.uuid4().hex, state="queued", dry_run=dry_run,
                    total=total, started_at=_now(), migration_id=migration_id)
    with _LOCK:
        _JOBS[job.job_id] = job
    return job


def get_job(job_id: str) -> Optional[JobStatus]:
    with _LOCK:
        job = _JOBS.get(job_id)
    if job:
        return job
    data = store.get_job(job_id)
    return JobStatus(**data) if data else None


def list_jobs(limit: int = 50) -> List[dict]:
    return store.list_jobs(limit)


def _log(job: JobStatus, message: str) -> None:
    job.log.append(f"{datetime.now().strftime('%H:%M:%S')}  {message}")
    if len(job.log) > 500:
        job.log = job.log[-500:]


def run_migration_job(job: JobStatus, req: MigrationRequest, issues: List[NormalizedIssue]) -> None:
    """Execute a migration on a worker thread, updating `job` in place."""
    job.state = "running"
    migrator = Migrator(req.jira, req.rally, req.type_map, req.include_attachments)
    _log(job, f"Starting migration of {len(issues)} issue(s) to {req.jira.project_key}")

    def progress(event: str, payload: dict) -> None:
        if event == "progress":
            job.progress = round(100.0 * payload["done"] / max(payload["total"], 1), 1)
            return
        item = payload
        if event == "created":
            job.created += 1
            job.attachments_uploaded += item.get("attachments_uploaded", 0)
            _log(job, f"Created {item['jira_key']} <- {item['external_id'] or 'row'}")
        elif event == "failed":
            job.failed += 1
            _log(job, f"FAILED {item['external_id'] or 'row'}: {item.get('message', '')[:180]}")
        job.items.append(_to_item(item))

    try:
        migrator.run(issues, progress)
        job.state = "done"
        _log(job, f"Done. created={job.created} failed={job.failed} "
                  f"attachments={job.attachments_uploaded}")
    except Exception as e:  # noqa: BLE001
        job.state = "failed"
        _log(job, f"Job crashed: {e}")
    finally:
        job.finished_at = _now()
        job.progress = 100.0
        store.upsert_job(job.job_id, job.state, job.model_dump())


def _to_item(item: dict):
    from .schemas import JobItemResult

    return JobItemResult(
        external_id=item.get("external_id", ""),
        jira_key=item.get("jira_key", ""),
        status=item.get("status", "pending"),
        message=item.get("message", ""),
        attachments_uploaded=item.get("attachments_uploaded", 0),
    )


def start_background(req: MigrationRequest, issues: List[NormalizedIssue]) -> JobStatus:
    job = create_job(dry_run=False, total=len(issues), migration_id=req.migration_id or "")
    t = threading.Thread(target=run_migration_job, args=(job, req, issues), daemon=True)
    t.start()
    return job
