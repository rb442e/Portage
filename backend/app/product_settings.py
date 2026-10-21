"""Product settings: one typed, sectioned registry for everything an admin may tune.

Precedence per key: saved value (app_settings) > environment variable > default.
The Settings page and API are generated from SECTIONS, so adding a Field here adds it everywhere.
Secrets never belong here: Portage does not persist tokens, and no field type exists for them.
"""
from __future__ import annotations

import json
import os
import platform
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from . import __version__, store
from .config import settings as env_config

_TRUE = ("true", "1", "yes", "on")
_FALSE = ("false", "0", "no", "off")


def _tool_names() -> Tuple[str, ...]:
    from .copilot.tools import REGISTRY   # lazy: tools import graph, which reads these settings
    return tuple(REGISTRY)


def _external_mcp_names() -> Tuple[str, ...]:
    from .copilot.external_mcp import names
    try:
        return tuple(names())
    except Exception:  # malformed admin config should be reported by the MCP status card, not break Settings
        return ()


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    type: str                      # bool | int | text | choice | multi
    default: Any
    help: str = ""
    env: str = ""
    choices: Union[Tuple[str, ...], Callable[[], Tuple[str, ...]]] = ()
    labels: Dict[str, str] = field(default_factory=dict)
    min: Optional[int] = None
    max: Optional[int] = None
    clean: Optional[Callable[[Any], Any]] = None
    hidden: bool = False           # managed by a dedicated panel instead of the generic form

    def options(self) -> Tuple[str, ...]:
        return tuple(self.choices() if callable(self.choices) else self.choices)


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    summary: str
    fields: Tuple[Field, ...]
    storage_key: str = ""          # legacy key kept so existing saved settings keep working


SECTIONS: Tuple[Section, ...] = (
    Section("sora", "Sora assistant", "The built-in assistant: local model, change mode and privacy.", (
        Field("enabled", "Enable Sora", "bool", True, "Turns the assistant on or off."),
        Field("base_url", "Ollama URL", "text", "http://localhost:11434", "Where the local model runs.",
              env="PORTAGE_OLLAMA_URL", clean=lambda s: s.rstrip("/")),
        Field("model", "Model", "text", "llama3.1:8b", "Must support tool calling.", env="PORTAGE_COPILOT_MODEL"),
        Field("mode", "Mode", "choice", "propose", "Read-only removes every tool that can propose a change.",
              env="PORTAGE_COPILOT_MODE", choices=("propose", "readonly"),
              labels={"propose": "Propose changes (you approve)", "readonly": "Read-only (no changes)"}),
        Field("redact", "Mask emails and secrets", "bool", True, "Masked before text reaches the model."),
        Field("max_steps", "Max steps per turn", "int", 6, "Tool calls Sora may chain in one answer.", min=1, max=12),
        Field("vision_model", "Vision model", "text", "gemma3:4b",
              "Reads screenshots you attach; Sora then answers from its description. Install with: ollama pull <model>.",
              env="PORTAGE_VISION_MODEL"),
        Field("attachment_retention_days", "Keep attachments (days)", "int", 7,
              "Files and screenshots attached to chats are deleted after this long.", min=1, max=90),
    ), storage_key="copilot_settings"),
    Section("mcp", "MCP server", "Control Portage's MCP server and read-only MCP tools available to Sora.", (
        Field("enabled", "Allow MCP access", "bool", True,
              "Master switch. When off, connected clients see no tools. Takes effect on the next call.",
              env="PORTAGE_MCP_ENABLED"),
        Field("read_only", "Read-only", "bool", False,
              "Hide every propose_* tool. MCP is also read-only whenever Sora's mode is read-only.",
              env="PORTAGE_MCP_READ_ONLY"),
        Field("redact", "Mask emails and secrets", "bool", True,
              "Applied to tool results sent to MCP clients. A cloud-backed client sends them to its provider.",
              env="PORTAGE_MCP_REDACT"),
        Field("hidden_tools", "Hidden tools", "multi", (), "Tools MCP clients cannot see or call.",
              env="PORTAGE_MCP_HIDDEN_TOOLS", choices=_tool_names),
        Field("external_servers", "External servers available to Sora", "multi", (),
              "Which external MCP servers Sora may use. Managed in the External MCP servers panel. Only tools explicitly marked read-only are exposed to Sora; external write tools are blocked.",
              env="PORTAGE_MCP_EXTERNAL_SERVERS", choices=_external_mcp_names, hidden=True),
    )),
    Section("graph", "GraphRAG", "How graph_search explores relationships (used by Sora and MCP clients).", (
        Field("default_depth", "Default depth", "int", 2, "Relationship hops followed when the caller gives none.",
              env="PORTAGE_GRAPH_DEFAULT_DEPTH", min=1, max=3),
        Field("max_nodes", "Max items per answer", "int", 24,
              "Upper bound on items in one graph answer; long answers are also trimmed to fit the model.",
              env="PORTAGE_GRAPH_MAX_NODES", min=8, max=60),
    )),
)
_BY_KEY = {s.key: s for s in SECTIONS}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _coerce(f: Field, v: Any) -> Any:
    if f.type == "bool":
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v.strip().lower() in _TRUE + _FALSE:
            return v.strip().lower() in _TRUE
        raise ValueError(f"{f.label} must be true or false")
    if f.type == "int":
        if isinstance(v, bool):
            raise ValueError(f"{f.label} must be a whole number")
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise ValueError(f"{f.label} must be a whole number") from None
        lo = f.min if f.min is not None else n
        hi = f.max if f.max is not None else n
        return max(lo, min(n, hi))
    if f.type == "text":
        s = str(v).strip()
        if not s:
            raise ValueError(f"{f.label} cannot be empty")
        return f.clean(s) if f.clean else s
    if f.type == "choice":
        s = str(v).strip().lower()
        if s not in f.options():
            raise ValueError(f"{f.label} must be one of: {', '.join(f.options())}")
        return s
    if f.type == "multi":
        items = [x.strip() for x in v.split(",")] if isinstance(v, str) else list(v or [])
        items = [str(x).strip() for x in items if str(x).strip()]
        unknown = [x for x in items if x not in f.options()]
        if unknown:
            raise ValueError(f"{f.label}: unknown {', '.join(unknown)}")
        return [o for o in f.options() if o in items]          # stable order, no duplicates
    raise ValueError(f"Unsupported setting type {f.type}")


# ---------------------------------------------------------------------------
# Storage and resolution
# ---------------------------------------------------------------------------
def _storage_key(sec: Section) -> str:
    return sec.storage_key or f"settings_{sec.key}"


def _section(key: str) -> Section:
    if key not in _BY_KEY:
        raise KeyError(key)
    return _BY_KEY[key]


def _stored(sec: Section) -> Dict[str, Any]:
    row = store.get_setting(_storage_key(sec))
    try:
        data = json.loads(row["value"]) if row else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _resolve(sec: Section) -> Dict[str, Tuple[Any, str]]:
    """key -> (value, source) where source is saved, env or default. Invalid stored or env values are skipped."""
    stored, out = _stored(sec), {}
    for f in sec.fields:
        for source, raw in (("saved", stored.get(f.key)), ("env", os.environ.get(f.env) if f.env else None)):
            if raw in (None, ""):
                continue
            try:
                out[f.key] = (_coerce(f, raw), source)
                break
            except ValueError:
                continue
        else:
            out[f.key] = (list(f.default) if f.type == "multi" else f.default, "default")
    return out


def get(section: str) -> Dict[str, Any]:
    return {k: v for k, (v, _) in _resolve(_section(section)).items()}


def update(section: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and save changed keys. Raises ValueError on bad input, KeyError on an unknown section."""
    sec = _section(section)
    fields = {f.key: f for f in sec.fields}
    unknown = sorted(set(patch) - set(fields))
    if unknown:
        raise ValueError(f"Unknown setting: {', '.join(unknown)}")
    current, stored, changed = _resolve(sec), _stored(sec), {}
    for key, raw in patch.items():
        if raw is None:
            continue
        value = _coerce(fields[key], raw)
        if key not in stored and value == current[key][0]:
            continue                                            # unchanged: keep following env and default
        changed[key] = value
    if changed:
        stored.update(changed)
        store.set_setting(_storage_key(sec), json.dumps(stored))
        store.audit("", "settings_changed", sec.key, changed)
    return get(section)


def reset(section: str, key: Optional[str] = None) -> Dict[str, Any]:
    """Forget the saved value of one key (or the whole section) so env and defaults apply again."""
    sec = _section(section)
    if key is not None and key not in {f.key for f in sec.fields}:
        raise ValueError(f"Unknown setting: {key}")
    stored = {} if key is None else {k: v for k, v in _stored(sec).items() if k != key}
    if stored:
        store.set_setting(_storage_key(sec), json.dumps(stored))
    else:
        store.delete_setting(_storage_key(sec))
    store.audit("", "settings_reset", sec.key, {"key": key or "*"})
    return get(section)


# ---------------------------------------------------------------------------
# Policy and views
# ---------------------------------------------------------------------------
def mcp_policy() -> Dict[str, Any]:
    """Effective MCP behaviour. MCP is never more permissive than Sora."""
    sora, mcp = get("sora"), get("mcp")
    return {"enabled": mcp["enabled"], "redact": mcp["redact"], "hidden_tools": set(mcp["hidden_tools"]),
            "read_only": mcp["read_only"] or sora["mode"] == "readonly",
            "external_servers": list(mcp["external_servers"])}


def describe() -> Dict[str, Any]:
    """Schema plus current values and where each value comes from, for the Settings page."""
    sections = []
    for sec in SECTIONS:
        resolved = _resolve(sec)
        sections.append({"key": sec.key, "label": sec.label, "summary": sec.summary, "fields": [
            {"key": f.key, "label": f.label, "type": f.type, "help": f.help, "env": f.env,
             "default": list(f.default) if f.type == "multi" else f.default,
             "value": resolved[f.key][0], "source": resolved[f.key][1],
             "choices": list(f.options()), "labels": f.labels, "min": f.min, "max": f.max,
             "hidden": f.hidden} for f in sec.fields]})
    return {"sections": sections}


def system_info() -> List[Dict[str, str]]:
    """Read-only facts set by environment variables at startup (change them and restart)."""
    return [
        {"label": "Portage version", "value": __version__, "env": ""},
        {"label": "Python", "value": platform.python_version(), "env": ""},
        {"label": "Data directory", "value": str(env_config.data_dir), "env": "PORTAGE_DATA_DIR"},
        {"label": "Database", "value": str(env_config.db_path), "env": ""},
        {"label": "Uploads", "value": str(env_config.upload_dir), "env": ""},
        {"label": "Allowed origins (CORS)", "value": ", ".join(env_config.cors_origins), "env": "PORTAGE_CORS_ORIGINS"},
        {"label": "Frontend served by API", "value": env_config.frontend_dist or "no", "env": "PORTAGE_FRONTEND_DIST"},
    ]


def mcp_connection() -> Dict[str, Any]:
    """Ready-to-paste client configuration for this installation."""
    python = os.path.abspath(sys.executable)   # normalises '..' but keeps the venv path (resolve() would not)
    env = {"PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PORTAGE_DATA_DIR": str(env_config.data_dir)}
    args = ["-m", "app.mcp_server"]
    entry = {"command": python, "args": args, "env": env}
    shell = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items()) + f" {shlex.quote(python)} -m app.mcp_server"
    return {"transport": "stdio", "shell": shell,
            "vscode": json.dumps({"servers": {"portage": {"type": "stdio", **entry}}}, indent=2),
            "generic": json.dumps({"mcpServers": {"portage": entry}}, indent=2)}
