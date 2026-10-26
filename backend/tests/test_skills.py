from pathlib import Path

import pytest

from app.copilot import skills


def test_sora_skills_are_loaded_from_skill_markdown_files():
    assert list(skills.SKILLS) == list(skills.SKILL_ORDER)
    for key, skill in skills.SKILLS.items():
        path = skills.SKILLS_DIR / key / "SKILL.md"
        assert path.is_file()
        assert skill.instructions


def test_skill_selection_preserves_explicit_and_keyword_routing():
    assert skills.pick_skill("@catalog show my mappings", "").key == "catalog"
    assert skills.pick_skill("Map Rally Iteration to Jira sprint", "/mapping").key == "mapping"
    assert skills.pick_skill("Tell me a joke", "/").key == "general"


def test_skill_loader_rejects_incomplete_skill_set(tmp_path: Path):
    with pytest.raises(skills.SkillError, match="Missing required skill file"):
        skills.load_skills(tmp_path)
