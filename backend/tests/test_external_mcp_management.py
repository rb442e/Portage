"""Adding external MCP servers in Settings is gated, validated, and never leaks environment values."""
import json
import sys
from pathlib import Path

import pytest

from app import store
from app.copilot import external_mcp

FIXTURE = Path(__file__).parent / "fixtures" / "external_mcp_server.py"
SECRET = "super-secret-token-123"


def body(name="docs", **extra):
    return {"name": name, "command": sys.executable, "args": [str(FIXTURE)], "cwd": str(FIXTURE.parent),
            "env": [{"key": "FIXTURE_CONFIG", "value": SECRET}], **extra}


@pytest.fixture
def editing(monkeypatch):
    monkeypatch.setenv(external_mcp.EDIT_FLAG, "1")


def test_editing_is_locked_by_default(client):
    view = client.get("/api/settings/mcp/servers").json()
    assert view["editing_enabled"] is False and view["flag"] == external_mcp.EDIT_FLAG
    for method, url in (("post", "/api/settings/mcp/servers"), ("post", "/api/settings/mcp/servers/test"),
                        ("put", "/api/settings/mcp/servers/docs"), ("delete", "/api/settings/mcp/servers/docs")):
        r = getattr(client, method)(url, json=body()) if method != "delete" else client.delete(url)
        assert r.status_code == 403 and external_mcp.EDIT_FLAG in r.json()["detail"]
    assert store.get_setting(external_mcp.STORE_KEY) is None


def test_add_test_enable_and_remove_server(client, editing):
    draft = client.post("/api/settings/mcp/servers/test", json=body()).json()
    assert draft["status"] == "available" and draft["tools"] == ["lookup"]
    assert {b["name"] for b in draft["blocked"]} == {"mutate", "unspecified"}

    added = client.post("/api/settings/mcp/servers", json=body(enable_for_sora=True))
    assert added.status_code == 200
    view = added.json()
    assert [s["name"] for s in view["servers"]] == ["docs"] and view["servers"][0]["source"] == "ui"
    assert view["enabled_for_sora"] == ["docs"]
    assert [t.name for t in external_mcp.discover(["docs"])] == ["ext_docs__lookup"]
    assert client.post("/api/settings/mcp/servers/docs/test").json()["tool_count"] == 1

    removed = client.delete("/api/settings/mcp/servers/docs").json()
    assert removed["servers"] == [] and removed["enabled_for_sora"] == []
    events = [a["event"] for a in store.list_audit()]
    assert "mcp_server_added" in events and "mcp_server_removed" in events


def test_environment_values_are_encrypted_and_never_returned_or_audited(client, editing):
    client.post("/api/settings/mcp/servers", json=body())
    stored = store.get_setting(external_mcp.STORE_KEY)["value"]
    assert SECRET not in stored
    listing = client.get("/api/settings/mcp/servers").text
    assert SECRET not in listing and "FIXTURE_CONFIG" in listing
    assert SECRET not in json.dumps(store.list_audit())
    assert SECRET not in client.get("/api/settings/mcp/external-servers").text
    client.put("/api/settings/mcp", json={"values": {"external_servers": ["docs"]}})
    tool = external_mcp.discover(["docs"])[0]
    assert external_mcp.call(tool, {"query": "x"})["structured_content"]["configured"] == SECRET


def test_blank_value_on_edit_keeps_saved_secret(client, editing):
    client.post("/api/settings/mcp/servers", json=body())
    edit = body(args=[str(FIXTURE)])
    edit["env"] = [{"key": "FIXTURE_CONFIG", "value": ""}]
    assert client.put("/api/settings/mcp/servers/docs", json=edit).status_code == 200
    client.put("/api/settings/mcp", json={"values": {"external_servers": ["docs"]}})
    tool = external_mcp.discover(["docs"])[0]
    assert external_mcp.call(tool, {"query": "x"})["structured_content"]["configured"] == SECRET
    edit["env"] = [{"key": "NEW_KEY", "value": ""}]
    assert client.put("/api/settings/mcp/servers/docs", json=edit).status_code == 400


@pytest.mark.parametrize("transport", ["http", "sse"])
def test_remote_server_definitions_store_url_and_encrypt_headers(client, editing, transport):
    remote = {"name": "public_docs", "transport": transport, "url": "https://example.com/mcp",
              "env": [{"key": "Authorization", "value": "Bearer test-secret"}]}
    assert client.post("/api/settings/mcp/servers", json=remote).status_code == 200
    stored = store.get_setting(external_mcp.STORE_KEY)["value"]
    assert "test-secret" not in stored
    listed = client.get("/api/settings/mcp/servers").json()["servers"][0]
    assert listed["transport"] == transport and listed["url"] == remote["url"]
    assert listed["env_keys"] == ["Authorization"]
    server = external_mcp._all_servers()[0]
    assert server.url == remote["url"] and server.transport == transport
    assert server.env["Authorization"] == "Bearer test-secret"


def test_remote_server_requires_http_url_and_rejects_embedded_credentials(client, editing):
    base = {"name": "remote", "transport": "http", "env": []}
    assert client.post("/api/settings/mcp/servers", json={**base, "url": "file:///tmp/mcp"}).status_code == 400
    assert client.post("/api/settings/mcp/servers", json={**base, "url": "https://user:pass@example.com/mcp"}).status_code == 400


def test_mcp_headers_can_be_supplied_as_masked_model_placeholders():
    from app.copilot.redact import Redactor

    red = Redactor(False)
    masked = red.to_model("Authorization: Bearer private-token-123456")
    assert "private-token-123456" not in masked
    restored = red.obj_from_model({"headers": [{"name": "Authorization", "value": "Bearer <secret_1>"}]})
    assert restored["headers"][0]["value"] == "Bearer private-token-123456"
    assert "private-token-123456" not in red.safe_to_store("Authorization: Bearer private-token-123456")


@pytest.mark.parametrize("change,message", [
    ({"name": "Bad Name!"}, "Name must"),
    ({"command": ""}, "Enter the command"),
    ({"command": "definitely-not-a-real-program"}, "not found"),
    ({"command": "relative/path"}, "absolute path"),
    ({"cwd": "/no/such/folder"}, "Working directory"),
    ({"env": [{"key": "1BAD", "value": "x"}]}, "valid environment variable"),
])
def test_validation_errors_are_clear(client, editing, change, message):
    r = client.post("/api/settings/mcp/servers", json={**body(), **change})
    assert r.status_code == 400 and message in r.json()["detail"]
    assert client.post("/api/settings/mcp/servers/test", json={**body(), **change}).status_code == 400


def test_names_must_be_unique_across_environment_and_ui(client, editing, monkeypatch):
    env_def = [{"name": "corp", "command": sys.executable, "args": [str(FIXTURE)], "env": {}, "cwd": None}]
    monkeypatch.setenv("PORTAGE_EXTERNAL_MCP_SERVERS", json.dumps(env_def))
    assert client.post("/api/settings/mcp/servers", json=body("corp")).status_code == 400
    assert client.post("/api/settings/mcp/servers", json=body("docs")).status_code == 200
    assert client.post("/api/settings/mcp/servers", json=body("docs")).status_code == 400
    view = client.get("/api/settings/mcp/servers").json()
    corp = next(s for s in view["servers"] if s["name"] == "corp")
    assert corp == {"name": "corp", "source": "environment"}          # command and args are never exposed
    assert client.put("/api/settings/mcp/servers/corp", json=body("corp")).status_code == 400
    assert client.delete("/api/settings/mcp/servers/corp").status_code == 404


def test_name_cannot_change_and_limit_is_enforced(client, editing):
    client.post("/api/settings/mcp/servers", json=body("docs"))
    assert client.put("/api/settings/mcp/servers/docs", json=body("other")).status_code == 400
    for i in range(external_mcp.MAX_SERVERS - 1):
        assert client.post("/api/settings/mcp/servers", json=body(f"s{i}")).status_code == 200
    assert client.post("/api/settings/mcp/servers", json=body("one-too-many")).status_code == 400


def test_removing_a_server_keeps_other_selections(client, editing):
    client.post("/api/settings/mcp/servers", json=body("docs", enable_for_sora=True))
    client.post("/api/settings/mcp/servers", json=body("jira", enable_for_sora=True))
    assert client.get("/api/settings/mcp/servers").json()["enabled_for_sora"] == ["docs", "jira"]
    assert client.delete("/api/settings/mcp/servers/docs").json()["enabled_for_sora"] == ["jira"]


def test_unavailable_server_reports_a_friendly_error(client, editing):
    r = client.post("/api/settings/mcp/servers/test", json={**body(), "args": ["-c", "raise SystemExit(3)"]}).json()
    assert r["status"] == "unavailable" and r["error"]


def test_external_servers_field_is_hidden_from_generic_form(client):
    mcp = next(s for s in client.get("/api/settings").json()["sections"] if s["key"] == "mcp")
    assert next(f for f in mcp["fields"] if f["key"] == "external_servers")["hidden"] is True


def test_editing_follows_sign_in_and_can_be_forced_off(monkeypatch):
    monkeypatch.delenv(external_mcp.EDIT_FLAG, raising=False)
    monkeypatch.setenv("PORTAGE_AUTH_DISABLED", "1")
    assert external_mcp.editing_enabled() is False
    monkeypatch.delenv("PORTAGE_AUTH_DISABLED")
    assert external_mcp.editing_enabled() is True
    monkeypatch.setenv(external_mcp.EDIT_FLAG, "0")
    assert external_mcp.editing_enabled() is False
