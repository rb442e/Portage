"""Runtime configuration for the Portage backend.

Everything is env-overridable so the same image runs locally and self-hosted.
Secrets (Jira/Rally tokens) are never persisted; they arrive per-request from
the UI or are read from the environment for headless runs.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# Local overrides work with both the dev launcher and direct backend startup.
# Explicit process environment variables take precedence.
load_dotenv(Path(__file__).resolve().parents[2] / ".env.local", override=False)


class Settings:
    def __init__(self) -> None:
        # Where SQLite, uploads and job artifacts live.
        self.data_dir = Path(os.environ.get("PORTAGE_DATA_DIR", "./data")).resolve()
        self.upload_dir = self.data_dir / "uploads"
        self.db_path = self.data_dir / "portage.db"

        # CORS origins for the dev/prod frontend (comma-separated).
        self.cors_origins = [
            o.strip()
            for o in os.environ.get(
                "PORTAGE_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if o.strip()
        ]

        # Optional: serve the built frontend (frontend/dist) from the API.
        self.frontend_dist = os.environ.get("PORTAGE_FRONTEND_DIST", "").strip()

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
