"""Turn a goal into a structured, saved plan.

Uses a delimiter format (not JSON-with-multiline) for robust parsing — the same
lesson as the skill forge. Plans are saved to <data>/plans/ and summarized into
memory, so Aeon can plan work before doing it (groundwork for plan→execute).
"""
import json
import re
import uuid
from typing import Dict, List, Optional

from aeon.core.config import Config
from aeon.core.time_utils import utc_now_iso
from aeon.core.tools import ToolDefinition
from aeon.models.router import ModelRouter

_PROMPT = """Make a concrete, actionable plan for this goal. Reply in EXACTLY \
this format and nothing else:

TITLE: short title
STEPS:
1. step — brief detail of how
2. step — brief detail of how
(as many as needed)
RISKS:
- a risk or thing to watch
- another (omit the line if none)

Goal: {goal}"""

_STEP_RE = re.compile(r"^\s*\d+\.\s*(.+?)\s*$")
_RISK_RE = re.compile(r"^\s*[-*]\s*(.+?)\s*$")


def _parse_plan(text: str) -> Optional[Dict]:
    title = ""
    steps: List[Dict] = []
    risks: List[str] = []
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("TITLE:"):
            title = stripped[6:].strip()
            section = None
            continue
        if upper.startswith("STEPS:"):
            section = "steps"
            continue
        if upper.startswith("RISKS:"):
            section = "risks"
            continue
        if section == "steps":
            m = _STEP_RE.match(line)
            if m:
                raw = m.group(1)
                step, _, detail = raw.partition(" — ")
                if not detail:
                    step, _, detail = raw.partition(" - ")
                steps.append({"step": step.strip(), "detail": detail.strip()})
        elif section == "risks":
            m = _RISK_RE.match(line)
            if m:
                risks.append(m.group(1))
    if not steps:
        return None
    return {"title": title or "Plan", "steps": steps, "risks": risks}


def generate_plan(arguments: Dict, config: Config) -> Dict:
    goal = arguments["goal"]
    router = ModelRouter(config)
    client, model = router.resolve("chat")
    text = ""
    for delta in client.chat(model, [{"role": "user", "content": _PROMPT.format(goal=goal)}], stream=False):
        if delta.kind == "text":
            text += delta.text

    parsed = _parse_plan(text)
    if parsed is None:
        return {"error": "could not produce a structured plan"}

    plan = {
        "id": uuid.uuid4().hex[:12],
        "goal": goal,
        "title": parsed["title"],
        "steps": parsed["steps"],
        "risks": parsed["risks"],
        "created_at": utc_now_iso(),
    }
    plans_dir = config.base_path / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / f"{plan['id']}.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    try:
        from aeon.core.ingest import ingest
        ingest(f"Plan for: {goal}\n{parsed['title']} ({len(parsed['steps'])} steps)",
               source="plan", config=config)
    except Exception:
        pass

    return plan


DEFINITIONS = [
    ToolDefinition(
        name="generate_plan",
        description="Turn a goal into a concrete, saved step-by-step plan with risks.",
        parameters={"type": "object", "properties": {"goal": {"type": "string"}}, "required": ["goal"]},
        tags=["planning"],
        approval_required=False,
    ),
]

HANDLERS = {"generate_plan": generate_plan}
