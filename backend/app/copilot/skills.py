"""Skills: focused personas with their own instructions and tool subsets."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Skill:
    key: str
    label: str
    summary: str
    instructions: str
    tools: Optional[Tuple[str, ...]]     # None = every tool
    keywords: Tuple[str, ...] = ()
    routes: Tuple[str, ...] = ()
    suggestions: Tuple[str, ...] = ()


SKILLS: Dict[str, Skill] = {s.key: s for s in [
    Skill("mapping", "Mapping Architect", "Edit field mappings and save new versions.",
          "You specialise in Rally-to-Jira field mappings. Mapping edits are saved as a NEW version "
          "(jira_<artifact>_mapping_vN); the old version is never overwritten. When the user asks for a change, call "
          "propose_mapping_edit right away instead of describing what you would do: it validates field names itself and "
          "tells you the valid ones if something is wrong. Use get_mapping or list_mapping_fields only when you truly need "
          "to look something up, and after looking, still call propose_mapping_edit. "
          "If the user names no base version, use the latest saved mapping for that artifact (list_mappings). "
          "If the user gives a name for the new version (for example 'save as jira_us_mapping_v5' or 'call it v5'), "
          "pass it unchanged as version_name; otherwise leave version_name out.",
          ("list_mappings", "get_mapping", "compare_mappings", "list_mapping_fields", "propose_mapping_edit",
           "list_sources", "describe_source", "search_docs"),
          ("mapping", "map ", "field", "transform", "fallback", "story point", "artifact", "version of the mapping", "coalesce"),
          ("/mapping",),
          ("Show the latest User Story mapping", "Map Rally Iteration to the Jira sprint field for User Story",
           "What changed between my last two mapping versions?")),
    Skill("catalog", "Catalog Curator", "Maintain sprint, version, user and team catalogs.",
          "You specialise in the Jira Catalog (sprint, version, user, team). Source = Rally value, target = Jira value. "
          "To add or change values call propose_catalog_upsert; to undo call list_catalog_versions then "
          "propose_catalog_restore. Use find_unmapped_values to detect gaps in an uploaded source file.",
          ("list_catalogs", "get_catalog_entries", "list_catalog_versions", "find_unmapped_values", "distinct_values",
           "list_sources", "describe_source", "propose_catalog_upsert", "propose_catalog_remove",
           "propose_catalog_restore", "search_docs"),
          ("catalog", "sprint", "fix version", "unmapped", "team", "user catalog", "lookup", "account id", "undo"),
          ("/lookups",),
          ("Which sprints in my latest upload are missing from the catalog?", "Add Sprint 24 with Jira ID 1042 to the sprint catalog",
           "Undo the last change to the team catalog")),
    Skill("migration", "Migration Operator", "Inspect jobs, failures and readiness.",
          "You specialise in migration runs. Use list_jobs and get_job to explain results and failures, and "
          "find_unmapped_values to explain missing catalog values. You cannot start a migration; tell the user to use "
          "the Migrate page.",
          ("list_jobs", "get_job", "list_sources", "describe_source", "find_unmapped_values", "list_mappings",
           "connection_status", "search_docs"),
          ("job", "migrat", "failed", "error", "dry run", "dry-run", "preview", "export", "attachment", "why did"),
          ("/migrate", "/reports", "/exports", "/attachments", "/"),
          ("Why did my last migration fail?", "Summarise my recent jobs", "Is my Jira connection configured?")),
    Skill("guide", "Guide", "Explain how Portage works.",
          "You explain how Portage works. Call search_docs and base your answer on what it returns.",
          ("search_docs", "connection_status", "list_mappings", "list_catalogs"),
          ("how do", "how to", "what is", "explain", "help", "where"),
          ("/connections",),
          ("How do mapping versions work?", "What does a catalog do during migration?")),
    Skill("general", "Sora", "General assistant.",
          "You can use any tool. Pick the simplest tool that answers the question.", None),
]}


def pick_skill(message: str, route: str, explicit: str = "") -> Skill:
    m = re.match(r"\s*@(\w+)", message or "")
    key = (explicit or (m.group(1).lower() if m else "")).lower()
    if key in SKILLS:
        return SKILLS[key]
    text = (message or "").lower()
    best, best_score = SKILLS["general"], 0
    for s in SKILLS.values():
        if s.key == "general":
            continue
        score = sum(2 for k in s.keywords if k in text)
        if route in s.routes and route != "/":
            score += 1
        if score > best_score:
            best, best_score = s, score
    return best


def suggestions_for(route: str) -> List[str]:
    for s in SKILLS.values():
        if route in s.routes and route != "/":
            return list(s.suggestions)
    return list(SKILLS["migration"].suggestions) + list(SKILLS["guide"].suggestions[:1])
