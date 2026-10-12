"""Chat-level behaviour: a user-given version name flows from the message through the model to the saved version."""
import json

import pytest

from app import store
from app.copilot import agent


class ScriptedLLM:
    """Replays a script of turns; each turn is a list of events or a callable(messages) -> events."""
    script: list = []
    calls: list = []

    def __init__(self, *a, **k):
        pass

    def chat_stream(self, messages, tools):
        ScriptedLLM.calls.append({"messages": json.loads(json.dumps(messages)), "tools": tools})
        turn = ScriptedLLM.script.pop(0)
        yield from (turn(messages) if callable(turn) else turn)


def call(**args):
    base = {"artifact": "User Story", "operations": [{"action": "set", "target": "sprint", "sources": ["Iteration"]}]}
    return [{"type": "tool_calls", "calls": [{"name": "propose_mapping_edit", "arguments": {**base, **args}}]}]


def say(text):
    return [{"type": "token", "text": text}]


@pytest.fixture()
def llm(monkeypatch):
    monkeypatch.setattr(agent, "OllamaClient", ScriptedLLM)
    ScriptedLLM.script, ScriptedLLM.calls = [], []
    return ScriptedLLM


def chat(message, route="/mapping", **page):
    return list(agent.run_chat(message, "", {"route": route, **page}))


def proposals(events):
    return [e["proposal"] for e in events if e["type"] == "proposal"]


def test_prompt_and_tool_schema_teach_the_model_about_version_names(llm):
    llm.script = [say("ok")]
    chat("hello @mapping")
    sent = llm.calls[0]
    system = sent["messages"][0]["content"]
    assert "version_name" in system and "jira_us_mapping_v5" in system
    tool = next(t for t in sent["tools"] if t["function"]["name"] == "propose_mapping_edit")
    props = tool["function"]["parameters"]["properties"]
    assert "version_name" in props and "jira_us_mapping_v5" in props["version_name"]["description"]
    assert "version_name" not in tool["function"]["parameters"]["required"]  # optional


def test_name_given_in_chat_becomes_the_saved_version_name(llm, client):
    llm.script = [call(version_name="jira_us_mapping_v5"), say("Proposed jira_us_mapping_v5.")]
    events = chat("On the User Story mapping, map Iteration to sprint and save it as jira_us_mapping_v5")

    p = proposals(events)[0]
    assert p["preview"]["new_name"] == "jira_us_mapping_v5" and p["status"] == "pending"
    assert [e for e in events if e["type"] == "tool_result"][0]["ok"] is True
    assert store.list_mappings() == []                                  # still nothing saved

    res = client.post(f"/api/copilot/proposals/{p['id']}/apply").json()
    assert res["result"]["name"] == "jira_us_mapping_v5"
    assert [m["name"] for m in store.list_mappings()] == ["jira_us_mapping_v5"]


def test_no_name_in_chat_means_auto_numbering(llm, client):
    store.save_mapping({"name": "jira_us_mapping_v4", "profiles": {}, "field_maps": []})
    llm.script = [call(), say("done")]
    p = proposals(chat("map Iteration to sprint for user stories"))[0]
    assert p["preview"]["new_name"] == "jira_us_mapping_v5"
    assert client.post(f"/api/copilot/proposals/{p['id']}/apply").json()["result"]["name"] == "jira_us_mapping_v5"


def test_model_recovers_after_a_name_collision(llm):
    store.save_mapping({"name": "jira_us_mapping_v9", "profiles": {}, "field_maps": []})

    def retry(messages):
        tool_msg = messages[-1]
        assert tool_msg["role"] == "tool" and "already exists" in tool_msg["content"]
        assert "jira_us_mapping_v10" in tool_msg["content"]             # the fix the model needs is in the error
        return call(version_name="jira_us_mapping_v10")

    llm.script = [call(version_name="jira_us_mapping_v9"), retry, say("Saved as v10 instead.")]
    events = chat("map Iteration to sprint, save as jira_us_mapping_v9")

    results = [e for e in events if e["type"] == "tool_result"]
    assert [r["ok"] for r in results] == [False, True]
    assert proposals(events)[0]["preview"]["new_name"] == "jira_us_mapping_v10"
    assert len(store.list_mappings()) == 1                                # nothing written by either attempt


def test_invalid_name_is_reported_back_and_nothing_is_created(llm):
    llm.script = [call(version_name="../../evil"), say("That name is not allowed.")]
    events = chat("save as ../../evil")
    assert proposals(events) == []
    res = [e for e in events if e["type"] == "tool_result"][0]
    assert res["ok"] is False and "Version name may use" in res["summary"]
    assert store.list_mappings() == []


def test_model_sending_nested_args_as_strings_and_null_name_still_works(llm):
    ops = json.dumps([{"action": "set", "target": "sprint", "sources": ["Iteration"]}])
    llm.script = [call(operations=ops, version_name="null"), say("ok")]
    p = proposals(chat("map iteration to sprint"))[0]
    assert p["preview"]["new_name"] == "jira_us_mapping_v1"             # "null" is treated as omitted


def test_page_context_selects_the_mapping_skill_and_base_version(llm):
    llm.script = [say("hi")]
    events = chat("add sprint mapping", route="/mapping", mapping_id=3, artifact="User Story")
    assert events[0]["skill"]["key"] == "mapping"
    system = llm.calls[0]["messages"][0]["content"]
    assert "selected mapping id: 3" in system and "artifact: User Story" in system


def test_readonly_mode_never_offers_the_edit_tool(llm, client):
    client.put("/api/copilot/settings", json={"mode": "readonly"})
    llm.script = [say("I can only read.")]
    chat("save as v5")
    offered = [t["function"]["name"] for t in llm.calls[0]["tools"]]
    assert "propose_mapping_edit" not in offered and "get_mapping" in offered
    client.put("/api/copilot/settings", json={"mode": "propose"})


def test_hallucinated_tool_in_readonly_mode_is_refused(llm, client):
    client.put("/api/copilot/settings", json={"mode": "readonly"})
    llm.script = [call(version_name="v5"), say("blocked")]
    events = chat("save as v5")
    res = [e for e in events if e["type"] == "tool_result"][0]
    assert res["ok"] is False and "unavailable" in res["summary"]
    assert proposals(events) == [] and store.list_mappings() == []
    client.put("/api/copilot/settings", json={"mode": "propose"})
