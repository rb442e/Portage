"""Copilot runtime settings, persisted in app_settings (no secrets: Ollama is local)."""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from .. import store

_KEY = "copilot_settings"
MODES = ("readonly", "propose")


def _defaults() -> Dict[str, Any]:
    return {
        "enabled": True,
        "base_url": os.environ.get("PORTAGE_OLLAMA_URL", "http://localhost:11434"),
        "model": os.environ.get("PORTAGE_COPILOT_MODEL", "llama3.1:8b"),
        "mode": os.environ.get("PORTAGE_COPILOT_MODE", "propose"),
        "redact": True,
        "max_steps": 6,
    }


def get() -> Dict[str, Any]:
    cfg = _defaults()
    row = store.get_setting(_KEY)
    if row:
        try:
            cfg.update(json.loads(row["value"]))
        except ValueError:
            pass
    if cfg["mode"] not in MODES:
        cfg["mode"] = "propose"
    return cfg


def update(patch: Dict[str, Any]) -> Dict[str, Any]:
    cfg = get()
    for k in ("enabled", "base_url", "model", "mode", "redact", "max_steps"):
        if k in patch and patch[k] is not None:
            cfg[k] = patch[k]
    if cfg["mode"] not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    cfg["max_steps"] = max(1, min(int(cfg["max_steps"]), 12))
    cfg["base_url"] = str(cfg["base_url"]).rstrip("/")
    store.set_setting(_KEY, json.dumps(cfg))
    return cfg
