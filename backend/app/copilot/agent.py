"""Chat orchestrator: stream model output, run tools, surface proposals as events."""
from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any, Dict, Iterator, List

from .. import store
from . import settings as cfg_mod
from .llm import LLMUnavailable, OllamaClient
from .redact import Redactor
from .skills import SKILLS, pick_skill
from .tools import REGISTRY, Tool, ToolContext, execute

_BASE_RULES = """You are Sora, the AI assistant built into Portage, a Rally-to-Jira migration platform. If asked who you are, say you are Sora.
Rules:
- Use tools to get facts. Never invent ids, names, versions or values.
- To change anything, call a propose_* tool. It only creates a proposal; tell the user to review it and click Apply. Never say a change has been applied.
- In catalogs, source is the Rally value and target is the Jira value.
- If a tool returns an error, correct the arguments and try once more, otherwise explain the problem plainly.
- Emails appear as placeholders such as <email_1>. Use them exactly as written.
- If required information is missing (for example which artifact), ask one short question instead of guessing.
- Be concise. Use short bullet lists. Mention mapping version names.
- Never show tool names, JSON or internal ids to the user; describe actions in plain English."""


def _system_prompt(skill_key: str, page: Dict[str, Any]) -> str:
    skill = SKILLS[skill_key]
    ctx = [f"Today is {date.today().isoformat()}.", f"Active skill: {skill.label}. {skill.instructions}"]
    bits = [f"{k}: {v}" for k, v in (("page", page.get("route")), ("selected mapping id", page.get("mapping_id")),
                                      ("artifact", page.get("artifact")), ("catalog kind", page.get("lookup_kind")),
                                      ("current source id", page.get("source_id"))) if v]
    if bits:
        ctx.append("User context: " + "; ".join(bits) + ".")
    return _BASE_RULES + "\n\n" + "\n".join(ctx)


def _tools_for(skill_key: str, mode: str) -> List[Tool]:
    skill = SKILLS[skill_key]
    names = skill.tools if skill.tools is not None else tuple(REGISTRY)
    tools = [REGISTRY[n] for n in names if n in REGISTRY]
    return [t for t in tools if mode != "readonly" or t.risk == "read"]


def _truncate(obj: Any, limit: int = 6000) -> str:
    text = json.dumps(obj, default=str)
    return text if len(text) <= limit else text[:limit] + '..."truncated"'


def run_chat(message: str, conversation_id: str, page: Dict[str, Any], skill_hint: str = "") -> Iterator[Dict[str, Any]]:
    cfg = cfg_mod.get()
    conv_id = conversation_id or uuid.uuid4().hex[:16]
    if not cfg["enabled"]:
        yield {"type": "error", "message": "Copilot is disabled in settings."}
        return

    client = OllamaClient(cfg["base_url"], cfg["model"])
    red = Redactor(cfg["redact"])
    skill = pick_skill(message, page.get("route", ""), skill_hint)
    ctx = ToolContext(conversation_id=conv_id, page=page)
    tools = _tools_for(skill.key, cfg["mode"])

    history = store.get_conversation(conv_id)
    messages: List[Dict[str, Any]] = [{"role": "system", "content": _system_prompt(skill.key, page)}]
    for m in (history["messages"] if history else [])[-10:]:
        if m["role"] in ("user", "assistant") and m["content"]:
            messages.append({"role": m["role"], "content": red.to_model(m["content"])})
    clean_message = message.strip()
    messages.append({"role": "user", "content": red.to_model(clean_message)})

    store.ensure_conversation(conv_id, clean_message)
    store.add_message(conv_id, "user", clean_message)
    store.audit(conv_id, "chat", "", {"skill": skill.key, "redact": cfg["redact"], "mode": cfg["mode"]})
    yield {"type": "meta", "conversation_id": conv_id, "skill": {"key": skill.key, "label": skill.label}}

    answer: List[str] = []
    used: List[str] = []
    proposal_ids: List[str] = []
    schemas = [t.schema() for t in tools]
    try:
        for _step in range(cfg["max_steps"]):
            restorer = red.stream()
            text_parts: List[str] = []
            calls: List[Dict[str, Any]] = []
            for ev in client.chat_stream(messages, schemas):
                if ev["type"] == "token":
                    text_parts.append(ev["text"])
                    out = restorer.feed(ev["text"])
                    if out:
                        answer.append(out)
                        yield {"type": "token", "text": out}
                else:
                    calls.extend(ev["calls"])
            tail = restorer.flush()
            if tail:
                answer.append(tail)
                yield {"type": "token", "text": tail}

            if not calls:
                break

            messages.append({"role": "assistant", "content": "".join(text_parts),
                             "tool_calls": [{"function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]})
            for c in calls:
                tool = REGISTRY.get(c["name"])
                args = red.obj_from_model(c["arguments"])
                yield {"type": "tool_call", "name": c["name"], "args": args}
                if tool is None or tool not in tools:
                    result: Dict[str, Any] = {"error": f"Unknown or unavailable tool '{c['name']}'"}
                    proposal = None
                else:
                    result, proposal = execute(tool, ctx, args)
                    used.append(tool.name)
                    store.audit(conv_id, "tool", tool.name, {"args": args, "ok": "error" not in result})
                ok = "error" not in result
                yield {"type": "tool_result", "name": c["name"], "ok": ok,
                       "summary": result.get("error") or result.get("summary") or "done"}
                if proposal:
                    proposal_ids.append(proposal["id"])
                    yield {"type": "proposal", "proposal": proposal}
                messages.append({"role": "tool", "tool_name": c["name"],
                                 "content": red.to_model(_truncate(result))})
        else:
            yield {"type": "token", "text": "\n\nI reached my step limit before finishing. Please narrow the request."}
    except LLMUnavailable as e:
        yield {"type": "error", "message": str(e)}
        store.audit(conv_id, "llm_error", "", {"error": str(e)})
    finally:
        final = "".join(answer).strip()
        if final or proposal_ids:
            store.add_message(conv_id, "assistant", final,
                              {"skill": skill.key, "tools": used, "proposals": proposal_ids})

    yield {"type": "done", "conversation_id": conv_id}
