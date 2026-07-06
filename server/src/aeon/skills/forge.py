"""Skill Forge: research a topic and forge a validated skill from it.

A forged skill must clear a rubric critique AND a live A/B functional test
before it is offered as a proposal — never a hollow label.
"""
import json
import re
from typing import Dict, Optional

from aeon.core.config import Config
from aeon.agent.loop import AgentEvent, AgentLoop
from aeon.models.router import ModelRouter
from aeon.skills.store import SkillStore, _NAME_RE

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_DRAFT_PROMPT = """You are writing a reusable SKILL for an AI assistant, grounded \
ONLY in the research report below. A skill is concrete, actionable guidance for a \
class of tasks — numbered steps the assistant can actually follow, not vague \
advice. Every claim must be supported by the report.

Topic: {topic}

Research report:
{report}
{feedback}
Reply with ONLY a JSON object:
{{"name": "kebab-case-name", "description": "one line", "body": "markdown steps"}}"""

_CRITIQUE_PROMPT = """You are a strict reviewer. Judge whether this SKILL is worth \
keeping. Score 1-5 each: specific (concrete, not vague), grounded (supported by \
the report), actionable (the assistant can follow it). It PASSES only if every \
score is >= 4.

Research report:
{report}

Skill:
name: {name}
description: {description}
body:
{body}

Reply with ONLY a JSON object:
{{"passed": true|false, "scores": {{"specific": n, "grounded": n, "actionable": n}}, "issues": ["..."]}}"""

_TASK_PROMPT = """Give ONE realistic user question that a skill named "{name}" \
({description}) should help answer. Reply with only the question, no preamble."""

_JUDGE_PROMPT = """Two assistant answers to the same question. Answer A used a \
skill; answer B did not. Is A clearly better — more specific, correct, and useful?

Question: {task}

Answer A (with skill):
{with_skill}

Answer B (without skill):
{without_skill}

Reply with ONLY a JSON object: {{"with_better": true|false, "reason": "..."}}"""


def _complete(client, model, prompt: str) -> str:
    text = ""
    for delta in client.chat(model, [{"role": "user", "content": prompt}], stream=False):
        if delta.kind == "text":
            text += delta.text
    return text


def _parse_json(text: str) -> Optional[dict]:
    match = _JSON_RE.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def draft_skill(topic: str, report: str, client, model, feedback: str = "") -> Optional[Dict]:
    fb = f"\nFix these problems from the last attempt:\n{feedback}\n" if feedback else ""
    data = _parse_json(
        _complete(client, model, _DRAFT_PROMPT.format(topic=topic, report=report, feedback=fb))
    )
    if not data:
        return None
    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    body = str(data.get("body", "")).strip()
    if not (name and description and body) or not _NAME_RE.match(name):
        return None
    return {"name": name, "description": description, "body": body}


def critique_skill(draft: Dict, report: str, client, model) -> Dict:
    data = _parse_json(
        _complete(
            client,
            model,
            _CRITIQUE_PROMPT.format(
                report=report,
                name=draft["name"],
                description=draft["description"],
                body=draft["body"],
            ),
        )
    )
    if not data or "passed" not in data:
        return {"passed": False, "scores": {}, "issues": ["unparseable critique"]}
    return {
        "passed": bool(data["passed"]),
        "scores": data.get("scores", {}),
        "issues": list(data.get("issues", [])),
    }
