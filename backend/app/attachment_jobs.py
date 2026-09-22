"""In-memory background runner for the attachment-migration step.

For each Rally ID: resolve the target Jira issue (JQL on the Rally-ID field),
discover the work item's attachments in Rally, download each and upload it to
Jira with an idempotency check. Progress is polled by the UI while running.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from .connectors.jira_client import JiraClient
from .connectors.rally_client import RallyClient
from .engine.attachments import _dedupe_name
from .schemas import AttachmentItemResult, AttachmentJob, AttachmentRunRequest

_JOBS: Dict[str, AttachmentJob] = {}
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(job_id: str) -> Optional[AttachmentJob]:
    with _LOCK:
        return _JOBS.get(job_id)


def _log(job: AttachmentJob, msg: str) -> None:
    job.log.append(f"{datetime.now().strftime('%H:%M:%S')}  {msg}")
    if len(job.log) > 500:
        job.log = job.log[-500:]


def _run(job: AttachmentJob, req: AttachmentRunRequest) -> None:
    job.state = "running"
    jira = JiraClient(req.jira)
    rally = RallyClient(req.rally) if req.rally.api_key else None
    total = len(req.rally_ids)
    _log(job, f"Starting attachment migration for {total} Rally work item(s)"
              + (" (dry run)" if req.dry_run else ""))

    key_cache: Dict[str, Optional[str]] = {}
    existing_cache: Dict[str, set] = {}

    try:
        for idx, rid in enumerate(req.rally_ids, start=1):
            job.processed_ids = idx
            job.progress = round(100.0 * idx / max(total, 1), 1)

            key = key_cache.get(rid) if rid in key_cache else jira.find_key_by_rally_id(req.rally_id_field, rid)
            key_cache[rid] = key
            if key:
                job.resolved += 1
            else:
                job.unresolved += 1
                job.skipped += 1
                job.items.append(AttachmentItemResult(rally_id=rid, status="skipped",
                                                       detail="no matching Jira issue for this Rally ID"))
                _log(job, f"SKIP {rid}: no Jira issue found")
                continue

            if rally is None:
                job.items.append(AttachmentItemResult(rally_id=rid, jira_key=key, status="skipped",
                                                       detail="Rally API key required to read attachments"))
                continue

            try:
                atts = rally.discover_attachments(rid)
            except Exception as e:  # noqa: BLE001
                job.errors += 1
                job.items.append(AttachmentItemResult(rally_id=rid, jira_key=key, status="error",
                                                       detail=f"rally lookup: {e}"))
                _log(job, f"ERROR {rid}: rally lookup failed: {e}")
                continue

            if not atts:
                job.items.append(AttachmentItemResult(rally_id=rid, jira_key=key, status="no attachments",
                                                       detail="no attachments found in Rally"))
                _log(job, f"{rid} -> {key}: no attachments")
                continue

            existing = existing_cache.get(key)
            if existing is None and not req.dry_run:
                existing = jira.existing_attachment_names(key)
                existing_cache[key] = existing
            existing = existing or set()

            seen: Dict[str, int] = {}
            for a in atts:
                ref = a.get("content_ref") or ""
                name = _dedupe_name(a.get("name", ""), seen)
                if not ref:
                    continue
                source = f"rally://{rid}/{name}"

                if req.dry_run:
                    job.items.append(AttachmentItemResult(rally_id=rid, jira_key=key, file_name=name, source=source,
                                                          status="dry-run", detail="would upload"))
                    continue

                if name in existing:
                    job.exists += 1
                    job.items.append(AttachmentItemResult(rally_id=rid, jira_key=key, file_name=name, source=source,
                                                          status="exists", detail="already attached"))
                    continue

                try:
                    content = rally.download(ref)
                except Exception as e:  # noqa: BLE001
                    job.errors += 1
                    job.items.append(AttachmentItemResult(rally_id=rid, jira_key=key, file_name=name, source=source,
                                                          status="error", detail=f"fetch: {e}"))
                    _log(job, f"ERROR {rid}/{name}: download failed: {e}")
                    continue

                err = jira.upload_attachment(key, name, content)
                if err:
                    job.errors += 1
                    job.items.append(AttachmentItemResult(rally_id=rid, jira_key=key, file_name=name, source=source,
                                                          status="error", detail=f"upload: {err}"))
                    _log(job, f"ERROR {key}/{name}: {err}")
                else:
                    existing.add(name)
                    job.uploaded += 1
                    job.items.append(AttachmentItemResult(rally_id=rid, jira_key=key, file_name=name, source=source,
                                                          status="uploaded"))
                    _log(job, f"OK {key}: {name}")

        job.state = "done"
        _log(job, f"Done. resolved={job.resolved} uploaded={job.uploaded} "
                  f"exists={job.exists} skipped={job.skipped} errors={job.errors}")
    except Exception as e:  # noqa: BLE001
        job.state = "failed"
        _log(job, f"Job crashed: {e}")
    finally:
        job.progress = 100.0
        job.finished_at = _now()


def start(req: AttachmentRunRequest) -> AttachmentJob:
    job = AttachmentJob(job_id=uuid.uuid4().hex, state="queued", dry_run=req.dry_run,
                        total_ids=len(req.rally_ids), started_at=_now())
    with _LOCK:
        _JOBS[job.job_id] = job
    threading.Thread(target=_run, args=(job, req), daemon=True).start()
    return job
