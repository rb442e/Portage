"""In-memory background runner for bulk 'copy Rally description -> Jira'.

For each Rally ID: resolve the Jira issue via the Rally-ID field, read the Rally
Description HTML, count its tables, and (unless dry-run) write it back as ADF
(Cloud) or wiki markup (Server/DC) so tables keep their grid format. A dry run
performs the same read + table count but no write — i.e. a table-detection
report over the whole batch. Progress is polled by the UI while running.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from .connectors.jira_client import JiraClient
from .connectors.rally_client import RallyClient
from .engine.richtext import count_tables
from .schemas import CopyDescBulkRequest, CopyDescItemResult, CopyDescJob

_JOBS: Dict[str, CopyDescJob] = {}
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(job_id: str) -> Optional[CopyDescJob]:
    with _LOCK:
        return _JOBS.get(job_id)


def _log(job: CopyDescJob, msg: str) -> None:
    job.log.append(f"{datetime.now().strftime('%H:%M:%S')}  {msg}")
    if len(job.log) > 500:
        job.log = job.log[-500:]


def _run(job: CopyDescJob, req: CopyDescBulkRequest) -> None:
    job.state = "running"
    jira = JiraClient(req.jira)
    rally = RallyClient(req.rally)
    total = len(req.rally_ids)
    _log(job, f"Starting description copy for {total} item(s)"
              + (" (dry run — detect tables only)" if req.dry_run else ""))

    key_cache: Dict[str, Optional[str]] = {}
    try:
        for idx, rid in enumerate(req.rally_ids, start=1):
            job.processed_ids = idx
            job.progress = round(100.0 * idx / max(total, 1), 1)

            # Identify the Jira issue: prefer a supplied post-import map, else
            # resolve by JQL on the stamped Rally-ID field.
            mapped = req.id_map.get(rid) if req.id_map else None
            if mapped:
                key = mapped
            else:
                key = key_cache.get(rid) if rid in key_cache else jira.find_key_by_rally_id(req.rally_id_field, rid)
                key_cache[rid] = key
            if not key:
                job.unresolved += 1
                job.items.append(CopyDescItemResult(rally_id=rid, status="unresolved",
                                                    detail="no matching Jira issue for this Rally ID"))
                _log(job, f"SKIP {rid}: no Jira issue found")
                continue
            job.resolved += 1

            try:
                html = rally.fetch_description(rid)
            except Exception as e:  # noqa: BLE001
                job.errors += 1
                job.items.append(CopyDescItemResult(rally_id=rid, jira_key=key, status="error",
                                                    detail=f"rally read: {e}"))
                _log(job, f"ERROR {rid}: rally read failed: {e}")
                continue

            tables = count_tables(html)
            if tables:
                job.with_tables += 1

            if not html.strip():
                job.empty += 1
                job.items.append(CopyDescItemResult(rally_id=rid, jira_key=key, tables_found=0,
                                                    status="empty", detail="Rally description is empty"))
                continue

            if req.dry_run:
                job.items.append(CopyDescItemResult(rally_id=rid, jira_key=key, tables_found=tables,
                                                    status="dry-run",
                                                    detail=f"{tables} table(s); would copy" if tables else "would copy"))
                continue

            if req.tables_only and tables == 0:
                job.skipped += 1
                job.items.append(CopyDescItemResult(rally_id=rid, jira_key=key, tables_found=0,
                                                    status="skipped", detail="no table (tables-only mode)"))
                continue

            ok, err = jira.set_description(key, jira.description_from_html(html))
            if ok:
                job.applied += 1
                job.items.append(CopyDescItemResult(rally_id=rid, jira_key=key, tables_found=tables,
                                                    status="applied",
                                                    detail=f"{tables} table(s) copied" if tables else "copied"))
                _log(job, f"OK {rid} -> {key}" + (f" ({tables} table)" if tables else ""))
            else:
                job.errors += 1
                job.items.append(CopyDescItemResult(rally_id=rid, jira_key=key, tables_found=tables,
                                                    status="error", detail=f"jira update: {err}"))
                _log(job, f"ERROR {key}: {err}")

        job.state = "done"
        _log(job, f"Done. resolved={job.resolved} with_tables={job.with_tables} "
                  f"applied={job.applied} skipped={job.skipped} empty={job.empty} errors={job.errors}")
    except Exception as e:  # noqa: BLE001
        job.state = "failed"
        _log(job, f"Job crashed: {e}")
    finally:
        job.progress = 100.0
        job.finished_at = _now()


def start(req: CopyDescBulkRequest) -> CopyDescJob:
    job = CopyDescJob(job_id=uuid.uuid4().hex, state="queued", dry_run=req.dry_run,
                      tables_only=req.tables_only, total_ids=len(req.rally_ids), started_at=_now())
    with _LOCK:
        _JOBS[job.job_id] = job
    threading.Thread(target=_run, args=(job, req), daemon=True).start()
    return job
