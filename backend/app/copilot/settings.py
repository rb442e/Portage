"""Sora runtime settings: the 'sora' section of the product settings registry."""
from __future__ import annotations

from typing import Any, Dict

from .. import product_settings

MODES = ("readonly", "propose")


def get() -> Dict[str, Any]:
    return product_settings.get("sora")


def update(patch: Dict[str, Any]) -> Dict[str, Any]:
    return product_settings.update("sora", patch)
