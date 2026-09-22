"""Portage API entrypoint.

Run (dev):  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, store
from .config import settings
from .routers import (attachments, connections, lookups, mappings, migrations,
                      sources, tools)

app = FastAPI(title="Portage", version=__version__,
              description="Carry your work across, intact — ALM migration platform.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(connections.router)
app.include_router(sources.router)
app.include_router(mappings.router)
app.include_router(lookups.router)
app.include_router(migrations.router)
app.include_router(attachments.router)
app.include_router(tools.router)


@app.on_event("startup")
def _startup() -> None:
    store.init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "product": "Portage", "version": __version__}


# Optionally serve the built frontend (frontend/dist) from the same origin.
if settings.frontend_dist:
    dist = Path(settings.frontend_dist)
    if dist.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
