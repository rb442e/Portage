"""Seeds a realistic demo workspace into PORTAGE_DATA_DIR (run with the backend venv, from backend/)."""
import json
import uuid

from app import store
from app.config import settings
from app.copilot.tools import REGISTRY, ToolContext, apply_proposal, execute

store.init_db()
ctx = ToolContext(conversation_id="seed")


def apply(tool, args):
    res, proposal = execute(REGISTRY[tool], ctx, args)
    assert proposal, res
    return apply_proposal(proposal)


v1 = apply("propose_mapping_edit", {"artifact": "User Story", "version_name": "v1",
           "operations": [{"action": "set", "target": "sprint", "sources": ["Iteration"]}]})
apply("propose_mapping_edit", {"artifact": "User Story", "base_mapping_id": v1["id"],
      "operations": [{"action": "set", "target": "team", "sources": ["Team", "Owner"]}]})

store.save_lookup({"name": "Sprint catalog", "kind": "sprint", "entries": {
    "Sprint 21": "1021", "Sprint 22": "1022", "Sprint 23": "1023", "Sprint 24": "1024"}}, author="user", message="Initial import")
store.save_lookup({"name": "Team catalog", "kind": "team", "entries": {
    "Payments Squad": "TEAM-11", "Platform Core": "TEAM-14", "Mobile Growth": "TEAM-17"}}, author="user", message="Initial import")
store.save_lookup({"name": "User catalog", "kind": "user", "entries": {
    "Priya Raman": "priya.raman@example.com", "Marcus Lee": "marcus.lee@example.com"}}, author="user", message="Initial import")

rows = [
    ("US1042", "Retry failed card payments", "Sprint 23", "Priya Raman", "Payments Squad", "Accepted", 5),
    ("US1043", "Export statements as PDF", "Sprint 24", "Marcus Lee", "Payments Squad", "In-Progress", 3),
    ("US1051", "Offline mode for mobile app", "Sprint 25", "Priya Raman", "Mobile Growth", "Defined", 8),
    ("US1052", "Push notification preferences", "Sprint 25", "Marcus Lee", "Mobile Growth", "In-Progress", 5),
    ("US1060", "Rate limiting on public API", "Sprint 26", "Marcus Lee", "Platform Core", "Defined", 8),
    ("US1061", "Audit log retention policy", "Sprint 26", "Priya Raman", "Platform Core", "Defined", 3),
    ("US1062", "SSO session timeout", "Sprint 24", "Priya Raman", "Platform Core", "Accepted", 2),
]
head = "Formatted ID,Name,Iteration,Owner,Team,State,Plan Estimate"
sid = uuid.uuid4().hex
(settings.upload_dir / f"{sid}.csv").write_text(head + "\n" + "\n".join(",".join(map(str, r)) for r in rows) + "\n", encoding="utf-8")

items = [{"external_id": r[0], "status": "failed", "message": f"{r[2]} not found in the sprint catalog"}
         for r in rows if r[2] in ("Sprint 25", "Sprint 26")]
items += [{"external_id": r[0], "jira_key": f"PAY-{200 + i}", "status": "created", "message": ""}
          for i, r in enumerate(rows) if r[2] not in ("Sprint 25", "Sprint 26")]
store.upsert_job("demo-run-0001", "done", {
    "job_id": "demo-run-0001", "state": "done", "dry_run": False, "migration_id": "MIG-0007", "total": len(rows),
    "created": 3, "failed": 4, "skipped": 0, "attachments_uploaded": 0, "progress": 100.0, "log": [],
    "items": items, "started_at": "2026-10-19T09:41:12+00:00", "finished_at": "2026-10-19T09:41:58+00:00"})
print("seeded", sid)
