"""Opt-in checks against the real local model (PORTAGE_LIVE_LLM=1). A small model is non-deterministic,
so each scenario gets up to three attempts; the safety properties (no duplicate/invalid name saved) must always hold."""
import os

import pytest

from app import store
from app.copilot import agent
from app.copilot.llm import OllamaClient
from app.copilot import settings as cfg

pytestmark = pytest.mark.skipif(os.environ.get("PORTAGE_LIVE_LLM") != "1", reason="set PORTAGE_LIVE_LLM=1 to run")

PAGE = {"route": "/mapping"}


def ask(message, attempts=3):
    last = []
    for _ in range(attempts):
        events = list(agent.run_chat(message, "", PAGE))
        last = events
        if any(e["type"] == "proposal" for e in events):
            break
    return last


def proposals(events):
    return [e["proposal"] for e in events if e["type"] == "proposal"]


@pytest.fixture(scope="module", autouse=True)
def require_model():
    store.init_db()
    h = OllamaClient(cfg.get()["base_url"], cfg.get()["model"]).health()
    if not (h["reachable"] and h["model_available"]):
        pytest.skip("Ollama or model unavailable")


@pytest.mark.parametrize("message,expected", [
    ("On the User Story mapping, map Rally Iteration to the Jira sprint field and save it as jira_us_mapping_v5", "jira_us_mapping_v5"),
    ("For Defect, map Iteration to the sprint field. Name the new version v6.", "jira_defect_mapping_v6"),
    ("Map Iteration to sprint for User Story and call the version Q4 sprint fix", "Q4 sprint fix"),
    ("Map Iteration to sprint for User Story", "jira_us_mapping_v1"),
])
def test_real_model_honours_the_requested_version_name(message, expected):
    events = ask(message)
    ps = proposals(events)
    assert ps, [e for e in events if e["type"] in ("tool_call", "tool_result", "error")]
    assert ps[0]["preview"]["new_name"] == expected
    assert store.list_mappings() == []                                  # proposing never saves


def test_real_model_never_saves_a_duplicate_name():
    store.save_mapping({"name": "jira_us_mapping_v5", "profiles": {}, "field_maps": []})
    events = ask("On the User Story mapping, map Iteration to sprint and save it as jira_us_mapping_v5")
    for p in proposals(events):
        assert p["preview"]["new_name"] != "jira_us_mapping_v5"
    assert [m["name"] for m in store.list_mappings()] == ["jira_us_mapping_v5"]
