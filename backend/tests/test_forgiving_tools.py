"""Tool behaviour that small local models depend on: forgiving inputs, grouped failures, plain-English lineage."""
from app import store
from app.config import settings
from app.copilot import graph
from app.copilot.tools import REGISTRY, ToolContext, apply_proposal, execute

CTX = ToolContext(conversation_id="forgiving")


def run(tool, args):
    return execute(REGISTRY[tool], CTX, args)[0]


def seed_upload():
    sid = "b" * 32
    (settings.upload_dir / f"{sid}.csv").write_text(
        "Formatted ID,Iteration,Owner\nUS1,Sprint 23,A\nUS2,Sprint 25,B\nUS3,Sprint 25,C\nUS4,Sprint 26,D\n", encoding="utf-8")
    store.save_lookup({"name": "Sprint catalog", "kind": "sprint", "entries": {"Sprint 23": "1023"}})
    return sid


def test_unmapped_values_recovers_from_a_guessed_column_name():
    seed_upload()
    for guess in ("sprint", "Sprint", "nonsense", None):
        res = run("find_unmapped_values", {"kind": "sprint", "column": guess, "source_id": "latest"})
        assert "error" not in res, (guess, res)
        assert res["columns"] == ["Iteration"] and res["unmapped_total"] == 2
        assert {u["value"]: u["count"] for u in res["unmapped"]} == {"Sprint 25": 2, "Sprint 26": 1}
    assert "does not exist" in run("find_unmapped_values", {"kind": "sprint", "column": "sprint"})["note"]
    assert run("find_unmapped_values", {"kind": "sprint", "column": "iteration"})["columns"] == ["Iteration"]  # case-insensitive


def test_unmapped_values_still_errors_when_no_column_fits():
    (settings.upload_dir / ("c" * 32 + ".csv")).write_text("Name,Notes\nx,y\n", encoding="utf-8")
    assert "No suitable column" in run("find_unmapped_values", {"kind": "team", "source_id": "c" * 32})["error"]


def seed_job():
    store.upsert_job("job-aaa", "done", {
        "job_id": "job-aaa", "state": "done", "total": 4, "created": 1, "failed": 3, "started_at": "x",
        "items": [{"external_id": "US2", "status": "failed", "message": "Sprint 25 not found in the sprint catalog"},
                  {"external_id": "US3", "status": "failed", "message": "Sprint 25 not found in the sprint catalog"},
                  {"external_id": "US4", "status": "failed", "message": "Sprint 26 not found in the sprint catalog"},
                  {"external_id": "US1", "status": "created", "jira_key": "PAY-1", "message": ""}]})


def test_get_job_defaults_to_the_latest_run_and_groups_failure_causes():
    seed_job()
    for args in ({}, {"job_id": None}, {"job_id": "null"}):
        res = run("get_job", args)
        assert res["job_id"] == "job-aaa" and res["failed"] == 3, args
    cause = res["failure_causes"][0]
    assert cause["pattern"] == "Sprint # not found in the sprint catalog" and cause["count"] == 3     # one cause, not three
    assert cause["examples"][0].startswith("US")


def test_get_job_with_a_wrong_id_lists_real_ids_and_with_no_jobs_says_so():
    assert "no migration jobs" in run("get_job", {})["error"]
    seed_job()
    err = run("get_job", {"job_id": "get_job"})["error"]
    assert "not found" in err and "job-aaa" in err


def test_lineage_facts_are_plain_english_and_never_call_a_catalog_a_rally_field():
    v1 = execute(REGISTRY["propose_mapping_edit"], CTX, {"artifact": "User Story", "version_name": "v1", "operations": [
        {"action": "set", "target": "sprint", "sources": ["Iteration"]}]})[1]
    apply_proposal(v1)
    store.save_lookup({"name": "Sprint catalog", "kind": "sprint", "entries": {"Sprint 23": "1023"}})
    seed_job()
    facts = graph.search("which Rally fields feed the sprint field for User Story")["facts"]
    text = "\n".join(facts)
    assert "Rally field 'Iteration' feeds Jira field 'sprint' (User Story)" in text and "jira_us_mapping_v1" in text
    assert "it is a catalog, not a Rally field" in text
    assert len(facts) <= 8
