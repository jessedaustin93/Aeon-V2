"""Distill a reusable skill proposal from a finished session transcript.

The model returns a small JSON object, or the sentinel NO_SKILL when the
session isn't worth generalizing. Proposals are always human-gated.
"""
from typing import Dict, List, Optional

from aeon.core.config import Config

from aeon.models.router import ModelRouter

from .store import Skill, SkillStore
from .forge import _parse_draft

_PROMPT = """You review a finished assistant session and decide whether it \
contains a reusable procedure worth saving as a skill for next time.

If yes, reply in EXACTLY this format (the body is multi-line markdown):

NAME: kebab-case-name
DESCRIPTION: one line
BODY:
1. first step
2. second step

If the session is too trivial or one-off to generalize, reply with exactly:
NO_SKILL

Session transcript:
"""


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

    if "NO_SKILL" in reply and "NAME:" not in reply:
        return None
    draft = _parse_draft(reply)
    if draft is None:
        return None

    store = SkillStore(config)
    try:
        return store.propose(draft["name"], draft["description"], draft["body"])
    except ValueError:
        return None
