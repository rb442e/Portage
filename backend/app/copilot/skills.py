"""Load Sora's focused skills from versioned Markdown files.

Each skill lives in ``skills/<key>/SKILL.md``. YAML front matter contains routing
metadata and the Markdown body becomes the instruction block sent to Sora.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


SKILLS_DIR = Path(__file__).with_name("skills")
SKILL_ORDER = ("mapping", "catalog", "migration", "guide", "lineage", "general")


class SkillError(RuntimeError):
    """A skill file is malformed or the installed skill set is incomplete."""


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


def _strings(value: Any, field: str, path: Path) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise SkillError(f"{path}: '{field}' must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _read(path: Path) -> Skill:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SkillError(f"Could not read {path}: {e}") from e
    match = re.fullmatch(r"---\s*\n(.*?)\n---\s*\n(.*\S)\s*", text, re.DOTALL)
    if not match:
        raise SkillError(f"{path}: begin with YAML front matter delimited by --- and include Markdown instructions")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        raise SkillError(f"{path}: invalid YAML front matter: {e}") from e
    if not isinstance(meta, dict):
        raise SkillError(f"{path}: front matter must be a mapping")

    key, label, summary = meta.get("key"), meta.get("label"), meta.get("summary")
    if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", key):
        raise SkillError(f"{path}: 'key' must be a lowercase identifier")
    if path.parent.name != key:
        raise SkillError(f"{path}: directory name must match skill key '{key}'")
    if not isinstance(label, str) or not label.strip() or not isinstance(summary, str) or not summary.strip():
        raise SkillError(f"{path}: 'label' and 'summary' must be non-empty strings")
    raw_tools = meta.get("tools")
    if raw_tools is None or raw_tools == "all":
        tools: Optional[Tuple[str, ...]] = None
    elif isinstance(raw_tools, list):
        tools = _strings(raw_tools, "tools", path)
    else:
        raise SkillError(f"{path}: 'tools' must be a list or 'all'")
    return Skill(key=key, label=label.strip(), summary=summary.strip(), instructions=match.group(2).strip(),
                 tools=tools, keywords=_strings(meta.get("keywords"), "keywords", path),
                 routes=_strings(meta.get("routes"), "routes", path),
                 suggestions=_strings(meta.get("suggestions"), "suggestions", path))


def load_skills(directory: Path = SKILLS_DIR) -> Dict[str, Skill]:
    """Load the complete, ordered Sora skill set and fail fast on bad configuration."""
    loaded: Dict[str, Skill] = {}
    for key in SKILL_ORDER:
        path = directory / key / "SKILL.md"
        if not path.is_file():
            raise SkillError(f"Missing required skill file: {path}")
        skill = _read(path)
        if skill.key in loaded:
            raise SkillError(f"Duplicate skill key '{skill.key}'")
        loaded[skill.key] = skill
    unexpected = sorted(path.parent.name for path in directory.glob("*/SKILL.md") if path.parent.name not in loaded)
    if unexpected:
        raise SkillError(f"Unknown skills not listed in SKILL_ORDER: {', '.join(unexpected)}")
    return loaded


SKILLS = load_skills()


def pick_skill(message: str, route: str, explicit: str = "") -> Skill:
    match = re.match(r"\s*@(\w+)", message or "")
    key = (explicit or (match.group(1).lower() if match else "")).lower()
    if key in SKILLS:
        return SKILLS[key]
    text = (message or "").lower()
    best, best_score = SKILLS["general"], 0
    for skill in SKILLS.values():
        if skill.key == "general":
            continue
        score = sum(2 for keyword in skill.keywords if keyword in text)
        if route in skill.routes and route != "/":
            score += 1
        if score > best_score:
            best, best_score = skill, score
    return best


def suggestions_for(route: str) -> List[str]:
    for skill in SKILLS.values():
        if route in skill.routes and route != "/":
            return list(skill.suggestions)
    return list(SKILLS["migration"].suggestions) + list(SKILLS["guide"].suggestions[:1])
