"""Copilot tool registry.

Read tools return data immediately. Write tools never mutate anything when the
model calls them: they validate, compute a diff and create a *proposal* that a
human must apply through the API. `apply` re-derives the change from the stored
arguments, so a proposal is always evaluated against current state.
"""
from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Type

from pydantic import BaseModel, Field, ValidationError

from .. import jobs, store
from ..config import settings as app_settings
from ..engine.field_catalog import build_catalog
from ..engine.mapping import ARTIFACT_TYPES
from ..engine.transform import load_dataframe
from ..schemas import LOOKUP_KINDS
from ..versioning import diff_entries, diff_mappings
from . import knowledge


class ToolError(Exception):
    """A recoverable problem reported back to the model."""


@dataclass
class ToolContext:
    conversation_id: str = ""
    page: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    name: str
    description: str
    model: Type[BaseModel]
    risk: str                                   # read | write
    run: Callable[[ToolContext, Any], Dict[str, Any]]   # read: result; write: preview
    apply: Optional[Callable[[Any], Dict[str, Any]]] = None

    def schema(self) -> Dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": _json_schema(self.model)}}


REGISTRY: Dict[str, Tool] = {}


def _register(tool: Tool) -> None:
    REGISTRY[tool.name] = tool


def _json_schema(model: Type[BaseModel]) -> Dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return clean(defs[node["$ref"].split("/")[-1]])
            return {k: clean(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [clean(x) for x in node]
        return node

    out = clean(raw)
    out.setdefault("properties", {})
    return out


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
ARTIFACT_SLUG = {"Epic": "epic", "Feature": "feature", "User Story": "us", "Task": "task", "Defect": "defect"}
TYPE_TRANSFORM = {"array": "labels", "number": "number", "date": "date"}
_ARTIFACT_ALIASES = {"story": "User Story", "userstory": "User Story", "us": "User Story", "stories": "User Story",
                     "bug": "Defect", "defects": "Defect", "bugs": "Defect", "tasks": "Task",
                     "features": "Feature", "epics": "Epic"}
_KIND_COLUMNS = {"sprint": ["Iteration", "Sprint"], "version": ["Release", "Milestone", "Fix Version"],
                 "user": ["Owner", "Submitted By"], "team": ["Team"]}


def _norm_artifact(name: str) -> str:
    key = re.sub(r"[\s_\-]", "", name or "").lower()
    for a in ARTIFACT_TYPES:
        if re.sub(r"[\s_\-]", "", a).lower() == key:
            return a
    if key in _ARTIFACT_ALIASES:
        return _ARTIFACT_ALIASES[key]
    raise ToolError(f"Unknown artifact '{name}'. Valid: {', '.join(ARTIFACT_TYPES)}")


def _norm_kind(kind: str) -> str:
    k = (kind or "").strip().lower()
    if k not in LOOKUP_KINDS:
        raise ToolError(f"Unknown catalog kind '{kind}'. Valid: {', '.join(LOOKUP_KINDS)}")
    return k


def _fields_for(artifact: str) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, str]]]:
    cat = build_catalog()
    rally = {f["key"]: f for f in cat["common"]["rally"] + cat["specific"][artifact]["rally"]}  # type: ignore[index,operator]
    jira = {f["key"]: f for f in cat["common"]["jira"] + cat["specific"][artifact]["jira"]}      # type: ignore[index,operator]
    return rally, jira


def _resolve(name: str, fields: Dict[str, Dict[str, str]], what: str) -> str:
    low = (name or "").strip().lower()
    for key, f in fields.items():
        if low in (key.lower(), f["label"].lower()):
            return key
    raise ToolError(f"Unknown {what} '{name}'. Valid {what}s: {', '.join(fields)}")


def _primary_catalog(kind: str) -> Optional[Dict[str, Any]]:
    found = store.list_lookups(kind)
    return found[0] if found else None


_SOURCE_ID = re.compile(r"[0-9a-f]{32}")


def _source_path(ctx: ToolContext, source_id: Optional[str]):
    """Explicit id, else the file open in the UI, else the most recent upload."""
    sid = source_id if source_id and _SOURCE_ID.fullmatch(source_id) else ctx.page.get("source_id")
    if not sid or not _SOURCE_ID.fullmatch(sid):
        files = sorted((p for p in app_settings.upload_dir.glob("*.csv") if _SOURCE_ID.fullmatch(p.stem)),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            raise ToolError("No uploaded source files found. Upload a Rally CSV on the Migrate page first.")
        return files[0]
    p = app_settings.upload_dir / f"{sid}.csv"
    if not p.exists():
        raise ToolError(f"Source {sid} not found")
    return p


def _compact_profile(maps: List[Dict[str, Any]]) -> List[str]:
    out = []
    for m in maps:
        srcs = m.get("sources") or ([m["source"]] if m.get("source") else [])
        out.append(f"{m['target']} <- {' | '.join(srcs)}" + (f" [{m['transform']}]" if m.get("transform") else ""))
    return out


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------
class NoArgs(BaseModel):
    pass


def _list_mappings(ctx: ToolContext, a: NoArgs) -> Dict[str, Any]:
    items = [{"id": m["id"], "name": m["name"], "version": m.get("version", 1),
              "fields_per_artifact": {k: len(v) for k, v in (m.get("profiles") or {}).items()}}
             for m in store.list_mappings()[:40]]
    return {"mappings": items, "count": len(items)}


class GetMappingArgs(BaseModel):
    mapping_id: int = Field(description="Saved mapping id from list_mappings")
    artifact: Optional[str] = Field(default=None, description="Epic, Feature, User Story, Task or Defect")


def _get_mapping(ctx: ToolContext, a: GetMappingArgs) -> Dict[str, Any]:
    m = store.get_mapping(a.mapping_id)
    if not m:
        raise ToolError(f"Mapping {a.mapping_id} not found")
    profiles = m.get("profiles") or {}
    if a.artifact:
        art = _norm_artifact(a.artifact)
        return {"id": m["id"], "name": m["name"], "artifact": art, "field_maps": _compact_profile(profiles.get(art, []))}
    return {"id": m["id"], "name": m["name"], "artifacts": {k: _compact_profile(v) for k, v in profiles.items()},
            "value_maps": {v["field"]: len(v.get("values", {})) for v in m.get("value_maps") or []}}


class CompareArgs(BaseModel):
    mapping_id: int = Field(description="Older mapping version id")
    other_id: int = Field(description="Newer mapping version id")


def _compare_mappings(ctx: ToolContext, a: CompareArgs) -> Dict[str, Any]:
    x, y = store.get_mapping(a.mapping_id), store.get_mapping(a.other_id)
    if not x or not y:
        raise ToolError("One of the mappings was not found")
    return {"from": x["name"], "to": y["name"], **diff_mappings(x, y)}


class FieldsArgs(BaseModel):
    artifact: str = Field(description="Epic, Feature, User Story, Task or Defect")


def _list_mapping_fields(ctx: ToolContext, a: FieldsArgs) -> Dict[str, Any]:
    art = _norm_artifact(a.artifact)
    rally, jira = _fields_for(art)
    return {"artifact": art, "rally_source_columns": list(rally),
            "jira_target_fields": [f"{k} ({f['label']}, {f['data_type']})" for k, f in jira.items()]}


class OptKind(BaseModel):
    kind: Optional[str] = Field(default=None, description="sprint, version, user or team")


def _list_catalogs(ctx: ToolContext, a: OptKind) -> Dict[str, Any]:
    kind = _norm_kind(a.kind) if a.kind else None
    return {"catalogs": [{"id": c["id"], "name": c["name"], "kind": c["kind"], "entries": len(c["entries"])}
                         for c in store.list_lookups(kind)]}


class CatalogEntriesArgs(BaseModel):
    kind: str = Field(description="sprint, version, user or team")
    query: Optional[str] = Field(default=None, description="Case-insensitive text to look for in source or target")
    limit: int = Field(default=40, ge=1, le=100)


def _get_catalog_entries(ctx: ToolContext, a: CatalogEntriesArgs) -> Dict[str, Any]:
    kind = _norm_kind(a.kind)
    cat = _primary_catalog(kind)
    if not cat:
        return {"kind": kind, "exists": False, "total": 0, "entries": []}
    q = (a.query or "").lower()
    rows = [{"source": s, "target": t} for s, t in cat["entries"].items() if not q or q in s.lower() or q in t.lower()]
    return {"kind": kind, "catalog_id": cat["id"], "name": cat["name"], "total": len(cat["entries"]),
            "matched": len(rows), "entries": rows[:a.limit]}


class KindArgs(BaseModel):
    kind: str = Field(description="sprint, version, user or team")


def _list_catalog_versions(ctx: ToolContext, a: KindArgs) -> Dict[str, Any]:
    kind = _norm_kind(a.kind)
    cat = _primary_catalog(kind)
    if not cat:
        return {"kind": kind, "versions": []}
    return {"kind": kind, "catalog_id": cat["id"], "versions": store.list_versions("lookup", cat["id"])[:20]}


class LimitArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=30)


def _list_sources(ctx: ToolContext, a: LimitArgs) -> Dict[str, Any]:
    files = sorted((p for p in app_settings.upload_dir.glob("*.csv") if re.fullmatch(r"[0-9a-f]{32}", p.stem)),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:a.limit]
    out = []
    for p in files:
        try:
            header = p.open(encoding="utf-8-sig", errors="ignore").readline().strip()
        except OSError:
            header = ""
        out.append({"source_id": p.stem, "size_kb": round(p.stat().st_size / 1024, 1), "columns": header[:300]})
    return {"sources": out, "current_page_source": ctx.page.get("source_id") or None}


class SourceArgs(BaseModel):
    source_id: Optional[str] = Field(default=None, description="Optional. Omit to use the current or latest upload")


def _describe_source(ctx: ToolContext, a: SourceArgs) -> Dict[str, Any]:
    path = _source_path(ctx, a.source_id)
    df = load_dataframe(path)
    return {"source_id": path.stem, "rows": int(len(df)), "columns": list(df.columns),
            "sample": df.head(3).fillna("").to_dict(orient="records")}


class DistinctArgs(BaseModel):
    source_id: Optional[str] = Field(default=None, description="Optional. Omit to use the current or latest upload")
    column: str = Field(description="Exact CSV column name")
    limit: int = Field(default=30, ge=1, le=100)


def _distinct_values(ctx: ToolContext, a: DistinctArgs) -> Dict[str, Any]:
    df = load_dataframe(_source_path(ctx, a.source_id))
    if a.column not in df.columns:
        raise ToolError(f"Column '{a.column}' not found. Columns: {', '.join(df.columns)}")
    counts = df[a.column].astype(str).str.strip()
    counts = counts[counts != ""].value_counts()
    return {"column": a.column, "distinct": int(len(counts)),
            "values": [{"value": v, "count": int(c)} for v, c in counts.head(a.limit).items()]}


class UnmappedArgs(BaseModel):
    source_id: Optional[str] = Field(default=None, description="Optional. Omit to use the current or latest upload")
    kind: str = Field(description="sprint, version, user or team")
    column: Optional[str] = Field(default=None, description="CSV column; omit to auto-pick by kind")


def _find_unmapped(ctx: ToolContext, a: UnmappedArgs) -> Dict[str, Any]:
    kind = _norm_kind(a.kind)
    path = _source_path(ctx, a.source_id)
    df = load_dataframe(path)
    cols = [a.column] if a.column else [c for c in _KIND_COLUMNS[kind] if c in df.columns]
    if not cols or any(c not in df.columns for c in cols):
        raise ToolError(f"No suitable column for {kind}. Columns: {', '.join(df.columns)}")
    known = {k.strip().lower() for c in store.list_lookups(kind) for k in c["entries"]}
    series = df[cols].astype(str).stack().str.strip()
    counts = series[series != ""].value_counts()
    missing = [{"value": v, "count": int(c)} for v, c in counts.items() if v.lower() not in known]
    return {"source_id": path.stem, "kind": kind, "columns": cols, "distinct_values": int(len(counts)),
            "mapped": int(len(counts)) - len(missing), "unmapped_total": len(missing), "unmapped": missing[:50]}


def _list_jobs(ctx: ToolContext, a: LimitArgs) -> Dict[str, Any]:
    return {"jobs": [{"job_id": j["job_id"], "state": j.get("state"), "dry_run": j.get("dry_run"),
                      "total": j.get("total"), "created": j.get("created"), "failed": j.get("failed"),
                      "started_at": j.get("started_at")} for j in jobs.list_jobs(a.limit)]}


class JobArgs(BaseModel):
    job_id: str


def _get_job(ctx: ToolContext, a: JobArgs) -> Dict[str, Any]:
    j = jobs.get_job(a.job_id)
    if not j:
        raise ToolError(f"Job {a.job_id} not found")
    failed = [{"id": i.external_id, "message": i.message[:200]} for i in j.items if i.status == "failed"][:10]
    return {"job_id": j.job_id, "state": j.state, "dry_run": j.dry_run, "total": j.total, "created": j.created,
            "failed": j.failed, "attachments_uploaded": j.attachments_uploaded, "failed_items": failed,
            "log_tail": j.log[-5:]}


class DocsArgs(BaseModel):
    query: str = Field(description="Keywords to look up in the Portage documentation")


def _search_docs(ctx: ToolContext, a: DocsArgs) -> Dict[str, Any]:
    return {"results": knowledge.search(a.query)}


def _connection_status(ctx: ToolContext, a: NoArgs) -> Dict[str, Any]:
    row = store.get_setting("connection_profile")
    if not row:
        return {"saved": False}
    data = json.loads(row["value"])
    jira, rally = data.get("jira") or {}, data.get("rally") or {}
    return {"saved": True, "saved_at": row["updated_at"],
            "jira": {"configured": bool(jira.get("base_url")), "base_url": jira.get("base_url", ""),
                     "project_key": jira.get("project_key", "")},
            "rally": {"configured": bool(rally.get("api_key"))}}


# ---------------------------------------------------------------------------
# Write tools (propose -> apply)
# ---------------------------------------------------------------------------
class MappingOp(BaseModel):
    action: Literal["set", "remove"] = Field(description="'set' maps Rally source column(s) to the Jira target; 'remove' deletes the mapping for the target")
    target: str = Field(description="Jira target field key or label, e.g. sprint, fix_versions, story_points")
    sources: List[str] = Field(default_factory=list, description="Rally source column(s); several = fallback, first non-empty wins")


class MappingEditArgs(BaseModel):
    artifact: str = Field(description="Epic, Feature, User Story, Task or Defect")
    operations: List[MappingOp] = Field(min_length=1)
    base_mapping_id: Optional[int] = Field(default=None, description="Saved mapping to start from; omit to start from the default connections")
    version_name: Optional[str] = Field(default=None, description="Exact name for the new version if the user gave one, e.g. jira_us_mapping_v5 or just v5. Omit to auto-number")
    note: str = Field(default="", description="Short reason for the change")


def _base_template(base_id: Optional[int]) -> Dict[str, Any]:
    if base_id:
        m = store.get_mapping(base_id)
        if not m:
            raise ToolError(f"Base mapping {base_id} not found")
        return copy.deepcopy(m)
    cat = build_catalog()
    profiles: Dict[str, List[Dict[str, Any]]] = {}
    for art in ARTIFACT_TYPES:
        _, jira = _fields_for(art)
        by_target: Dict[str, List[str]] = {}
        for c in cat["defaults"][art]:  # type: ignore[index]
            by_target.setdefault(c["target"], []).append(c["source"])
        profiles[art] = [{"sources": s, "source": s[0], "target": t, "target_type": jira.get(t, {}).get("data_type", ""),
                          "transform": TYPE_TRANSFORM.get(jira.get(t, {}).get("data_type", ""), "")}
                         for t, s in by_target.items()]
    value_maps: List[Dict[str, Any]] = []
    try:
        from ..routers.mappings import default_template
        value_maps = [v.model_dump() for v in default_template().value_maps]
    except Exception:  # noqa: BLE001  (defaults are best-effort)
        pass
    return {"name": "Rally -> Jira mapping", "description": "", "version": 1, "issue_type_field": "Issue Type",
            "field_maps": profiles["Feature"], "profiles": profiles, "value_maps": value_maps}


def _apply_ops(base: Dict[str, Any], a: MappingEditArgs) -> Dict[str, Any]:
    art = _norm_artifact(a.artifact)
    rally, jira = _fields_for(art)
    tpl = copy.deepcopy(base)
    maps = {m["target"]: m for m in (tpl.get("profiles") or {}).get(art, [])}
    for op in a.operations:
        target = _resolve(op.target, jira, "target field")
        if op.action == "remove":
            if target not in maps:
                raise ToolError(f"'{target}' is not mapped for {art}, nothing to remove")
            del maps[target]
            continue
        if not op.sources:
            raise ToolError(f"'set' on '{target}' needs at least one Rally source column")
        sources = [_resolve(s, rally, "Rally column") for s in op.sources]
        dtype = jira[target]["data_type"]
        maps[target] = {"sources": sources, "source": sources[0], "target": target, "target_type": dtype,
                        "transform": TYPE_TRANSFORM.get(dtype, "")}
    tpl.setdefault("profiles", {})[art] = list(maps.values())
    if art == "Feature":
        tpl["field_maps"] = tpl["profiles"][art]
    return tpl


def _next_mapping_name(artifact: str) -> Tuple[str, int]:
    base = f"jira_{ARTIFACT_SLUG[artifact]}_mapping"
    rx = re.compile(rf"^{re.escape(base)}_v(\d+)$")
    top = max([int(m.group(1)) for s in store.list_mappings() if (m := rx.match(s.get("name", "")))] or [0])
    return f"{base}_v{top + 1}", top + 1


_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,79}$")
_VERSIONED = re.compile(r"^jira_([a-z]+)_mapping_v(\d+)$")


def _resolve_version_name(artifact: str, requested: Optional[str]) -> Tuple[str, int]:
    """Name and version number for the new mapping: the user's choice if valid and free, else auto-numbered."""
    auto, auto_v = _next_mapping_name(artifact)
    name = (requested or "").strip()
    if not name:
        return auto, auto_v
    slug = ARTIFACT_SLUG[artifact]
    if re.fullmatch(r"[vV]?\d+", name):
        name = f"jira_{slug}_mapping_v{int(name.lstrip('vV'))}"
    if not _NAME_OK.match(name):
        raise ToolError("Version name may use letters, digits, spaces, '_', '-' and '.', up to 80 characters")
    m = _VERSIONED.match(name)
    if m and m.group(1) != slug:
        raise ToolError(f"'{name}' belongs to a different artifact. For {artifact} use jira_{slug}_mapping_vN")
    if name.lower() in {s.get("name", "").lower() for s in store.list_mappings()}:
        raise ToolError(f"A mapping named '{name}' already exists. The next free name is '{auto}'")
    return name, int(m.group(2)) if m else auto_v


def _plan_mapping_edit(ctx: ToolContext, a: MappingEditArgs) -> Dict[str, Any]:
    base = _base_template(a.base_mapping_id)
    new = _apply_ops(base, a)
    diff = diff_mappings(base, new)
    if not diff["artifacts"]:
        raise ToolError("No effective change: the mapping already matches the requested edit")
    name, _ = _resolve_version_name(_norm_artifact(a.artifact), a.version_name)
    return {"kind": "mapping", "title": f"Save new mapping version {name}",
            "base": base.get("name", "default connections"), "new_name": name, "diff": diff,
            "summary": diff["summary"]}


def _apply_mapping_edit(a: MappingEditArgs) -> Dict[str, Any]:
    art = _norm_artifact(a.artifact)
    new = _apply_ops(_base_template(a.base_mapping_id), a)
    name, version = _resolve_version_name(art, a.version_name)  # re-checked: the name may have been taken since the proposal
    saved = store.save_mapping({**new, "id": None, "name": name, "version": version,
                                "description": f"Edited by Sora. {a.note}".strip()})
    store.audit("", "mapping_saved", "propose_mapping_edit", {"id": saved["id"], "name": name})
    return {"id": saved["id"], "name": name, "refresh": ["mapping"]}


class Pair(BaseModel):
    source: str = Field(description="Rally value, e.g. the iteration or user name")
    target: str = Field(description="Jira value, e.g. sprint name/ID, version, email or team ID")


class CatalogUpsertArgs(BaseModel):
    kind: str = Field(description="sprint, version, user or team")
    entries: List[Pair] = Field(min_length=1, max_length=500)
    note: str = Field(default="", description="Short reason for the change")


def _clean_pairs(pairs: List[Pair]) -> Dict[str, str]:
    out = {p.source.strip(): p.target.strip() for p in pairs if p.source.strip() and p.target.strip()}
    if not out:
        raise ToolError("Entries must have non-empty source and target values")
    return out


def _plan_catalog_upsert(ctx: ToolContext, a: CatalogUpsertArgs) -> Dict[str, Any]:
    kind = _norm_kind(a.kind)
    cat = _primary_catalog(kind)
    current = cat["entries"] if cat else {}
    diff = diff_entries(current, {**current, **_clean_pairs(a.entries)})
    if not (diff["added"] or diff["changed"]):
        raise ToolError("No changes: every entry already exists with the same value")
    return {"kind": "catalog", "title": f"Update {kind} catalog", "catalog": cat["name"] if cat else f"{kind.title()} catalog (new)",
            "diff": diff, "summary": diff["summary"]}


def _apply_catalog_upsert(a: CatalogUpsertArgs) -> Dict[str, Any]:
    kind = _norm_kind(a.kind)
    cat = _primary_catalog(kind)
    merged = {**(cat["entries"] if cat else {}), **_clean_pairs(a.entries)}
    saved = store.save_lookup({"id": cat["id"] if cat else None, "name": cat["name"] if cat else f"{kind.title()} catalog",
                               "kind": kind, "side": "rally_to_jira", "entries": merged},
                              author="copilot", message=a.note or f"Copilot: upsert {len(a.entries)} entries")
    store.audit("", "catalog_saved", "propose_catalog_upsert", {"id": saved["id"], "kind": kind})
    return {"id": saved["id"], "kind": kind, "entries": len(merged), "refresh": ["lookups"]}


class CatalogRemoveArgs(BaseModel):
    kind: str = Field(description="sprint, version, user or team")
    sources: List[str] = Field(min_length=1, max_length=500, description="Rally values (keys) to remove")
    note: str = ""


def _plan_catalog_remove(ctx: ToolContext, a: CatalogRemoveArgs) -> Dict[str, Any]:
    kind = _norm_kind(a.kind)
    cat = _primary_catalog(kind)
    if not cat:
        raise ToolError(f"There is no {kind} catalog yet")
    wanted = {s.strip().lower() for s in a.sources}
    remaining = {k: v for k, v in cat["entries"].items() if k.lower() not in wanted}
    diff = diff_entries(cat["entries"], remaining)
    if not diff["removed"]:
        raise ToolError("None of those values exist in the catalog")
    return {"kind": "catalog", "title": f"Remove entries from {kind} catalog", "catalog": cat["name"],
            "diff": diff, "summary": diff["summary"]}


def _apply_catalog_remove(a: CatalogRemoveArgs) -> Dict[str, Any]:
    kind = _norm_kind(a.kind)
    cat = _primary_catalog(kind)
    if not cat:
        raise ToolError(f"There is no {kind} catalog yet")
    wanted = {s.strip().lower() for s in a.sources}
    remaining = {k: v for k, v in cat["entries"].items() if k.lower() not in wanted}
    saved = store.save_lookup({**cat, "entries": remaining}, author="copilot",
                              message=a.note or f"Copilot: removed {len(cat['entries']) - len(remaining)} entries")
    store.audit("", "catalog_saved", "propose_catalog_remove", {"id": saved["id"], "kind": kind})
    return {"id": saved["id"], "kind": kind, "entries": len(remaining), "refresh": ["lookups"]}


class CatalogRestoreArgs(BaseModel):
    kind: str = Field(description="sprint, version, user or team")
    version: int = Field(ge=1, description="Version number from list_catalog_versions")


def _plan_catalog_restore(ctx: ToolContext, a: CatalogRestoreArgs) -> Dict[str, Any]:
    kind = _norm_kind(a.kind)
    cat = _primary_catalog(kind)
    snap = store.get_version("lookup", cat["id"], a.version) if cat else None
    if not cat or not snap:
        raise ToolError(f"Version {a.version} of the {kind} catalog does not exist")
    diff = diff_entries(cat["entries"], snap["payload"].get("entries", {}))
    return {"kind": "catalog", "title": f"Restore {kind} catalog to v{a.version}", "catalog": cat["name"],
            "diff": diff, "summary": diff["summary"]}


def _apply_catalog_restore(a: CatalogRestoreArgs) -> Dict[str, Any]:
    kind = _norm_kind(a.kind)
    cat = _primary_catalog(kind)
    snap = store.get_version("lookup", cat["id"], a.version) if cat else None
    if not cat or not snap:
        raise ToolError(f"Version {a.version} of the {kind} catalog does not exist")
    saved = store.save_lookup({**snap["payload"], "id": cat["id"]}, author="copilot",
                              message=f"Copilot: restored v{a.version}")
    store.audit("", "catalog_restored", "propose_catalog_restore", {"id": saved["id"], "version": a.version})
    return {"id": saved["id"], "kind": kind, "entries": len(saved["entries"]), "refresh": ["lookups"]}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def _r(name: str, desc: str, model: Type[BaseModel], fn: Callable) -> None:
    _register(Tool(name, desc, model, "read", fn))


def _w(name: str, desc: str, model: Type[BaseModel], plan: Callable, apply: Callable) -> None:
    _register(Tool(name, desc + " Creates a proposal; nothing changes until the user approves it.", model, "write", plan, apply))


_r("list_mappings", "List saved mapping versions (id, name, field counts).", NoArgs, _list_mappings)
_r("get_mapping", "Show the field maps of a saved mapping, optionally for one artifact.", GetMappingArgs, _get_mapping)
_r("compare_mappings", "Diff two saved mapping versions.", CompareArgs, _compare_mappings)
_r("list_mapping_fields", "List valid Rally source columns and Jira target fields for an artifact.", FieldsArgs, _list_mapping_fields)
_r("list_catalogs", "List Jira catalogs (sprint, version, user, team) and entry counts.", OptKind, _list_catalogs)
_r("get_catalog_entries", "Look up entries in a catalog, optionally filtered by text.", CatalogEntriesArgs, _get_catalog_entries)
_r("list_catalog_versions", "List the saved version history of a catalog.", KindArgs, _list_catalog_versions)
_r("list_sources", "List recently uploaded source CSV files.", LimitArgs, _list_sources)
_r("describe_source", "Show columns, row count and sample rows of an uploaded source file.", SourceArgs, _describe_source)
_r("distinct_values", "Count distinct values of a column in an uploaded source file.", DistinctArgs, _distinct_values)
_r("find_unmapped_values", "Find values in a source file that are missing from the sprint/version/user/team catalog.", UnmappedArgs, _find_unmapped)
_r("list_jobs", "List recent migration jobs.", LimitArgs, _list_jobs)
_r("get_job", "Show a migration job's results and failures.", JobArgs, _get_job)
_r("search_docs", "Search Portage documentation and concepts.", DocsArgs, _search_docs)
_r("connection_status", "Show whether Jira/Rally connections are saved (never returns secrets).", NoArgs, _connection_status)
_w("propose_mapping_edit", "Add, change or remove field mappings for one artifact and save as a new mapping version.",
   MappingEditArgs, _plan_mapping_edit, _apply_mapping_edit)
_w("propose_catalog_upsert", "Add or update entries in the sprint, version, user or team catalog.",
   CatalogUpsertArgs, _plan_catalog_upsert, _apply_catalog_upsert)
_w("propose_catalog_remove", "Remove entries from a catalog.", CatalogRemoveArgs, _plan_catalog_remove, _apply_catalog_remove)
_w("propose_catalog_restore", "Restore a catalog to an earlier version (undo).", CatalogRestoreArgs, _plan_catalog_restore, _apply_catalog_restore)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def _coerce_args(raw: Any) -> Dict[str, Any]:
    """Small local models often send nested lists/objects as JSON strings; decode them."""
    if isinstance(raw, str):
        raw = json.loads(raw or "{}")
    out: Dict[str, Any] = {}
    for k, v in (raw or {}).items():
        if isinstance(v, str) and v.strip().lower() in ("null", "none", "undefined"):
            continue  # small models write "null" for omitted optionals
        if isinstance(v, str) and v.lstrip()[:1] in ("[", "{"):
            try:
                v = json.loads(v)
            except ValueError:
                pass
        out[k] = v
    return out


def execute(tool: Tool, ctx: ToolContext, raw_args: Any) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Validate and run a tool. Returns (result for the model, proposal or None)."""
    try:
        args = tool.model(**_coerce_args(raw_args))
    except (ValidationError, ValueError, TypeError) as e:
        msg = e.errors()[0]["msg"] + " at " + ".".join(map(str, e.errors()[0]["loc"])) if isinstance(e, ValidationError) else str(e)
        return {"error": f"Invalid arguments: {msg}"}, None
    try:
        out = tool.run(ctx, args)
    except ToolError as e:
        return {"error": str(e)}, None
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}, None
    if tool.risk == "read":
        return out, None
    pid = uuid.uuid4().hex[:12]
    store.save_proposal(pid, ctx.conversation_id, tool.name, tool.risk, args.model_dump(), out)
    store.audit(ctx.conversation_id, "proposal_created", tool.name, {"proposal_id": pid, "summary": out.get("summary")})
    return ({"status": "proposal_created", "proposal_id": pid, "summary": out.get("summary"),
             "note": "Awaiting user approval. The change is NOT applied yet."}, store.get_proposal(pid))


def apply_proposal(proposal: Dict[str, Any]) -> Dict[str, Any]:
    tool = REGISTRY[proposal["tool"]]
    assert tool.apply is not None
    return tool.apply(tool.model(**proposal["args"]))
