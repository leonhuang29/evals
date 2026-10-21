from pathlib import Path

import pytest
from strands.vended_plugins.skills.skill import Skill

BAD_SKILL = """---
name: bad-skill
description: "unterminated
---
Body
"""


def test_malformed_frontmatter_raises_documented_value_error():
    with pytest.raises(ValueError):
        Skill.from_content(BAD_SKILL)


def test_malformed_skill_does_not_abort_valid_sibling(tmp_path: Path):
    good_dir = tmp_path / "good-skill"
    good_dir.mkdir()
    (good_dir / "SKILL.md").write_text("---\nname: good-skill\ndescription: valid\n---\nInstructions.\n")

    bad_dir = tmp_path / "bad-skill"
    bad_dir.mkdir()
    (bad_dir / "SKILL.md").write_text(BAD_SKILL)

    skills = Skill.from_directory(tmp_path)

    assert [skill.name for skill in skills] == ["good-skill"]
