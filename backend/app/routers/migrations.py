"""Migration preview (dry run) + live run + status + import-file export."""
from __future__ import annotations

import datetime
import io
import re
import uuid
import zipfile
from collections import Counter
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from .. import jobs, store
from ..config import settings
from ..engine.default_mappings import build_default_template
from ..engine.exporter import write_export
from ..engine.mapping import DEFAULT_JIRA_ALL_TEMPLATE, merge_lookups
from ..engine.migrator import Migrator
from ..engine.parent_map import apply_parent_map, parse_parent_map
from ..engine.transform import (detect_artifact_type, detect_kind,
                                load_dataframe, transform_batch,
                                transform_source)
from ..engine.validate import validate_mappings
from ..schemas import (BatchMigrationRequest, ExportFile, ExportPreview,
                       ExportRecord, ExportResult, JiraConnection, JobStatus,
                       MappingIssue, MappingValidation, MigrationRequest,
                       NormalizedIssue, ParentMapResult, PreviewResult)

router = APIRouter(prefix="/api/migrations", tags=["migrations"])

_EXPORT_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _load_parent_map(parent_map_id: str) -> dict:
    """Load the uploaded parent.csv (Rally ID -> Jira Issue id) by id."""
    if not parent_map_id or not _EXPORT_ID_RE.match(parent_map_id):
        return {}
    path = settings.upload_dir / f"parentmap_{parent_map_id}.csv"
    if not path.exists():
        return {}
    _, _, pmap = parse_parent_map(load_dataframe(path))
    return pmap



def _load_issues(req: MigrationRequest, with_lookups: bool = True) -> List[NormalizedIssue]:
    src = settings.upload_dir / f"{req.source_id}.csv"
    if not src.exists():
        raise HTTPException(status_code=404, detail="Source not found; upload it again.")
    template = None
    # An inline mapping (built in the Migrate wizard) takes precedence, then a
    # saved template, then the built-in template for converted exports.
    if req.mapping is not None and req.mapping.field_maps:
        template = req.mapping.model_dump()
    elif req.mapping_id:
        template = store.get_mapping(req.mapping_id)
        if not template:
            raise HTTPException(status_code=404, detail="Mapping template not found.")
    if template is None:
        df = load_dataframe(src)
        if detect_kind(df) == "jira_all_issues":
            template = dict(DEFAULT_JIRA_ALL_TEMPLATE)
        else:
            # No template chosen + raw Rally export -> the rally_to_jira default.
            repo_root = Path(__file__).resolve().parents[3]
            template = build_default_template(repo_root / "config.yaml")
    if with_lookups and template is not None and req.lookup_ids:
        template = merge_lookups(template, store.get_lookups(req.lookup_ids))
    try:
        return transform_source(src, template, force_type=req.force_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/validate", response_model=MappingValidation)
def validate_single(req: MigrationRequest) -> MappingValidation:
    return _validation(_load_issues(req, with_lookups=False), req.lookup_ids)


@router.post("/preview", response_model=PreviewResult)
def preview(req: MigrationRequest) -> PreviewResult:
    issues = _load_issues(req)
    parents_total = sum(1 for i in issues if i.parent_row_id)
    parents_resolved = 0
    if req.parent_map_id:
        parents_resolved = apply_parent_map(issues, _load_parent_map(req.parent_map_id))
    migrator = Migrator(req.jira, req.rally, req.type_map, req.include_attachments)
    planned = migrator.preview(issues)
    by_type = Counter(p.jira_issue_type for p in planned)
    warnings: List[str] = []
    if not req.jira.project_key:
        warnings.append("No Jira project key set on the target connection.")
    if not any(i.row_id for i in issues) and any(i.parent_row_id for i in issues):
        warnings.append("Parent links present but no row ids — hierarchy may not resolve.")
    if req.parent_map_id and parents_total and not parents_resolved:
        warnings.append("Parent map uploaded but no parent references matched — check the Rally IDs.")
    return PreviewResult(
        source_id=req.source_id,
        total=len(planned),
        by_type=dict(by_type),
        planned=planned,
        warnings=warnings,
        parents_resolved=parents_resolved,
        parents_total=parents_total,
    )


@router.post("/run", response_model=JobStatus)
def run(req: MigrationRequest) -> JobStatus:
    if not req.jira.base_url or not req.jira.api_token:
        raise HTTPException(status_code=400, detail="Jira base URL and API token are required.")
    if not req.jira.project_key:
        raise HTTPException(status_code=400, detail="Jira project key is required.")
    issues = _load_issues(req)
    if not issues:
        raise HTTPException(status_code=400, detail="No issues found in the source.")
    return jobs.start_background(req, issues)


# ---------------------------------------------------------------------------
# Import-file export (Jira CSV importer) — an alternative to live API creation.
# Needs no Jira credentials; the mapping + lookups are still applied.
# ---------------------------------------------------------------------------
def _export_dir(export_id: str) -> Path:
    if not _EXPORT_ID_RE.match(export_id):
        raise HTTPException(status_code=404, detail="Export not found.")
    return settings.data_dir / "exports" / export_id


def _record_export(export_id: str, total: int, files: List[dict], kind: str, label: str, migration_id: str = "") -> None:
    store.save_export(export_id, {
        "total": total,
        "kind": kind,
        "label": label,
        "migration_id": migration_id,
        "files": [{"name": f["name"], "rows": int(f["rows"])} for f in files],
    })


def _scan_export_dir(export_id: str) -> dict:
    """Synthesize metadata for an export folder that predates the exports table."""
    d = _export_dir(export_id)
    files = []
    for p in sorted(d.glob("*.csv")):
        try:
            with p.open("r", encoding="utf-8-sig") as fh:
                rows = max(0, sum(1 for _ in fh) - 1)
        except OSError:
            rows = 0
        files.append({"name": p.name, "rows": rows})
    total = next((f["rows"] for f in files if f["name"] == "jira_all_issues.csv"),
                 sum(f["rows"] for f in files))
    created = datetime.datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return {"total": total, "kind": "", "label": "", "files": files, "created_at": created}


@router.post("/parent-map", response_model=ParentMapResult)
async def upload_parent_map(file: UploadFile) -> ParentMapResult:
    """Upload a parent.csv (Rally ID -> Jira Issue id) for the Parent Id VLOOKUP."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv parent map.")
    pid = uuid.uuid4().hex
    dest = settings.upload_dir / f"parentmap_{pid}.csv"
    dest.write_bytes(await file.read())
    try:
        df = load_dataframe(dest)
    except Exception as e:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")
    kcol, vcol, pmap = parse_parent_map(df)
    if not kcol or not vcol:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"parent.csv needs a Rally-ID column (e.g. 'Custom field (Rally ID)') and an "
                   f"Issue-id column (e.g. 'Issue id'). Found: {list(df.columns)}.",
        )
    sample = [{"rally_id": k, "issue_id": v} for k, v in list(pmap.items())[:8]]
    return ParentMapResult(parent_map_id=pid, filename=file.filename, row_count=int(len(df)),
                           key_column=kcol, value_column=vcol, count=len(pmap), sample=sample)


@router.post("/export", response_model=ExportResult)
def export(req: MigrationRequest) -> ExportResult:
    issues = _load_issues(req)
    if not issues:
        raise HTTPException(status_code=400, detail="No issues found in the source.")
    if req.parent_map_id:
        apply_parent_map(issues, _load_parent_map(req.parent_map_id))
    export_id = uuid.uuid4().hex
    files = write_export(issues, req.type_map, _export_dir(export_id), max_rows=req.split_rows or 0)
    _record_export(export_id, len(issues), files, kind="single", label="Single export file",
                   migration_id=req.migration_id or "")
    return ExportResult(export_id=export_id, total=len(issues), migration_id=req.migration_id or "",
                        files=[ExportFile(**f) for f in files])


# ---------------------------------------------------------------------------
# Batch path: several per-artifact Rally files -> mapped + looked-up issues,
# hierarchy resolved across files, then Jira import files.
# ---------------------------------------------------------------------------
def _batch_template(req: BatchMigrationRequest) -> dict:
    if req.mapping is not None and (req.mapping.field_maps or req.mapping.profiles):
        return req.mapping.model_dump()
    if req.mapping_id:
        tpl = store.get_mapping(req.mapping_id)
        if not tpl:
            raise HTTPException(status_code=404, detail="Mapping template not found.")
        return tpl
    # Default per-artifact mapping derived from rally_to_jira.py.
    repo_root = Path(__file__).resolve().parents[3]
    return build_default_template(repo_root / "config.yaml")


def _load_batch_issues(req: BatchMigrationRequest, with_lookups: bool = True) -> List[NormalizedIssue]:
    if not req.files:
        raise HTTPException(status_code=400, detail="No files provided.")
    template = _batch_template(req)
    files = []
    for item in req.files:
        src = settings.upload_dir / f"{item.source_id}.csv"
        if not src.exists():
            raise HTTPException(status_code=404, detail=f"Source {item.source_id} not found; re-upload.")
        atype = item.artifact_type or detect_artifact_type(src.name)
        files.append((atype, src))
    lookups = store.get_lookups(req.lookup_ids) if (with_lookups and req.lookup_ids) else None
    try:
        return transform_batch(files, template, lookups)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _validation(issues, lookup_ids) -> MappingValidation:
    lookups = store.get_lookups(lookup_ids) if lookup_ids else []
    found = validate_mappings(issues, lookups)
    return MappingValidation(
        ok=not found,
        total_missing=sum(i["missing_count"] for i in found),
        issues=[MappingIssue(**i) for i in found],
    )


@router.post("/validate-batch", response_model=MappingValidation)
def validate_batch(req: BatchMigrationRequest) -> MappingValidation:
    return _validation(_load_batch_issues(req, with_lookups=False), req.lookup_ids)


@router.post("/preview-batch", response_model=PreviewResult)
def preview_batch(req: BatchMigrationRequest) -> PreviewResult:
    issues = _load_batch_issues(req)
    parents_total = sum(1 for i in issues if i.parent_row_id)
    parents_resolved = 0
    if req.parent_map_id:
        parents_resolved = apply_parent_map(issues, _load_parent_map(req.parent_map_id))
    jira = req.jira or JiraConnection(base_url="")
    migrator = Migrator(jira, None, req.type_map, req.include_attachments)
    planned = migrator.preview(issues)
    by_type = Counter(p.jira_issue_type for p in planned)
    warnings: List[str] = []
    if not any(i.row_id for i in issues) and any(i.parent_row_id for i in issues):
        warnings.append("Parent links present but no row ids — hierarchy may not resolve.")
    return PreviewResult(source_id="batch", total=len(planned),
                         by_type=dict(by_type), planned=planned, warnings=warnings,
                         parents_resolved=parents_resolved, parents_total=parents_total)


@router.post("/export-batch", response_model=ExportResult)
def export_batch(req: BatchMigrationRequest) -> ExportResult:
    issues = _load_batch_issues(req)
    if not issues:
        raise HTTPException(status_code=400, detail="No issues found in the uploaded files.")
    if req.parent_map_id:
        apply_parent_map(issues, _load_parent_map(req.parent_map_id))
    export_id = uuid.uuid4().hex
    files = write_export(issues, req.type_map, _export_dir(export_id), max_rows=req.split_rows or 0)
    types = ", ".join(dict.fromkeys(i.artifact_type for i in req.files if i.artifact_type))
    label = f"{len(req.files)} files" + (f" ({types})" if types else "")
    _record_export(export_id, len(issues), files, kind="batch", label=label,
                   migration_id=req.migration_id or "")
    return ExportResult(export_id=export_id, total=len(issues), migration_id=req.migration_id or "",
                        files=[ExportFile(**f) for f in files])


@router.get("/exports", response_model=List[ExportRecord])
def list_exports() -> List[ExportRecord]:
    """Every saved import-file set, newest first (back-fills pre-existing folders)."""
    known = {r["export_id"]: r for r in store.list_exports()}
    root = settings.data_dir / "exports"
    if root.exists():
        for d in sorted(root.iterdir()):
            if d.is_dir() and _EXPORT_ID_RE.match(d.name) and d.name not in known:
                meta = _scan_export_dir(d.name)
                store.save_export(d.name, meta)
                known[d.name] = {**meta, "export_id": d.name}
    records = sorted(known.values(), key=lambda r: r.get("created_at", ""), reverse=True)
    return [ExportRecord(export_id=r["export_id"], created_at=r.get("created_at", ""),
                         total=r.get("total", 0), kind=r.get("kind", ""),
                         label=r.get("label", ""), migration_id=r.get("migration_id", ""),
                         files=r.get("files", []))
            for r in records]


@router.get("/exports/{export_id}.zip")
def download_zip(export_id: str) -> StreamingResponse:
    out_dir = _export_dir(export_id)
    if not out_dir.exists():
        raise HTTPException(status_code=404, detail="Export not found.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(out_dir.glob("*.csv")):
            zf.write(p, arcname=p.name)
    buf.seek(0)
    fname = f"portage_jira_import_{export_id[:8]}.zip"
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/exports/{export_id}/preview", response_model=ExportPreview)
def preview_export(export_id: str, file: str, limit: int = 200) -> ExportPreview:
    """Return a file's columns + first `limit` rows for in-tool viewing."""
    safe = Path(file).name
    fp = _export_dir(export_id) / safe
    if not fp.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    df = load_dataframe(fp)
    total = int(len(df))
    rows = df.head(max(1, limit)).to_dict(orient="records")
    return ExportPreview(file=safe, columns=list(df.columns), rows=rows,
                         total_rows=total, truncated=total > limit)


@router.get("/exports/{export_id}/{filename}")
def download_file(export_id: str, filename: str) -> FileResponse:
    safe = Path(filename).name  # strip any path components
    fp = _export_dir(export_id) / safe
    if not fp.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(fp, media_type="text/csv", filename=safe)


@router.get("/jobs", response_model=List[JobStatus])
def list_jobs() -> List[JobStatus]:
    return [JobStatus(**j) for j in jobs.list_jobs()]


@router.get("/jobs/{job_id}", response_model=JobStatus)
def job_status(job_id: str) -> JobStatus:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job
