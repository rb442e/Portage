"""Copilot mapping edits: validation, user-chosen version names, immutability and engine-level effect."""
import json
import uuid

import pytest

from app import store
from app.config import settings
from app.copilot import agent
from app.copilot.tools import REGISTRY, ToolContext, _base_template, apply_proposal, execute
from app.engine.transform import transform_source

CTX = ToolContext(conversation_id="t-map")
SET_SPRINT = {"action": "set", "target": "sprint", "sources": ["Iteration"]}


def edit(artifact="User Story", ops=None, **kw):
    return execute(REGISTRY["propose_mapping_edit"], CTX,
                   {"artifact": artifact, "operations": ops or [SET_SPRINT], **kw})


def save(artifact="User Story", ops=None, **kw):
    res, p = edit(artifact, ops, **kw)
    assert p, res
    return apply_proposal(p)


def profile(mapping_id, artifact="User Story"):
    return {m["target"]: m for m in store.get_mapping(mapping_id)["profiles"][artifact]}


def mapping_names():
    return sorted(m["name"] for m in store.list_mappings())


# ---------------------------------------------------------------------------
# Version naming
# ---------------------------------------------------------------------------
def test_auto_names_increment_per_artifact():
    assert save()["name"] == "jira_us_mapping_v1"
    assert save()["name"] == "jira_us_mapping_v2"   # each edit starts from the defaults here, so it is effective again
    assert save("Epic", [SET_SPRINT])["name"] == "jira_epic_mapping_v1"
    assert save("Defect", [SET_SPRINT])["name"] == "jira_defect_mapping_v1"
    assert save()["name"] == "jira_us_mapping_v3"


@pytest.mark.parametrize("artifact,slug", [("Epic", "epic"), ("Feature", "feature"), ("User Story", "us"),
                                           ("Task", "task"), ("Defect", "defect")])
def test_slug_for_every_artifact(artifact, slug):
    assert save(artifact, [SET_SPRINT])["name"] == f"jira_{slug}_mapping_v1"


def test_user_supplied_full_name_is_used_verbatim():
    r = save(version_name="jira_us_mapping_v5")
    assert r["name"] == "jira_us_mapping_v5"
    saved = store.get_mapping(r["id"])
    assert saved["version"] == 5 and saved["name"] == "jira_us_mapping_v5"
    nxt = save(ops=[{"action": "set", "target": "team", "sources": ["Team", "Owner"]}], base_mapping_id=r["id"])
    assert nxt["name"] == "jira_us_mapping_v6"  # auto numbering continues after a user-chosen number


@pytest.mark.parametrize("given", ["v7", "V7", "7", " v7 "])
def test_shorthand_expands_per_artifact(given):
    assert save("Epic", [SET_SPRINT], version_name=given)["name"] == "jira_epic_mapping_v7"


def test_free_form_name_is_allowed_and_gets_next_number():
    r = save(version_name="Q4 sprint fix")
    saved = store.get_mapping(r["id"])
    assert saved["name"] == "Q4 sprint fix" and saved["version"] == 1


def test_blank_name_falls_back_to_auto():
    assert save(version_name="   ")["name"] == "jira_us_mapping_v1"


@pytest.mark.parametrize("bad", ["../etc/passwd", "a/b", "<script>alert(1)</script>", "x" * 81, "-leading", "semi;colon", "quote'name"])
def test_unsafe_or_malformed_names_are_rejected(bad):
    res, p = edit(version_name=bad)
    assert p is None and "Version name may use" in res["error"]
    assert store.list_mappings() == [] and store.list_proposals("t-map") == []


def test_name_for_a_different_artifact_is_rejected():
    res, p = edit("User Story", version_name="jira_epic_mapping_v3")
    assert p is None and "different artifact" in res["error"] and "jira_us_mapping_vN" in res["error"]


def test_duplicate_name_is_rejected_case_insensitively_and_suggests_next():
    save(version_name="jira_us_mapping_v3")
    res, p = edit(version_name="JIRA_US_MAPPING_V3".lower())
    assert p is None and "already exists" in res["error"] and "jira_us_mapping_v4" in res["error"]
    res, p = edit(version_name="3")
    assert p is None and "already exists" in res["error"]
    assert mapping_names() == ["jira_us_mapping_v3"]


def test_name_taken_between_proposal_and_apply_is_caught(client):
    _, p = edit(version_name="jira_us_mapping_v9")
    store.save_mapping({"name": "jira_us_mapping_v9", "profiles": {}, "field_maps": []})  # someone else saved it meanwhile
    r = client.post(f"/api/copilot/proposals/{p['id']}/apply")
    assert r.status_code == 422 and "already exists" in r.json()["detail"]
    assert store.get_proposal(p["id"])["status"] == "pending"
    assert mapping_names() == ["jira_us_mapping_v9"]  # nothing extra written


def test_plan_shows_the_chosen_name_and_writes_nothing():
    res, p = edit(version_name="jira_us_mapping_v5")
    assert res["status"] == "proposal_created"
    assert p["preview"]["new_name"] == "jira_us_mapping_v5" and "jira_us_mapping_v5" in p["preview"]["title"]
    assert store.list_mappings() == []


# ---------------------------------------------------------------------------
# Edit semantics
# ---------------------------------------------------------------------------
def test_set_new_target_and_diff_preview():
    res, p = edit()
    d = p["preview"]["diff"]["artifacts"]["User Story"]
    assert d["added"] == {"sprint": ["Iteration"]} and not d["removed"] and not d["changed"]
    r = apply_proposal(p)
    m = profile(r["id"])["sprint"]
    assert m["sources"] == ["Iteration"] and m["source"] == "Iteration" and m["target_type"] == "id" and m["transform"] == ""


def test_set_existing_target_replaces_sources_and_keeps_fallback_order():
    res, p = edit(ops=[{"action": "set", "target": "labels", "sources": ["Tags", "Team"]}])
    assert p["preview"]["diff"]["artifacts"]["User Story"]["changed"]["labels"] == {"from": ["Tags"], "to": ["Tags", "Team"]}
    m = profile(apply_proposal(p)["id"])["labels"]
    assert m["sources"] == ["Tags", "Team"] and m["transform"] == "labels"


@pytest.mark.parametrize("target,sources,transform", [
    ("due_date", ["Creation Date", "Planned End Date"], "date"),
    ("story_points", ["Plan Estimate", "Name"], "number"),
    ("labels", ["Tags", "Team"], "labels"),
    ("summary", ["Name", "Description"], ""),
])
def test_transform_follows_target_data_type(target, sources, transform):
    r = save(ops=[{"action": "set", "target": target, "sources": sources}], version_name="v2")
    assert profile(r["id"])[target]["transform"] == transform


def test_remove_mapping():
    res, p = edit(ops=[{"action": "remove", "target": "labels"}])
    assert p["preview"]["diff"]["artifacts"]["User Story"]["removed"] == {"labels": ["Tags"]}
    assert "labels" not in profile(apply_proposal(p)["id"])


def test_labels_and_case_are_resolved_to_canonical_keys():
    r = save(ops=[{"action": "set", "target": "Fix Version/s", "sources": ["iteration", "TAGS"]},
                  {"action": "set", "target": "STORY POINTS", "sources": ["plan estimate", "name"]}])
    prof = profile(r["id"])
    assert prof["fix_versions"]["sources"] == ["Iteration", "Tags"] and prof["story_points"]["sources"] == ["Plan Estimate", "Name"]


def test_other_artifacts_and_value_maps_are_untouched():
    base = _base_template(None)
    r = save()
    saved = store.get_mapping(r["id"])
    for art in ("Epic", "Feature", "Task", "Defect"):
        assert saved["profiles"][art] == base["profiles"][art]
    assert saved["value_maps"] == base["value_maps"]
    assert saved["description"].startswith("Edited by Sora")


def test_feature_edit_keeps_field_maps_in_sync():
    r = save("Feature", [{"action": "set", "target": "sprint", "sources": ["Iteration"]}])
    saved = store.get_mapping(r["id"])
    assert saved["field_maps"] == saved["profiles"]["Feature"]


@pytest.mark.parametrize("ops,fragment", [
    ([{"action": "set", "target": "nope", "sources": ["Name"]}], "Unknown target field"),
    ([{"action": "set", "target": "sprint", "sources": ["Nope Column"]}], "Unknown Rally column"),
    ([{"action": "set", "target": "sprint", "sources": []}], "at least one Rally source"),
    ([{"action": "remove", "target": "sprint"}], "nothing to remove"),
    ([{"action": "set", "target": "severity", "sources": ["Severity"]}], "Unknown target field"),  # Defect-only field on a Story
])
def test_invalid_operations_report_valid_options_and_create_nothing(ops, fragment):
    res, p = edit(ops=ops)
    assert p is None and fragment in res["error"]
    assert store.list_proposals("t-map") == [] and store.list_mappings() == []


def test_unknown_artifact_lists_valid_ones():
    res, p = edit("Initiative")
    assert p is None and "Valid:" in res["error"] and "User Story" in res["error"]


@pytest.mark.parametrize("alias,expected", [("story", "jira_us_mapping_v1"), ("bugs", "jira_defect_mapping_v1"), ("user_story", "jira_us_mapping_v1")])
def test_artifact_aliases(alias, expected):
    assert save(alias, [{"action": "set", "target": "sprint", "sources": ["Iteration"]}])["name"] == expected


def test_multi_operation_edit_is_atomic():
    ops = [SET_SPRINT, {"action": "set", "target": "bogus", "sources": ["Name"]}]
    res, p = edit(ops=ops)
    assert p is None and store.list_mappings() == []


def test_no_op_edit_is_rejected():
    first = save()
    res, p = edit(base_mapping_id=first["id"])  # sprint <- Iteration already there
    assert p is None and "No effective change" in res["error"]
    res, p = edit(ops=[{"action": "set", "target": "labels", "sources": ["Tags"]}])  # default already maps this
    assert p is None and "No effective change" in res["error"]


def test_empty_operations_and_bad_types_are_invalid_arguments():
    for args in ({"artifact": "Epic", "operations": []}, {"operations": [SET_SPRINT]},
                 {"artifact": "Epic", "operations": [{"action": "explode", "target": "x"}]}):
        res, p = execute(REGISTRY["propose_mapping_edit"], CTX, args)
        assert p is None and "Invalid arguments" in res["error"]


# ---------------------------------------------------------------------------
# Versioning guarantees
# ---------------------------------------------------------------------------
def test_old_versions_are_immutable_and_chain_carries_changes_forward():
    v1 = save(version_name="jira_us_mapping_v1")
    snapshot = json.dumps(store.get_mapping(v1["id"]), sort_keys=True)
    v2 = save(ops=[{"action": "set", "target": "team", "sources": ["Team", "Owner"]}],
              base_mapping_id=v1["id"], version_name="jira_us_mapping_v2")
    assert json.dumps(store.get_mapping(v1["id"]), sort_keys=True) == snapshot  # v1 untouched
    assert v2["id"] != v1["id"] and mapping_names() == ["jira_us_mapping_v1", "jira_us_mapping_v2"]
    assert "sprint" in profile(v2["id"]) and profile(v2["id"])["team"]["sources"] == ["Team", "Owner"]  # v1's edit carried forward
    assert "sprint" in profile(v1["id"]) and profile(v1["id"])["team"]["sources"] == ["Team"]


def test_deleted_base_between_proposal_and_apply(client):
    v1 = save()
    _, p = edit(ops=[{"action": "set", "target": "team", "sources": ["Team", "Owner"]}], base_mapping_id=v1["id"])
    store.delete_mapping(v1["id"])
    r = client.post(f"/api/copilot/proposals/{p['id']}/apply")
    assert r.status_code == 422 and "not found" in r.json()["detail"]


# ---------------------------------------------------------------------------
# API + engine validation of the saved version
# ---------------------------------------------------------------------------
RALLY_CSV = ("Formatted ID,Name,Description,Owner,Submitted By,State,Tags,Iteration,Team,Creation Date,"
             "Planned End Date,Parent Feature,Plan Estimate\n"
             "US1,Login page,desc,Jane Doe,Jane Doe,In-Progress,ui,Sprint 5,Team A,2024-01-02,2024-02-03,F1,3\n"
             "US2,Logout,desc,Jane Doe,Jane Doe,Defined,,Sprint 6,Team A,2024-01-02,2024-02-03,F1,5\n")


@pytest.fixture()
def rally_source():
    sid = uuid.uuid4().hex
    (settings.upload_dir / f"{sid}.csv").write_text(RALLY_CSV)
    return sid


def test_saved_version_through_api_roundtrip(client):
    _, p = edit(version_name="jira_us_mapping_v5", note="sprint for stories")
    r = client.post(f"/api/copilot/proposals/{p['id']}/apply")
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["name"] == "jira_us_mapping_v5" and body["result"]["refresh"] == ["mapping"]
    assert body["proposal"]["status"] == "applied"

    listed = client.get("/api/mappings").json()
    assert [m["name"] for m in listed] == ["jira_us_mapping_v5"]
    got = client.get(f"/api/mappings/{body['result']['id']}").json()   # validates against the MappingTemplate schema
    assert got["version"] == 5 and got["description"] == "Edited by Sora. sprint for stories"
    assert any(m["target"] == "sprint" and m["sources"] == ["Iteration"] for m in got["profiles"]["User Story"])

    code = client.post("/api/mappings/generate", json=got).json()      # the Studio's code generator accepts it
    assert "sprint" in code["code"] and "Iteration" in code["code"]

    audit = [a for a in client.get("/api/copilot/audit").json() if a["event"] == "mapping_saved"]
    assert audit and audit[0]["detail"]["name"] == "jira_us_mapping_v5"


def test_second_apply_and_apply_after_reject_conflict(client):
    _, p = edit()
    assert client.post(f"/api/copilot/proposals/{p['id']}/apply").status_code == 200
    assert client.post(f"/api/copilot/proposals/{p['id']}/apply").status_code == 409
    assert client.post(f"/api/copilot/proposals/{p['id']}/reject").status_code == 409
    assert len(store.list_mappings()) == 1
    _, q = edit(version_name="v8")
    assert client.post(f"/api/copilot/proposals/{q['id']}/reject").status_code == 200
    assert client.post(f"/api/copilot/proposals/{q['id']}/apply").status_code == 409
    assert len(store.list_mappings()) == 1


def test_readonly_mode_blocks_apply_and_hides_the_tool(client):
    _, p = edit()
    client.put("/api/copilot/settings", json={"mode": "readonly"})
    assert client.post(f"/api/copilot/proposals/{p['id']}/apply").status_code == 403
    assert store.list_mappings() == []
    assert "propose_mapping_edit" not in [t.name for t in agent._tools_for("mapping", "readonly")]
    assert "propose_mapping_edit" in [t.name for t in agent._tools_for("mapping", "propose")]


def test_version_diff_endpoint_reflects_the_edit(client):
    a = save(version_name="jira_us_mapping_v1")
    b = save(ops=[{"action": "set", "target": "labels", "sources": ["Tags", "Team"]}], base_mapping_id=a["id"], version_name="v2")
    d = client.get(f"/api/mappings/{a['id']}/diff/{b['id']}").json()
    assert d["from"] == "jira_us_mapping_v1" and d["to"] == "jira_us_mapping_v2"
    assert d["artifacts"]["User Story"]["changed"]["labels"] == {"from": ["Tags"], "to": ["Tags", "Team"]}
    assert d["summary"] == "1 change(s)"


def test_engine_applies_the_new_mapping_to_real_rows(rally_source):
    before = transform_source(settings.upload_dir / f"{rally_source}.csv", _base_template(None), force_type="User Story")
    assert [i.sprint for i in before] == ["", ""]                        # default mapping has no sprint

    r = save(version_name="jira_us_mapping_v5")
    after = transform_source(settings.upload_dir / f"{rally_source}.csv", store.get_mapping(r["id"]), force_type="User Story")
    assert [i.sprint for i in after] == ["Sprint 5", "Sprint 6"]
    assert [i.summary for i in after] == ["Login page", "Logout"]          # untouched fields still map
    assert [i.story_points for i in after] == [3.0, 5.0]
    assert [i.fix_versions for i in after] == [i.fix_versions for i in before]  # default Iteration -> fix_versions retained


def test_engine_honours_fallback_sources(rally_source):
    r = save(ops=[{"action": "set", "target": "team", "sources": ["Tags", "Team"]}], version_name="v3")
    issues = transform_source(settings.upload_dir / f"{rally_source}.csv", store.get_mapping(r["id"]), force_type="User Story")
    assert [i.team for i in issues] == ["ui", "Team A"]  # first non-empty source wins per row


def test_saved_version_works_in_migration_preview_and_export(client, rally_source):
    r = save(version_name="jira_us_mapping_v5")
    req = {"source_id": rally_source, "mapping_id": r["id"], "force_type": "User Story",
           "jira": {"base_url": "https://example.atlassian.net", "email": "a@b.co", "api_token": "x", "project_key": "P"}}
    prev = client.post("/api/migrations/preview", json=req)
    assert prev.status_code == 200 and prev.json()["total"] == 2 and prev.json()["by_type"] == {"Story": 2}

    exp = client.post("/api/migrations/export", json=req)
    assert exp.status_code == 200 and exp.json()["total"] == 2
    export_id = exp.json()["export_id"]
    csv_text = (settings.data_dir / "exports" / export_id / "jira_all_issues.csv").read_text()
    assert "Sprint 5" in csv_text and "Sprint 6" in csv_text


def test_lookup_catalog_still_applies_on_top_of_the_new_mapping(rally_source):
    lk = store.save_lookup({"name": "Sprints", "kind": "sprint", "entries": {"Sprint 5": "1005"}})
    from app.engine.mapping import merge_lookups
    r = save(version_name="jira_us_mapping_v5")
    tpl = merge_lookups(store.get_mapping(r["id"]), store.get_lookups([lk["id"]]))
    issues = transform_source(settings.upload_dir / f"{rally_source}.csv", tpl, force_type="User Story")
    assert issues[0].sprint == "1005"
