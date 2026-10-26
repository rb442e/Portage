"""Dry-run the demo prompts through the real chat endpoint and print what Sora does."""
import json
import sys
import time

import requests

BASE = "http://127.0.0.1:8130/api/copilot"


def ask(message, route, attachments=(), conv="", extra_page=None):
    page = {"route": route, **(extra_page or {})}
    t = time.time()
    text, steps, proposals = "", [], []
    with requests.post(f"{BASE}/chat", json={"message": message, "conversation_id": conv, "attachments": list(attachments), "page": page},
                       stream=True, timeout=300) as r:
        for line in r.iter_lines():
            if not line.startswith(b"data: "):
                continue
            e = json.loads(line[6:])
            if e["type"] == "tool_call":
                steps.append(f"{e['name']}({json.dumps(e['args'])[:110]})")
            elif e["type"] == "tool_result":
                steps.append(f"  -> {'ok' if e['ok'] else 'FAIL'}: {e['summary'][:90]}")
            elif e["type"] == "proposal":
                proposals.append(e["proposal"]["preview"]["summary"])
            elif e["type"] == "token":
                text += e["text"]
            elif e["type"] == "error":
                steps.append("ERROR " + e["message"])
            elif e["type"] == "meta":
                conv = e["conversation_id"]
    print(f"\n=== [{time.time() - t:.0f}s] {message}")
    for s in steps:
        print("  ", s)
    for p in proposals:
        print("   PROPOSAL:", p)
    print("   ANSWER:", text.strip()[:600])
    return conv


which = sys.argv[1] if len(sys.argv) > 1 else "all"
if which in ("all", "unmapped"):
    ask("Which sprints in my latest upload are missing from the sprint catalog?", "/lookups", extra_page={"lookup_kind": "sprint"})
if which in ("all", "why"):
    ask("Why did my last migration fail?", "/reports")
if which in ("all", "lineage"):
    ask("@lineage Which Rally fields feed the sprint field for User Story?", "/mapping", extra_page={"artifact": "User Story"})
if which in ("all", "shot"):
    up = requests.post(f"{BASE}/attachments", files={"file": ("new_users.png", open(sys.argv[2] if len(sys.argv) > 2 else "new_users.png", "rb"), "image/png")}).json()
    ask("Add these new users to the user catalog", "/lookups", [up["id"]], extra_page={"lookup_kind": "user"})
