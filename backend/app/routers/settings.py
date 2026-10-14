"""Settings API: the sectioned product settings behind the Settings page."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import product_settings as ps

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SectionPatch(BaseModel):
    values: Dict[str, Any]


def _view() -> Dict[str, Any]:
    policy = ps.mcp_policy()
    return {**ps.describe(), "system": ps.system_info(),
            "effective_mcp": {**policy, "hidden_tools": sorted(policy["hidden_tools"])}}


@router.get("")
def read_settings() -> Dict[str, Any]:
    return _view()


@router.put("/{section}")
def save_section(section: str, patch: SectionPatch) -> Dict[str, Any]:
    try:
        ps.update(section, patch.values)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown settings section '{section}'")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _view()


@router.delete("/{section}")
def reset_section(section: str) -> Dict[str, Any]:
    try:
        ps.reset(section)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown settings section '{section}'")
    return _view()


@router.delete("/{section}/{key}")
def reset_key(section: str, key: str) -> Dict[str, Any]:
    try:
        ps.reset(section, key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown settings section '{section}'")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _view()


@router.get("/mcp/connection")
def mcp_connection() -> Dict[str, Any]:
    return ps.mcp_connection()
