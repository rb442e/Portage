"""Connection test endpoints for source (Rally) and target (Jira)."""
from __future__ import annotations

import json
from typing import List

from fastapi import APIRouter

from .. import secretbox, store
from ..connectors.jira_client import JiraClient
from ..connectors.rally_client import RallyClient
from ..schemas import (ConnectionTestRequest, ConnectionTestResult,
                       DiscoverRequest, JiraConnection, JiraMetaResult,
                       RallyConnection, SavedConnectionRequest,
                       SavedConnectionState)

router = APIRouter(prefix="/api/connections", tags=["connections"])

_SETTING_KEY = "connection_profile"


@router.post("/test", response_model=List[ConnectionTestResult])
def test_connections(req: ConnectionTestRequest) -> List[ConnectionTestResult]:
    results: List[ConnectionTestResult] = []
    if req.jira and req.jira.base_url:
        ok, detail, who = JiraClient(req.jira).test()
        results.append(ConnectionTestResult(system="jira", ok=ok, detail=detail, account=who))
    if req.rally and req.rally.api_key:
        ok, detail, who = RallyClient(req.rally).test()
        results.append(ConnectionTestResult(system="rally", ok=ok, detail=detail, account=who))
    return results


@router.post("/discover", response_model=JiraMetaResult)
def discover_jira(req: DiscoverRequest) -> JiraMetaResult:
    """Read the target's issue types + custom-field catalog and suggest IDs."""
    meta = JiraClient(req.jira).discover()
    return JiraMetaResult(**meta)


# ---------------------------------------------------------------------------
# Saved connection profile — persisted in the store with secrets encrypted at
# rest. Lets the API keys survive a browser reload without living in the browser.
# ---------------------------------------------------------------------------
@router.post("/save", response_model=SavedConnectionState)
def save_connections(req: SavedConnectionRequest) -> SavedConnectionState:
    jira = req.jira.model_dump()
    rally = req.rally.model_dump()
    jira["api_token"] = secretbox.encrypt(jira.get("api_token", ""))
    rally["api_key"] = secretbox.encrypt(rally.get("api_key", ""))
    store.set_setting(_SETTING_KEY, json.dumps({"jira": jira, "rally": rally}))
    row = store.get_setting(_SETTING_KEY)
    return SavedConnectionState(saved=True, saved_at=row["updated_at"] if row else "")


@router.get("/saved", response_model=SavedConnectionState)
def get_saved_connections() -> SavedConnectionState:
    row = store.get_setting(_SETTING_KEY)
    if not row:
        return SavedConnectionState(saved=False)
    data = json.loads(row["value"])
    jira = data.get("jira", {}) or {}
    rally = data.get("rally", {}) or {}
    jira["api_token"] = secretbox.decrypt(jira.get("api_token", ""))
    rally["api_key"] = secretbox.decrypt(rally.get("api_key", ""))
    return SavedConnectionState(
        saved=True, saved_at=row["updated_at"],
        jira=JiraConnection(**jira), rally=RallyConnection(**rally),
    )


@router.delete("/saved", response_model=SavedConnectionState)
def forget_connections() -> SavedConnectionState:
    store.delete_setting(_SETTING_KEY)
    return SavedConnectionState(saved=False)
