"""Browser reloads should reach the SPA while missing APIs/assets remain errors."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import FrontendFiles


@pytest.fixture
def frontend(tmp_path):
    (tmp_path / "index.html").write_text("<html>Portage verification shell</html>")
    app = FastAPI()
    app.mount("/", FrontendFiles(directory=tmp_path, html=True))
    return TestClient(app)


def test_browser_can_reload_settings_route(frontend):
    response = frontend.get("/settings", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "Portage verification shell" in response.text


@pytest.mark.parametrize("path", ["/api/missing", "/assets/missing", "/missing.js"])
def test_frontend_does_not_mask_missing_api_or_assets(frontend, path):
    assert frontend.get(path, headers={"Accept": "text/html"}).status_code == 404


def test_non_navigation_request_does_not_receive_html(frontend):
    assert frontend.get("/settings", headers={"Accept": "application/json"}).status_code == 404
