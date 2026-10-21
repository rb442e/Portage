"""Settings API: the sectioned product settings behind the Settings page."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import product_settings as ps
from ..copilot import external_mcp

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SectionPatch(BaseModel):
    values: Dict[str, Any]


class EnvVar(BaseModel):
    key: str = Field("", max_length=64)
    value: Optional[str] = Field(None, max_length=4000)     # omitted on edit = keep the saved value


class ServerBody(BaseModel):
    name: str = Field("", max_length=64)
    command: str = Field("", max_length=400)
    args: List[str] = Field(default_factory=list, max_length=external_mcp.MAX_ARGS)
    cwd: str = Field("", max_length=1000)
    env: List[EnvVar] = Field(default_factory=list, max_length=external_mcp.MAX_ENV)
    enable_for_sora: bool = False
    current: Optional[str] = None                           # draft test of an existing server's edit
    transport: str = "stdio"
    url: str = Field("", max_length=2000)


class ExternalToolAccessBody(BaseModel):
    disabled_tools: List[str] = Field(default_factory=list, max_length=external_mcp.MAX_SERVERS * external_mcp.MAX_TOOLS_PER_SERVER)


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


@router.get("/mcp/external-servers")
def external_mcp_servers() -> Dict[str, Any]:
    """Probe configured local stdio servers and return only names, tools and status (never command/env)."""
    return {"servers": external_mcp.configured(), "enabled_for_sora": ps.get("mcp")["external_servers"]}


def _require_editing() -> None:
    if not external_mcp.editing_enabled():
        raise HTTPException(
            status_code=403,
            detail=f"Editing MCP servers is turned off. Starting a server runs a program on this computer, so it needs "
                   f"sign-in to be on (admins only) or {external_mcp.EDIT_FLAG}=1.")


def _definitions() -> Dict[str, Any]:
    return {**external_mcp.list_view(), "enabled_for_sora": ps.get("mcp")["external_servers"],
            "disabled_tools": external_mcp.disabled_tool_names()}


def _payload(body: ServerBody) -> Dict[str, Any]:
    return {"name": body.name, "transport": body.transport, "url": body.url, "command": body.command, "args": body.args, "cwd": body.cwd,
            "env": [e.model_dump() for e in body.env]}


@router.get("/mcp/servers")
def mcp_server_definitions() -> Dict[str, Any]:
    """Definitions for the management panel. Environment values and admin-managed commands are never included."""
    return _definitions()


@router.put("/mcp/servers/tool-access")
def save_external_tool_access(body: ExternalToolAccessBody) -> Dict[str, Any]:
    """Save which discovered, read-only remote tools Sora may call."""
    try:
        external_mcp.set_disabled_tool_names(body.disabled_tools)
    except external_mcp.ExternalMcpError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _definitions()


@router.post("/mcp/servers/test")
def test_draft_server(body: ServerBody) -> Dict[str, Any]:
    """Validate and start an unsaved definition once, so mistakes show before anything is stored."""
    _require_editing()
    try:
        return external_mcp.probe_draft(_payload(body), body.current)
    except external_mcp.ExternalMcpError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/mcp/servers")
def add_server(body: ServerBody) -> Dict[str, Any]:
    _require_editing()
    try:
        external_mcp.save_server(_payload(body))
        if body.enable_for_sora:
            name = body.name.strip().lower()
            ps.update("mcp", {"external_servers": [*ps.get("mcp")["external_servers"], name]})
    except external_mcp.ExternalMcpError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _definitions()


@router.put("/mcp/servers/{name}")
def update_server(name: str, body: ServerBody) -> Dict[str, Any]:
    _require_editing()
    try:
        external_mcp.save_server(_payload(body), current=name)
    except external_mcp.ExternalMcpError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _definitions()


@router.delete("/mcp/servers/{name}")
def remove_server(name: str) -> Dict[str, Any]:
    _require_editing()
    keep = [n for n in ps.get("mcp")["external_servers"] if n != name]   # read before the name stops being valid
    try:
        external_mcp.delete_server(name)
    except external_mcp.ExternalMcpError as e:
        raise HTTPException(status_code=404, detail=str(e))
    ps.update("mcp", {"external_servers": keep})
    return _definitions()


@router.post("/mcp/servers/{name}/test")
def test_saved_server(name: str) -> Dict[str, Any]:
    try:
        return external_mcp.probe_saved(name)
    except external_mcp.ExternalMcpError as e:
        raise HTTPException(status_code=404, detail=str(e))
