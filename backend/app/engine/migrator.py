"""Migration orchestrator.

Given normalized issues + a live Jira connection, Portage:
  1. Orders issues so parents are created before children.
  2. Creates each work item via the Jira REST API (no CSV importer).
  3. Resolves parent links using an intra-batch row_id -> Jira key map.
  4. Adds issue links and uploads attachments (from URLs or live Rally fetch).

`preview()` performs the same planning with zero writes (dry run).
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from ..connectors.jira_client import JiraClient
from ..connectors.rally_client import RallyClient
from ..schemas import (JiraConnection, NormalizedIssue, PlannedIssue,
                       RallyConnection)
from .mapping import DEFAULT_TYPE_MAP, order_index

ProgressFn = Callable[[str, dict], None]

# Jira issue types that are sub-tasks (must be created with a `parent`).
_SUBTASK_TYPES = {"sub-task", "subtask"}


def _resolve_type(issue_type: str, type_map: Dict[str, str]) -> str:
    return type_map.get(issue_type) or DEFAULT_TYPE_MAP.get(issue_type) or issue_type or "Task"


def _sorted(issues: List[NormalizedIssue]) -> List[NormalizedIssue]:
    return sorted(issues, key=lambda i: order_index(i.issue_type))


class Migrator:
    def __init__(self, jira: JiraConnection, rally: Optional[RallyConnection],
                 type_map: Dict[str, str], include_attachments: bool = True):
        self.jira_conn = jira
        self.rally_conn = rally
        self.type_map = type_map or {}
        self.include_attachments = include_attachments

    # -- dry run -----------------------------------------------------------
    def preview(self, issues: List[NormalizedIssue]) -> List[PlannedIssue]:
        known_rows = {i.row_id for i in issues if i.row_id}
        planned: List[PlannedIssue] = []
        for issue in _sorted(issues):
            jtype = _resolve_type(issue.issue_type, self.type_map)
            warnings: List[str] = []
            if not issue.summary:
                warnings.append("missing summary")
            if issue.parent_row_id and issue.parent_row_id not in known_rows:
                warnings.append(f"parent '{issue.parent_row_id}' not found in this batch")
            if issue.assignee and "@" in issue.assignee and self.jira_conn.deployment == "cloud":
                warnings.append("assignee is an email; will resolve to accountId at run time")
            if issue.sprint and not self.jira_conn.sprint_field:
                warnings.append("sprint value present but no sprint_field configured")
            if issue.story_points is not None and not self.jira_conn.story_points_field:
                warnings.append("story points present but no story_points_field configured")
            planned.append(PlannedIssue(
                external_id=issue.external_id,
                parent_external_id=issue.parent_row_id,
                jira_issue_type=jtype,
                summary=issue.summary,
                warnings=warnings,
                fields_preview={
                    "priority": issue.priority,
                    "labels": issue.labels,
                    "components": issue.components,
                    "sprint": issue.sprint,
                    "team": issue.team,
                    "story_points": issue.story_points,
                    "attachments": len(issue.attachments),
                },
            ))
        return planned

    # -- live run ----------------------------------------------------------
    def run(self, issues: List[NormalizedIssue], progress: ProgressFn) -> Dict[str, dict]:
        jira = JiraClient(self.jira_conn)
        rally = RallyClient(self.rally_conn) if self.rally_conn and self.rally_conn.api_key else None

        row_to_key: Dict[str, str] = {}
        account_cache: Dict[str, str] = {}
        results: Dict[str, dict] = {}

        ordered = _sorted(issues)
        total = len(ordered)
        for idx, issue in enumerate(ordered, start=1):
            ident = issue.row_id or issue.external_id or f"row-{idx}"
            jtype = _resolve_type(issue.issue_type, self.type_map)
            is_subtask = jtype.lower() in _SUBTASK_TYPES

            parent_key = ""
            if issue.parent_row_id:
                parent_key = row_to_key.get(issue.parent_row_id, "")

            assignee_id = ""
            if issue.assignee:
                if self.jira_conn.deployment == "cloud" and "@" in issue.assignee:
                    if issue.assignee not in account_cache:
                        account_cache[issue.assignee] = jira.account_id(issue.assignee) or ""
                    assignee_id = account_cache[issue.assignee]
                else:
                    assignee_id = issue.assignee

            fields = jira.build_fields(
                issue_type=jtype,
                summary=issue.summary,
                description=issue.description,
                priority=issue.priority,
                labels=issue.labels,
                components=issue.components,
                assignee_id=assignee_id,
                parent_key=parent_key,
                is_subtask=is_subtask,
                story_points=issue.story_points,
                sprint=issue.sprint,
                team=issue.team,
                fix_versions=issue.fix_versions,
                due_date=issue.due_date,
                external_id=issue.external_id,
            )
            key, err = jira.create_issue(fields)
            item = {"external_id": issue.external_id, "jira_key": key or "",
                    "status": "created" if key else "failed", "message": err,
                    "attachments_uploaded": 0}

            if key:
                if issue.row_id:
                    row_to_key[issue.row_id] = key
                # Issue links carried from the source.
                for link_key in issue.links:
                    target = row_to_key.get(link_key, link_key)
                    if target and target != key:
                        jira.link_issues(key, target)
                # Attachments (from URLs in the export or live Rally discovery).
                if self.include_attachments:
                    item["attachments_uploaded"] = self._attach(jira, rally, key, issue)
                    if item["attachments_uploaded"]:
                        item["status"] = "attached"
                progress("created", item)
            else:
                progress("failed", item)

            results[ident] = item
            progress("progress", {"done": idx, "total": total})
        return results

    def _attach(self, jira: JiraClient, rally: Optional[RallyClient],
                issue_key: str, issue: NormalizedIssue) -> int:
        existing = jira.existing_attachment_names(issue_key)
        uploaded = 0

        # 1) Direct URLs present in the source export.
        for att in issue.attachments:
            name = att.get("name") or "attachment"
            url = att.get("url") or ""
            if not url or name in existing:
                continue
            try:
                content = rally.download_url(url) if rally else _plain_download(url)
                if not jira.upload_attachment(issue_key, name, content):
                    uploaded += 1
                    existing.add(name)
            except Exception:  # noqa: BLE001 - recorded as a non-fatal skip
                continue

        # 2) Live Rally discovery when we have creds + a source id and no URLs.
        if rally and issue.external_id and not issue.attachments:
            try:
                for att in rally.discover_attachments(issue.external_id):
                    name = att.get("name") or "attachment"
                    ref = att.get("content_ref") or ""
                    if not ref or name in existing:
                        continue
                    content = rally.download(ref)
                    if not jira.upload_attachment(issue_key, name, content):
                        uploaded += 1
                        existing.add(name)
            except Exception:  # noqa: BLE001
                pass
        return uploaded


def _plain_download(url: str) -> bytes:
    import requests

    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content
