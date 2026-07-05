"""Distill a reusable skill proposal from a finished session transcript.

The model returns a small JSON object, or the sentinel NO_SKILL when the
session isn't worth generalizing. Proposals are always human-gated.
"""
import json
import re
from typing import Dict, List, Optional

from aeon.core.config import Config

from aeon.models.router import ModelRouter

from .store import Skill, SkillStore

_PROMPT = """You review a finished assistant session and decide whether it \
contains a reusable procedure worth saving as a skill for next time.

If yes, reply with ONLY a JSON object:
{"name": "kebab-case-name", "description": "one line", "body": "markdown steps"}

If the session is too trivial or one-off to generalize, reply with exactly:
NO_SKILL

Session transcript:
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _transcript(messages: List[Dict]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content")
        if role in ("user", "assistant") and content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def propose_from_transcript(
    messages: List[Dict],
    config: Optional[Config] = None,
    router: Optional[ModelRouter] = None,
) -> Optional[Skill]:
    config = config or Config()
    router = router or ModelRouter(config)
    client, model = router.resolve("chat")

    prompt = _PROMPT + _transcript(messages)
    reply = ""
    for delta in client.chat(model, [{"role": "user", "content": prompt}], stream=False):
        if delta.kind == "text":
            reply += delta.text

    if "NO_SKILL" in reply and "{" not in reply:
        return None
    match = _JSON_RE.search(reply)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    body = str(data.get("body", "")).strip()
    if not (name and description and body):
        return None

    store = SkillStore(config)
    try:
        return store.propose(name, description, body)
    except ValueError:
        return None
