"""Regressions from live Sora calls to Parallel Web Fetch."""
import pytest

from app.copilot.external_mcp import ExternalMcpError, RemoteTool, normalize_arguments


def fetch_tool():
    return RemoteTool(
        "ext_parallel_search_mcp__web_fetch", "parallel_search_mcp", "web_fetch", "Read a URL",
        {"type": "object", "properties": {
            "urls": {"type": "array", "items": {"type": "string"}},
            "allow_live_fetch": {"type": "boolean"},
            "full_content": {"type": "boolean"},
            "session_id": {"type": "string"},
        }, "required": ["urls"]},
    )


def test_normalizes_captured_local_model_fetch_arguments():
    normalized = normalize_arguments(fetch_tool(), {
        "urls": "['https://modelcontextprotocol.org/docs/getting-started/intro']",
        "allow_live_fetch": "true", "full_content": "false",
        "session_id": "current Portage conversation identifier",
    }, session_id="conversation-123")
    assert normalized == {
        "urls": ["https://modelcontextprotocol.org/docs/getting-started/intro"],
        "allow_live_fetch": True, "full_content": False, "session_id": "conversation-123",
    }


@pytest.mark.parametrize("value", ["yes", "0", "anything", 1, []])
def test_rejects_ambiguous_boolean_values(value):
    with pytest.raises(ExternalMcpError, match="allow_live_fetch must be boolean"):
        normalize_arguments(fetch_tool(), {"urls": ["https://example.com"], "allow_live_fetch": value})
