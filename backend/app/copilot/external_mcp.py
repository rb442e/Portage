"""Read-only MCP clients that contribute tools to Sora.

Definitions come from two places:
- PORTAGE_EXTERNAL_MCP_SERVERS (JSON array): administrator-managed, never shown or edited in the UI.
- Settings > MCP server > Add server: stored in the database. Environment values are encrypted at rest and are
  never returned by the API.
Adding servers from the UI makes Portage launch programs on the host, so it is limited to admins when sign-in is on,
and otherwise needs PORTAGE_ALLOW_MCP_SERVER_EDITING=1 (set it to 0 to always lock it). Only local stdio servers are
launched, and only tools annotated readOnlyHint=true are exposed to Sora.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

from .. import secretbox, store

EDIT_FLAG = "PORTAGE_ALLOW_MCP_SERVER_EDITING"
STORE_KEY = "mcp_external_servers"
DISABLED_TOOLS_KEY = "mcp_external_disabled_tools"
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_SERVERS = 8
MAX_ARGS, MAX_ENV = 40, 20
MAX_TOOLS_PER_SERVER = 32
MAX_RESULT_CHARS = 5000


class ExternalMcpError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServerConfig:
    name: str
    command: str
    args: List[str]
    env: Dict[str, str]
    cwd: Optional[str]
    source: str = "environment"        # environment | ui
    url: Optional[str] = None
    transport: str = "stdio"


@dataclass(frozen=True)
class RemoteTool:
    name: str                 # namespaced name presented to Sora
    server: str
    remote_name: str
    description: str
    schema: Dict[str, Any]

    def llm_schema(self) -> Dict[str, Any]:
        schema = json.loads(json.dumps(self.schema))
        if "parallel" in self.server.lower():
            guidance = {
                "search_queries": "A non-empty list of specific web search queries based on the user's actual request.",
                "objective": "The concrete research question to answer; do not use generic placeholder text.",
                "model_name": "The model or subject being researched, not the assistant's own model name.",
                "session_id": "The current Portage conversation identifier; Portage supplies this value.",
            }
            for key, description in guidance.items():
                prop = schema.get("properties", {}).get(key)
                if isinstance(prop, dict):
                    prop["description"] = description
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": schema}}


def editing_enabled() -> bool:
    """On when sign-in is on (only admins reach the endpoints); otherwise only with PORTAGE_ALLOW_MCP_SERVER_EDITING=1."""
    flag = os.environ.get(EDIT_FLAG, "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    from .. import auth
    return auth.enabled()


def _parse(raw: Optional[str] = None) -> List[ServerConfig]:
    raw = os.environ.get("PORTAGE_EXTERNAL_MCP_SERVERS", "") if raw is None else raw
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ExternalMcpError(f"PORTAGE_EXTERNAL_MCP_SERVERS is not valid JSON: {e.msg}") from e
    if not isinstance(data, list) or len(data) > MAX_SERVERS:
        raise ExternalMcpError(f"Configure an array of at most {MAX_SERVERS} stdio servers")
    out, names = [], set()
    for item in data:
        if not isinstance(item, dict):
            raise ExternalMcpError("Each external MCP server must be an object")
        name, command = item.get("name"), item.get("command")
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in names:
            raise ExternalMcpError("Server names must be unique lowercase ids (a-z, 0-9, _ and -)")
        if not isinstance(command, str) or not command.strip() or "\x00" in command:
            raise ExternalMcpError(f"Server '{name}' needs a valid command")
        args, env, cwd = item.get("args", []), item.get("env", {}), item.get("cwd")
        if not isinstance(args, list) or not all(isinstance(x, str) and "\x00" not in x for x in args):
            raise ExternalMcpError(f"Server '{name}' args must be a list of strings")
        if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            raise ExternalMcpError(f"Server '{name}' env must be a string map")
        if cwd is not None and (not isinstance(cwd, str) or "\x00" in cwd):
            raise ExternalMcpError(f"Server '{name}' cwd must be a path string")
        out.append(ServerConfig(name, command.strip(), args, env, cwd, "environment"))
        names.add(name)
    return out


# ---------------------------------------------------------------------------
# Servers added in the UI (stored in the database; env values encrypted)
# ---------------------------------------------------------------------------
def _stored_rows() -> List[Dict[str, Any]]:
    row = store.get_setting(STORE_KEY)
    try:
        data = json.loads(row["value"]) if row else []
    except ValueError:
        data = []
    return data if isinstance(data, list) else []


def _save_rows(rows: List[Dict[str, Any]]) -> None:
    if rows:
        store.set_setting(STORE_KEY, json.dumps(rows))
    else:
        store.delete_setting(STORE_KEY)


def disabled_tool_names() -> List[str]:
    row = store.get_setting(DISABLED_TOOLS_KEY)
    try:
        names = json.loads(row["value"]) if row else []
    except ValueError:
        names = []
    return sorted(set(n for n in names if isinstance(n, str))) if isinstance(names, list) else []


def set_disabled_tool_names(tool_names: List[str]) -> List[str]:
    """Persist per-tool exclusions for Sora; names are namespaced as ext_<server>__<tool>."""
    if not isinstance(tool_names, list) or len(tool_names) > MAX_SERVERS * MAX_TOOLS_PER_SERVER:
        raise ExternalMcpError("Provide a valid list of at most 256 external tools")
    configured = set(names())
    clean = set()
    for value in tool_names:
        if not isinstance(value, str):
            raise ExternalMcpError("Tool names must be strings")
        match = re.fullmatch(r"ext_([a-z][a-z0-9_-]{0,31})__([a-z][a-z0-9_-]{0,31})", value)
        if not match or match.group(1) not in configured:
            raise ExternalMcpError(f"Unknown external MCP tool '{value}'")
        clean.add(value)
    result = sorted(clean)
    if result:
        store.set_setting(DISABLED_TOOLS_KEY, json.dumps(result))
    else:
        store.delete_setting(DISABLED_TOOLS_KEY)
    store.audit("", "mcp_external_tools_changed", "", {"disabled_tools": result})
    return result


def _ui_servers() -> List[ServerConfig]:
    out = []
    for r in _stored_rows():
        try:
            env = {k: secretbox.decrypt(v) for k, v in (r.get("env") or {}).items()}
            transport = r.get("transport", "stdio")
            out.append(ServerConfig(r["name"], r.get("command", ""), list(r.get("args") or []), env, r.get("cwd"), "ui", r.get("url"), transport))
        except (KeyError, TypeError, AttributeError):
            continue
    return out


def _all_servers() -> List[ServerConfig]:
    env_servers = _parse()
    taken = {s.name for s in env_servers}
    return env_servers + [s for s in _ui_servers() if s.name not in taken]   # the administrator's definition wins


def names() -> List[str]:
    """Names only; safe to include in settings schema and never starts a process."""
    return [s.name for s in _all_servers()]


def _env_names() -> List[str]:
    try:
        return [s.name for s in _parse()]
    except ExternalMcpError:
        return []


def list_view() -> Dict[str, Any]:
    """Definitions for the Settings page. Never includes env values or the commands of admin-managed servers."""
    config_error = ""
    try:
        env_servers = _parse()
    except ExternalMcpError as e:
        env_servers, config_error = [], str(e)
    taken = {s.name for s in env_servers}
    servers: List[Dict[str, Any]] = [{"name": s.name, "source": "environment"} for s in env_servers]
    for r in _stored_rows():
        if r.get("name") in taken:
            continue
        servers.append({"name": r.get("name"), "source": "ui", "transport": r.get("transport", "stdio"), "url": r.get("url", ""), "command": r.get("command", ""),
                        "args": list(r.get("args") or []), "cwd": r.get("cwd") or "",
                        "env_keys": sorted((r.get("env") or {}).keys())})
    return {"editing_enabled": editing_enabled(), "flag": EDIT_FLAG, "max_servers": MAX_SERVERS,
            "servers": servers, "config_error": config_error}


def _resolve_command(command: str) -> str:
    if "/" in command:
        path = os.path.expanduser(command)
        if not os.path.isabs(path):
            raise ExternalMcpError("Use an absolute path for the command, or a name on Portage's PATH")
        if not (os.path.isfile(path) and os.access(path, os.X_OK)):
            raise ExternalMcpError(f"'{command}' is not an executable file")
        return path
    if shutil.which(command) is None:
        raise ExternalMcpError(f"'{command}' was not found on Portage's PATH. Use its full path instead")
    return command


def validate(data: Dict[str, Any], current: Optional[str] = None) -> Dict[str, Any]:
    """Clean definition {name, command, args, cwd, env: {KEY: value | None}}. None keeps the stored value."""
    name = str(data.get("name") or "").strip().lower()
    if not NAME.fullmatch(name):
        raise ExternalMcpError("Name must start with a letter and use only lowercase letters, digits, - or _ (up to 32 characters)")
    if current and name != current:
        raise ExternalMcpError("A server's name cannot be changed. Remove it and add it again under the new name")
    existing = {r.get("name") for r in _stored_rows()}
    if not current and (name in existing or name in _env_names()):
        raise ExternalMcpError(f"A server named '{name}' already exists")
    if not current and len(existing) + len(_env_names()) >= MAX_SERVERS:
        raise ExternalMcpError(f"Portage supports at most {MAX_SERVERS} external servers")

    transport = data.get("transport", "stdio")
    if transport not in ("stdio", "http", "sse"):
        raise ExternalMcpError("Choose stdio, Streamable HTTP, or SSE transport")
    url = str(data.get("url") or "").strip()
    if transport in ("http", "sse"):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
            raise ExternalMcpError("Enter a valid HTTP or HTTPS MCP URL without embedded credentials")
        command = ""
    else:
        url = ""
        command = str(data.get("command") or "").strip()
    if transport == "stdio":
        if not command or len(command) > 400 or any(c in command for c in "\x00\n\r"):
            raise ExternalMcpError("Enter the command that starts the server")
        command = _resolve_command(command)

    raw_args = data.get("args") or []
    if not isinstance(raw_args, list) or len(raw_args) > MAX_ARGS:
        raise ExternalMcpError(f"Provide at most {MAX_ARGS} arguments")
    args = [str(a) for a in raw_args if str(a).strip() != ""]
    if any("\x00" in a or len(a) > 1000 for a in args):
        raise ExternalMcpError("Arguments must be plain text of at most 1,000 characters")

    cwd = str(data.get("cwd") or "").strip() or None
    if cwd:
        cwd = os.path.expanduser(cwd)
        if not os.path.isabs(cwd) or not os.path.isdir(cwd):
            raise ExternalMcpError("Working directory must be an absolute path to an existing folder")

    env: Dict[str, Optional[str]] = {}
    for item in data.get("env") or []:
        key = str(item.get("key") or "").strip()
        value = item.get("value")
        if not key and not value:
            continue
        valid_key = ENV_KEY.fullmatch(key) if transport == "stdio" else re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}", key)
        if not valid_key:
            raise ExternalMcpError(f"'{key}' is not a valid environment variable name")
        if any(existing_key.lower() == key.lower() for existing_key in env):
            raise ExternalMcpError(f"Environment variable {key} is listed twice")
        if value is not None and (len(str(value)) > 4000 or "\x00" in str(value)):
            raise ExternalMcpError(f"The value of {key} is too long or contains invalid characters")
        env[key] = str(value) if value not in (None, "") else None
    if len(env) > MAX_ENV:
        raise ExternalMcpError(f"Provide at most {MAX_ENV} environment variables")
    return {"name": name, "transport": transport, "url": url, "command": command, "args": args, "cwd": cwd, "env": env}


def _find_row(name: Optional[str]) -> Optional[Dict[str, Any]]:
    return next((r for r in _stored_rows() if r.get("name") == name), None)


def _audit(event: str, name: str, row: Dict[str, Any]) -> None:
    # Names and launch details only; environment values are never written to the audit log.
    store.audit("", event, name, {"command": row.get("command"), "args": row.get("args"), "cwd": row.get("cwd"),
                                  "env_keys": sorted((row.get("env") or {}).keys())})


def save_server(data: Dict[str, Any], current: Optional[str] = None) -> None:
    """Add (current=None) or update a UI-defined server. Environment values are encrypted before storage."""
    if current and _find_row(current) is None:
        raise ExternalMcpError("That server is managed by the administrator's environment, or no longer exists")
    clean = validate(data, current)
    stored_env = (_find_row(current) or {}).get("env", {})
    env: Dict[str, str] = {}
    for key, value in clean["env"].items():
        if value is None:
            if key not in stored_env:
                raise ExternalMcpError(f"Enter a value for {key}")
            env[key] = stored_env[key]                      # blank on edit keeps the saved (encrypted) value
        else:
            env[key] = secretbox.encrypt(value)
    row = {"name": clean["name"], "transport": clean["transport"], "url": clean["url"], "command": clean["command"], "args": clean["args"], "cwd": clean["cwd"], "env": env}
    rows = _stored_rows()
    rows = [row if r.get("name") == current else r for r in rows] if current else rows + [row]
    _save_rows(rows)
    _audit("mcp_server_updated" if current else "mcp_server_added", clean["name"], row)


def delete_server(name: str) -> None:
    row = _find_row(name)
    if row is None:
        raise ExternalMcpError("That server is managed by the administrator's environment, or no longer exists")
    _save_rows([r for r in _stored_rows() if r.get("name") != name])
    prefix = f"ext_{name}__"
    remaining = [tool for tool in disabled_tool_names() if not tool.startswith(prefix)]
    if remaining:
        store.set_setting(DISABLED_TOOLS_KEY, json.dumps(remaining))
    else:
        store.delete_setting(DISABLED_TOOLS_KEY)
    _audit("mcp_server_removed", name, row)


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------
def _classify(tool: Any) -> Optional[str]:
    """None when the tool is explicitly read-only; otherwise the reason it is blocked."""
    a = tool.annotations
    if a is None or a.readOnlyHint is None:
        return "no safety annotation"
    if a.readOnlyHint is not True or a.destructiveHint is True:
        return "can change data"
    if not NAME.fullmatch(tool.name):
        return "unsupported tool name"
    return None


def _short(error: BaseException) -> str:
    while getattr(error, "exceptions", None):
        error = error.exceptions[0]                    # unwrap anyio task-group errors
    if isinstance(error, FileNotFoundError):
        return "The command could not be started. Check the path."
    if isinstance(error, PermissionError):
        return "Portage is not allowed to run that command."
    if isinstance(error, TimeoutError):
        return "The server did not respond in time."
    return (str(error) or type(error).__name__)[:180]


def probe(server: ServerConfig) -> Dict[str, Any]:
    """Start the server once; report tools Sora could use and tools that are blocked. Never returns secrets."""
    base: Dict[str, Any] = {"name": server.name, "tool_count": 0, "blocked_count": 0,
                            "tools": [], "tool_descriptions": {}, "blocked": []}
    try:
        tools = _run(_list_tools(server), timeout=20)
    except Exception as e:  # a failed optional server must not prevent Sora from starting
        return {**base, "status": "unavailable", "error": _short(e)}
    allowed = [t.name for t in tools if _classify(t) is None]
    descriptions = {t.name: (t.description or "").strip()[:500]
                    for t in tools if _classify(t) is None and (t.description or "").strip()}
    blocked = [{"name": t.name, "reason": _classify(t)} for t in tools if _classify(t) is not None]
    return {**base, "status": "available", "tool_count": len(allowed), "blocked_count": len(blocked),
            "tools": allowed, "tool_descriptions": descriptions, "blocked": blocked}


def configured() -> List[Dict[str, Any]]:
    """Probe every server. Never return commands, arguments or environment values."""
    try:
        servers = _all_servers()
    except ExternalMcpError as e:
        return [{"name": "configuration error", "status": "invalid configuration", "error": str(e),
                 "tool_count": 0, "blocked_count": 0, "tools": [], "blocked": []}]
    return [probe(s) for s in servers]


def probe_saved(name: str) -> Dict[str, Any]:
    server = next((s for s in _all_servers() if s.name == name), None)
    if server is None:
        raise ExternalMcpError(f"No external server named '{name}'")
    return probe(server)


def probe_draft(data: Dict[str, Any], current: Optional[str] = None) -> Dict[str, Any]:
    """Validate an unsaved definition and start it once, so mistakes show before anything is stored."""
    clean = validate(data, current)
    saved = (_find_row(current) or {}).get("env", {})
    env: Dict[str, str] = {}
    for key, value in clean["env"].items():
        if value is None:
            if key not in saved:
                raise ExternalMcpError(f"Enter a value for {key}")
            env[key] = secretbox.decrypt(saved[key])
        else:
            env[key] = value
    return probe(ServerConfig(clean["name"], clean["command"], clean["args"], env, clean["cwd"], "ui", clean["url"], clean["transport"]))


def _stdio_args(server: ServerConfig) -> StdioServerParameters:
    # Give the child only basic runtime variables plus values the administrator explicitly configured.
    inherited = {key: value for key, value in os.environ.items()
                 if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}}
    return StdioServerParameters(command=server.command, args=server.args,
                                 env={**inherited, **server.env}, cwd=server.cwd)


async def _list_tools(server: ServerConfig) -> List[Any]:
    if server.url:
        client = sse_client(server.url, headers=server.env or None) if server.transport == "sse" else streamablehttp_client(server.url, headers=server.env or None)
        async with client as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.list_tools()
                return list(response.tools)[:MAX_TOOLS_PER_SERVER]
    async with stdio_client(_stdio_args(server)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            response = await session.list_tools()
            return list(response.tools)[:MAX_TOOLS_PER_SERVER]


async def _call(server: ServerConfig, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if server.url:
        client = sse_client(server.url, headers=server.env or None) if server.transport == "sse" else streamablehttp_client(server.url, headers=server.env or None)
    else:
        client = stdio_client(_stdio_args(server))
    async with client as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            selected = next((t for t in tools.tools if t.name == name), None)
            if not selected or not selected.annotations or selected.annotations.readOnlyHint is not True:
                raise ExternalMcpError(f"{server.name}.{name} is no longer marked read-only; refusing the call")
            if selected.annotations.destructiveHint is True:
                raise ExternalMcpError(f"{server.name}.{name} is marked destructive; refusing the call")
            response = await session.call_tool(name, arguments, read_timeout_seconds=timedelta(seconds=40))
            content = []
            for item in response.content:
                if getattr(item, "type", "") == "text":
                    content.append(item.text)
                elif getattr(item, "type", "") == "image":
                    content.append("[image content omitted]")
                else:
                    content.append(f"[{getattr(item, 'type', 'non-text')} content omitted]")
            text = "\n".join(content)[:MAX_RESULT_CHARS]
            if response.isError:
                return {"error": text or "External MCP tool failed"}
            result: Dict[str, Any] = {"content": text, "summary": text[:300] or "done"}
            if response.structuredContent is not None:
                result["structured_content"] = response.structuredContent
            return result


def _coerce_schema_value(value: Any, schema: Dict[str, Any], path: str) -> Any:
    """Repair local-model calls that encode schema containers as JSON strings."""
    expected = schema.get("type")
    if isinstance(expected, list):
        expected = next((t for t in expected if t in ("array", "object") and value is not None), expected[0])
    if expected in ("array", "object") and isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            # Local models can emit Python-style literals. literal_eval parses
            # data only; it cannot execute calls or expressions.
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                if expected == "array" and schema.get("items", {}).get("type") == "string":
                    value = [value]
                else:
                    raise ExternalMcpError(f"{path} must be {expected}; provide it as a JSON {expected}")
        if expected == "array" and not isinstance(value, list):
            raise ExternalMcpError(f"{path} must be an array")
        if expected == "object" and not isinstance(value, dict):
            raise ExternalMcpError(f"{path} must be an object")
    if expected == "array" and isinstance(value, list):
        item_schema = schema.get("items", {})
        return [_coerce_schema_value(item, item_schema, f"{path}[{i}]") for i, item in enumerate(value)]
    if expected == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        return {key: _coerce_schema_value(item, properties.get(key, {}), f"{path}.{key}")
                for key, item in value.items()}
    return value


def normalize_arguments(remote: RemoteTool, arguments: Dict[str, Any], session_id: Optional[str] = None) -> Dict[str, Any]:
    """Coerce schema-declared containers before passing arguments to an MCP server."""
    if not isinstance(arguments, dict):
        raise ExternalMcpError("Tool arguments must be an object")
    properties = remote.schema.get("properties", {})
    normalized = {key: _coerce_schema_value(value, properties.get(key, {}), key)
                  for key, value in arguments.items()}
    # Conversation-scoped IDs are generated by Portage; never rely on a model
    # placeholder such as "stable identifier for the current conversation".
    if session_id and "session_id" in properties:
        normalized["session_id"] = session_id
    _validate_schema_value(normalized, remote.schema, "arguments")
    return normalized


def _validate_schema_value(value: Any, schema: Dict[str, Any], path: str) -> None:
    """Check common JSON Schema constraints before making a remote call."""
    expected = schema.get("type")
    if isinstance(expected, str) and value is not None:
        matches = {"object": isinstance(value, dict), "array": isinstance(value, list),
                   "string": isinstance(value, str), "boolean": isinstance(value, bool),
                   "integer": isinstance(value, int) and not isinstance(value, bool),
                   "number": isinstance(value, (int, float)) and not isinstance(value, bool)}
        if expected in matches and not matches[expected]:
            raise ExternalMcpError(f"{path} must be {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ExternalMcpError(f"{path} must be one of: {', '.join(map(str, schema['enum']))}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        raise ExternalMcpError(f"{path} must not be empty")
    if isinstance(value, list):
        if path.endswith("search_queries") and (not value or any(not isinstance(item, str) or not item.strip() for item in value)):
            raise ExternalMcpError(f"{path} must contain at least one non-empty search query")
        if len(value) < schema.get("minItems", 0):
            raise ExternalMcpError(f"{path} must contain at least {schema['minItems']} item(s)")
        for index, item in enumerate(value):
            _validate_schema_value(item, schema.get("items", {}), f"{path}[{index}]")
    if isinstance(value, dict):
        missing = [key for key in schema.get("required", []) if key not in value]
        if missing:
            raise ExternalMcpError(f"{path} is missing required argument(s): {', '.join(missing)}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _validate_schema_value(item, properties[key], f"{path}.{key}")


def _run(awaitable, timeout: float = 45):
    async def limited():
        with anyio.fail_after(timeout):
            return await awaitable
    return anyio.run(limited)


def discover(enabled_servers: List[str]) -> List[RemoteTool]:
    """List only opted-in, explicitly read-only tools, namespaced as ext_<server>__<tool>."""
    chosen = set(enabled_servers)
    if not chosen:
        return []
    tools: List[RemoteTool] = []
    for server in _all_servers():
        if server.name not in chosen:
            continue
        try:
            for tool in _run(_list_tools(server), timeout=20):
                if _classify(tool) is not None:
                    continue
                name = f"ext_{server.name}__{tool.name}"
                desc = (tool.description or f"Read-only tool from external MCP server {server.name}.")[:500]
                schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else {"type": "object", "properties": {}}
                tools.append(RemoteTool(name, server.name, tool.name, desc, schema))
        except Exception as e:  # optional MCP server errors do not take down Sora
            continue
    return tools


def call(remote: RemoteTool, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Spawn the configured local server for a call and return a bounded, JSON-safe result."""
    server = next((s for s in _all_servers() if s.name == remote.server), None)
    if server is None:
        raise ExternalMcpError(f"External MCP server '{remote.server}' is no longer configured")
    try:
        return _run(_call(server, remote.remote_name, arguments), timeout=45)
    except Exception as e:
        raise ExternalMcpError(f"{remote.server}.{remote.remote_name} failed: {str(e)[:200]}") from e
