import os
import sys
import tempfile
from pathlib import Path

# Must run before `app` is imported: settings read PORTAGE_DATA_DIR at import time.
os.environ["PORTAGE_DATA_DIR"] = tempfile.mkdtemp(prefix="portage-test-")
# Most tests exercise features, not sign-in; test_auth.py turns authentication back on.
os.environ["PORTAGE_AUTH_DISABLED"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import store  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:  # runs startup (init_db + knowledge index)
        yield c


@pytest.fixture(autouse=True)
def clean_db():
    store.init_db()
    from app import auth
    auth.init_tables()
    auth._ip_hits.clear()
    from app.store import _conn, _lock
    with _lock, _conn() as conn:
        for t in ("mappings", "lookups", "entity_versions", "copilot_conversations", "copilot_messages",
                  "copilot_proposals", "copilot_audit", "app_settings", "jobs", "users", "auth_codes", "sessions",
                  "signups", "login_failures"):
            conn.execute(f"DELETE FROM {t}")
    yield
