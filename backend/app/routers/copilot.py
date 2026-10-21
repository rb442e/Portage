"""Sora API: streaming chat, proposals (approve/reject), history, settings."""
from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from .. import auth, store
from ..copilot import attachments, settings as cfg_mod
from ..copilot.agent import run_chat
from ..copilot.llm import OllamaClient, model_installed
from ..copilot.skills import SKILLS, suggestions_for
from ..copilot.tools import ToolError, apply_proposal

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


class PageContext(BaseModel):
    route: str = ""
    mapping_id: Optional[int] = None
    artifact: Optional[str] = None
    lookup_kind: Optional[str] = None
    source_id: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    conversation_id: str = ""
    skill: str = ""
    attachments: List[str] = []
    page: PageContext = PageContext()


class SettingsPatch(BaseModel):
    enabled: Optional[bool] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    mode: Optional[str] = None
    redact: Optional[bool] = None
    max_steps: Optional[int] = None
    vision_model: Optional[str] = None
    attachment_retention_days: Optional[int] = None


def _sse(events: Iterator[Dict[str, Any]]) -> Iterator[str]:
    for ev in events:
        yield f"data: {json.dumps(ev, default=str)}\n\n"


@router.post("/chat")
def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message is empty")
    viewer = auth.current_user(request)["role"] == "viewer"   # viewers can ask Sora but never get change tools
    user = auth.current_user(request)
    events = run_chat(req.message, req.conversation_id, req.page.model_dump(exclude_none=True), req.skill,
                      req.attachments, read_only=viewer,
                      can_manage_mcp=(not auth.enabled() or user["role"] == "admin"))
    return StreamingResponse(_sse(events), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/status")
def status() -> Dict[str, Any]:
    cfg = cfg_mod.get()
    llm = OllamaClient(cfg["base_url"], cfg["model"]).health()
    llm["vision_model_available"] = model_installed(llm["models"], cfg["vision_model"])
    return {"settings": cfg, "llm": llm}


@router.post("/attachments")
async def upload_attachment(file: UploadFile) -> Dict[str, Any]:
    data = await file.read(attachments.MAX_IMAGE_BYTES + 1)
    try:
        meta = attachments.save(file.filename or "attachment", data)
    except attachments.AttachmentError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    attachments.purge(cfg_mod.get()["attachment_retention_days"])
    return attachments.public(meta)


@router.get("/attachments/{attachment_id}")
def attachment_image(attachment_id: str) -> Response:
    meta = attachments.get(attachment_id)
    if not meta or meta["kind"] != "image":
        raise HTTPException(status_code=404, detail="Attachment not found")
    return Response(attachments.read(attachment_id), media_type=meta["mime"],
                    headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"})


@router.delete("/attachments/{attachment_id}")
def remove_attachment(attachment_id: str) -> Dict[str, str]:
    attachments.delete(attachment_id)
    return {"deleted": attachment_id}


@router.get("/settings")
def get_settings() -> Dict[str, Any]:
    return cfg_mod.get()


@router.put("/settings")
def put_settings(patch: SettingsPatch) -> Dict[str, Any]:
    try:
        return cfg_mod.update(patch.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/skills")
def skills() -> List[Dict[str, str]]:
    return [{"key": s.key, "label": s.label, "summary": s.summary} for s in SKILLS.values() if s.key != "general"]


@router.get("/suggestions")
def suggestions(route: str = "") -> List[str]:
    return suggestions_for(route)


@router.get("/conversations")
def conversations() -> List[Dict[str, Any]]:
    return store.list_conversations()


@router.get("/conversations/{conv_id}")
def conversation(conv_id: str) -> Dict[str, Any]:
    conv = store.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {**conv, "proposals": store.list_proposals(conv_id)}


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: str) -> Dict[str, str]:
    store.delete_conversation(conv_id)
    return {"deleted": conv_id}


@router.post("/proposals/{proposal_id}/apply")
def apply(proposal_id: str, request: Request) -> Dict[str, Any]:
    if cfg_mod.get()["mode"] == "readonly":
        raise HTTPException(status_code=403, detail="Copilot is in read-only mode")
    p = store.get_proposal(proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if p["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal already {p['status']}")
    if p["tool"] == "propose_mcp_server":
        if auth.enabled() and auth.current_user(request)["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only an admin can add MCP servers.")
        from ..copilot import external_mcp
        if not external_mcp.editing_enabled():
            raise HTTPException(status_code=403, detail="MCP server editing is disabled in Portage Settings.")
    try:
        result = apply_proposal(p)
    except ToolError as e:
        raise HTTPException(status_code=422, detail=str(e))
    store.resolve_proposal(proposal_id, "applied", result)
    store.audit(p["conversation_id"], "proposal_applied", p["tool"], {"proposal_id": proposal_id, **result})
    return {"proposal": store.get_proposal(proposal_id), "result": result}


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: str) -> Dict[str, Any]:
    p = store.get_proposal(proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if p["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal already {p['status']}")
    store.resolve_proposal(proposal_id, "rejected")
    store.audit(p["conversation_id"], "proposal_rejected", p["tool"], {"proposal_id": proposal_id})
    return {"proposal": store.get_proposal(proposal_id)}


@router.get("/audit")
def audit(limit: int = 100) -> List[Dict[str, Any]]:
    return store.list_audit(limit)
