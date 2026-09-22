"""CRUD for reusable mapping templates."""
from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException

from .. import store
from ..engine.codegen import generate_python
from ..engine.default_mappings import build_default_template
from ..engine.field_catalog import build_catalog
from ..engine.legacy_import import build_legacy_template
from ..engine.mapping import (ARTIFACT_TYPES, CANONICAL_FIELD_DEFS,
                              CANONICAL_FIELDS, DATA_TYPES,
                              DEFAULT_JIRA_ALL_TEMPLATE)
from ..schemas import (CanonicalFieldDef, GeneratedCode, LegacyImportResult,
                       MappingTemplate)

router = APIRouter(prefix="/api/mappings", tags=["mappings"])


@router.get("/catalog")
def catalog() -> dict:
    """Rally + Jira fields (common + per-artifact) and default connections."""
    return build_catalog()


@router.post("/generate", response_model=GeneratedCode)
def generate(tpl: MappingTemplate) -> GeneratedCode:
    """Consolidate all artifacts into one versioned, readable Python module."""
    return GeneratedCode(**generate_python(tpl.model_dump()))


@router.get("/canonical-fields", response_model=List[str])
def canonical_fields() -> List[str]:
    return CANONICAL_FIELDS


@router.get("/fields", response_model=List[CanonicalFieldDef])
def typed_fields() -> List[CanonicalFieldDef]:
    """Canonical fields with their ConnectALL-style data types."""
    return [CanonicalFieldDef(**d) for d in CANONICAL_FIELD_DEFS]


@router.get("/data-types", response_model=List[str])
def data_types() -> List[str]:
    return DATA_TYPES


@router.get("/artifact-types", response_model=List[str])
def artifact_types() -> List[str]:
    return ARTIFACT_TYPES


@router.get("/defaults", response_model=MappingTemplate)
def default_template() -> MappingTemplate:
    """The per-artifact-type default Rally → Jira mapping (seeds the Studio)."""
    repo_root = Path(__file__).resolve().parents[4]
    return MappingTemplate(**build_default_template(repo_root / "config.yaml"))


@router.post("/import-legacy", response_model=LegacyImportResult)
def import_legacy() -> LegacyImportResult:
    """Seed a Studio template from rally_to_jira.py's rules + repo config.yaml."""
    # portage/backend/app/routers/mappings.py -> repo root is parents[4].
    repo_root = Path(__file__).resolve().parents[4]
    result = build_legacy_template(repo_root / "config.yaml")
    return LegacyImportResult(template=MappingTemplate(**result["template"]),
                              notes=result["notes"])


@router.get("/builtin", response_model=MappingTemplate)
def builtin_template() -> MappingTemplate:
    return MappingTemplate(**DEFAULT_JIRA_ALL_TEMPLATE)


@router.get("", response_model=List[MappingTemplate])
def list_templates() -> List[MappingTemplate]:
    return [MappingTemplate(**m) for m in store.list_mappings()]


@router.post("", response_model=MappingTemplate)
def save_template(tpl: MappingTemplate) -> MappingTemplate:
    saved = store.save_mapping(tpl.model_dump())
    return MappingTemplate(**saved)


@router.get("/{mapping_id}", response_model=MappingTemplate)
def get_template(mapping_id: int) -> MappingTemplate:
    data = store.get_mapping(mapping_id)
    if not data:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return MappingTemplate(**data)


@router.delete("/{mapping_id}")
def delete_template(mapping_id: int) -> dict:
    store.delete_mapping(mapping_id)
    return {"deleted": mapping_id}
