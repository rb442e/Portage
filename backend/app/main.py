"""Portage API entrypoint.

Run (dev):  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from . import __version__, auth, store
from .config import settings
from .routers import (attachments, auth as auth_router, connections, copilot, lookups, mappings,
                      migrations, settings as settings_router, sources, tools)


class FrontendFiles(StaticFiles):
    """Serve client-side navigation routes without masking missing APIs or assets."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            headers = dict(scope.get("headers", []))
            navigation = b"text/html" in headers.get(b"accept", b"")
            reserved = path == "api" or path.startswith(("api/", "assets/"))
            if exc.status_code != 404 or not navigation or reserved or Path(path).suffix:
                raise
            return await super().get_response("index.html", scope)


app = FastAPI(title="Portage", version=__version__,
              description="Carry your work across, intact — ALM migration platform.")

# Registered before CORS so CORS stays outermost and 401/403 answers still carry CORS headers.
app.middleware("http")(auth.middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(connections.router)
app.include_router(sources.router)
app.include_router(mappings.router)
app.include_router(lookups.router)
app.include_router(migrations.router)
app.include_router(attachments.router)
app.include_router(tools.router)
app.include_router(copilot.router)

app.include_router(settings_router.router)


@app.on_event("startup")
def _startup() -> None:
    store.init_db()
    auth.init_tables()
    from .copilot import attachments, knowledge, settings as copilot_settings
    knowledge.rebuild()
    attachments.purge(copilot_settings.get()["attachment_retention_days"])


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "product": "Portage", "version": __version__}


# Optionally serve the built frontend (frontend/dist) from the same origin.
if settings.frontend_dist:
    dist = Path(settings.frontend_dist)
    if dist.exists():
        app.mount("/", FrontendFiles(directory=str(dist), html=True), name="frontend")
