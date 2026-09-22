import io
import requests
import pandas as pd

B = "http://localhost:8000/api"
ROOT = "/Users/a112932/Documents/projects/agents/jira_project/Jira_migration_scripts/portage"
M = f"{ROOT}/mappings"


def entries(csv, k, v):
    df = pd.read_csv(csv, dtype=str, keep_default_na=False)
    out = {}
    for _, r in df.iterrows():
        a, b = str(r[k]).strip(), str(r[v]).strip()
        if a and b:
            out.setdefault(a, b)
    return out


specs = {
    "sprint": (f"{M}/sprint_mapping.csv", "Iteration", "Jira Id"),
    "team": (f"{M}/team_mapping.csv", "Team Name", "Atlassian Team ID"),
    "user": (f"{M}/user_mapping.csv", "Name", "Email"),
    "version": (f"{M}/version_mapping.csv", "Version Name", "Milestone ID"),
}

existing = requests.get(f"{B}/lookups").json()
for kind, (csv, ks, vs) in specs.items():
    ent = entries(csv, ks, vs)
    cur = next((l for l in existing if l["kind"] == kind), None)
    payload = {"id": cur["id"] if cur else None, "name": f"{kind} catalog",
               "kind": kind, "side": "rally_to_jira", "entries": ent}
    saved = requests.post(f"{B}/lookups", json=payload).json()
    print(f"{kind}: {len(saved['entries'])} entries e.g. {list(saved['entries'].items())[0]}")

# Live batch export
P = f"{ROOT}/Input_sample"
files = [("files", open(f"{P}/{n}", "rb")) for n in ("epics.csv", "features.csv", "userstories.csv", "defects.csv")]
items = requests.post(f"{B}/sources/upload-batch", files=files).json()["items"]
lookup_ids = [l["id"] for l in requests.get(f"{B}/lookups").json()]
body = {"files": [{"source_id": it["source_id"], "artifact_type": it["artifact_type"]} for it in items],
        "lookup_ids": lookup_ids}
ex = requests.post(f"{B}/migrations/export-batch", json=body).json()
csv = requests.get(f"{B}/migrations/exports/{ex['export_id']}/jira_all_issues.csv").text
d = pd.read_csv(io.StringIO(csv), dtype=str, keep_default_na=False)
email = lambda c: int(d[c].str.contains("@", regex=False).sum())
print("\nrows:", len(d), "Assignee emails:", email("Assignee"), "Reporter emails:", email("Reporter"),
      "Team set:", int((d["Team"] != "").sum()))
fv = d[d["Fix Version/s"] != ""]
print("Fix Version/s populated:", len(fv))
print("sample Fix Version/s:", fv["Fix Version/s"].head(5).tolist())
