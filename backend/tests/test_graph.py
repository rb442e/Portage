"""GraphRAG: graph construction, retrieval, overview and the registry tools."""
import json

from app import store
from app.config import settings
from app.copilot import graph
from app.copilot.tools import REGISTRY, ToolContext, apply_proposal, execute

CTX = ToolContext(conversation_id="graph")


def _apply(tool, args):
    res, proposal = execute(REGISTRY[tool], CTX, args)
    assert proposal, res
    return apply_proposal(proposal)


def _seed():
    v1 = _apply("propose_mapping_edit", {"artifact": "User Story", "version_name": "v1",
                "operations": [{"action": "set", "target": "sprint", "sources": ["Iteration"]}]})
    v2 = _apply("propose_mapping_edit", {"artifact": "User Story", "base_mapping_id": v1["id"],
                "operations": [{"action": "set", "target": "team", "sources": ["Team", "Owner"]}]})
    _apply("propose_catalog_upsert", {"kind": "sprint", "entries": [{"source": "Sprint 24", "target": "1042"}]})
    _apply("propose_catalog_upsert", {"kind": "sprint", "entries": [{"source": "Sprint 25", "target": "1043"}]})
    store.upsert_job("job1", "done", {
        "job_id": "job1", "state": "done", "total": 3, "created": 1, "failed": 2, "started_at": "now",
        "items": [{"external_id": "US1", "status": "failed", "message": "Sprint 77 not found in the sprint catalog"},
                  {"external_id": "US2", "status": "failed", "message": "Sprint 78 not found in the sprint catalog"},
                  {"external_id": "US3", "status": "created", "message": ""}]})
    (settings.upload_dir / ("a" * 32 + ".csv")).write_text("Iteration,Team,Name\nSprint 24,Alpha,x\n", encoding="utf-8")
    return v1, v2


def test_build_links_lineage_versions_and_catalogs():
    v1, v2 = _seed()
    g = graph.build()
    # Rally -> Jira lineage, per artifact
    feeds = g.edges[("rally_field:User Story:Iteration", "feeds", "jira_field:User Story:sprint")]
    assert feeds.props["mappings"]
    # the newer version supersedes the older one
    assert (f"mapping:{v2['id']}", "supersedes", f"mapping:{v1['id']}") in g.edges
    # a fallback mapping lists both sources
    pop = g.edges[(f"mapping:{v2['id']}", "populates", "jira_field:User Story:team")]
    assert pop.props["sources"] == ["Team", "Owner"]
    # sprint catalog translates the Jira sprint field and has copilot-authored history
    cat = g.of_type("catalog")[0]
    assert ("%s" % cat.id, "translates", "jira_field:User Story:sprint") in g.edges
    assert {v.props["author"] for v in g.related(cat.id, "has_version")} == {"copilot"}
    # uploaded column links to the catalog it depends on
    assert (("column:iteration"), "needs_catalog", cat.id) in g.edges


def test_job_errors_are_clustered_and_linked_to_the_catalog():
    _seed()
    g = graph.build()
    (err,) = g.of_type("error")
    assert err.props["occurrences"] == 2                       # "Sprint 77/78" collapse into one cluster
    assert {n.type for n in g.related(err.id, "mentions")} == {"catalog", "jira_field"}


def test_search_returns_multi_hop_context_and_docs():
    _seed()
    out = graph.search("which Rally fields feed the sprint field for User Story")
    text = json.dumps(out)
    assert any("sprint (User Story)" in s for s in out["seeds"] + out["nodes"])
    assert "Iteration (User Story) --feeds--> jira_field:sprint (User Story)" in text
    assert out["docs"] and out["stats"]["graph_nodes"] > 5
    assert len(text) < 6000                                    # fits the agent's tool-result budget


def test_search_follows_error_to_catalog_and_back_to_entries():
    _seed()
    out = graph.search("why did my sprint migration fail", depth=3)
    rels = "\n".join(out["relationships"])
    assert "error:" in rels and "--mentions-->" in rels


def test_search_with_no_match_still_answers_safely():
    out = graph.search("zzzz qqqq")
    assert out["seeds"] == [] and out["relationships"] == []


def test_overview_summarises_communities():
    v1, v2 = _seed()
    o = graph.overview()
    story = next(a for a in o["artifacts"] if a["artifact"] == "User Story")
    assert story["mapping_versions"] == 2 and story["latest"] == store.get_mapping(v2["id"])["name"]
    assert o["catalogs"][0]["entries"] == 2 and o["catalogs"][0]["last_change_by"] == "copilot"
    assert o["jobs"]["by_state"] == {"done": 1} and o["jobs"]["top_errors"][0]["occurrences"] == 2


def test_graph_tools_are_read_only_registry_tools():
    assert REGISTRY["graph_search"].risk == "read" and REGISTRY["graph_overview"].risk == "read"
    res, proposal = execute(REGISTRY["graph_search"], CTX, {"query": "sprint", "depth": "2"})
    assert proposal is None and "seeds" in res
    res, _ = execute(REGISTRY["graph_search"], CTX, {"query": "sprint", "depth": 9})
    assert "error" in res                                      # depth is bounded
    assert store.list_proposals("graph") == []                 # reading never creates proposals
