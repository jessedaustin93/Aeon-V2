"""Skill access tool — the model lists skills from its system prompt and
pulls full instructions on demand."""
from typing import Dict

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition
from aeon.skills import SkillStore


def skill_use(arguments: Dict, config: Config) -> Dict:
    store = SkillStore(config)
    skill = store.get(arguments["name"])
    if skill is None:
        return {"error": f"unknown skill: {arguments['name']}"}
    return {"name": skill.name, "description": skill.description, "instructions": skill.body}


DEFINITIONS = [
    ToolDefinition(
        name="skill_use",
        description="Fetch the full instructions of an available skill by name.",
        parameters={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        tags=["skills"],
        approval_required=False,
    ),
]

HANDLERS = {"skill_use": skill_use}
