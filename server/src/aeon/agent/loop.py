"""The Aeon-V2 agent loop.

Streams model output, executes tool calls through registered handlers,
gates approval_required tools through the ApprovalBroker, journals every
execution, and feeds results back to the model until it finishes without
tool calls (or hits the iteration cap).
"""
import json
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition
from aeon.tools import all_handlers
from aeon.skills import SkillStore

from aeon.models.router import ModelRouter

from .approvals import ApprovalBroker
from .journal import ToolJournal

SYSTEM_PROMPT = (
    "You are Aeon, Jesse's local-first systems assistant: practical, direct, "
    "technically capable, calm, honest about uncertainty. Use tools when they "
    "help; report real results, never invent tool output."
)


@dataclass
class AgentEvent:
    kind: str  # "text" | "tool_call" | "tool_result" | "approval_pending" | "done" | "error"
    data: Dict = field(default_factory=dict)


def _openai_tools(definitions: List[ToolDefinition]) -> List[Dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": d.name,
                "description": d.description,
                "parameters": d.parameters or {"type": "object", "properties": {}},
            },
        }
        for d in definitions
        if d.enabled
    ]


class AgentLoop:
    def __init__(
        self,
        config: Optional[Config] = None,
        router: Optional[ModelRouter] = None,
        broker: Optional[ApprovalBroker] = None,
        skill_store: Optional[SkillStore] = None,
        max_iterations: int = 12,
        approval_timeout: float = 300.0,
        enable_tools: bool = True,
    ):
        self.config = config or Config()
        self.router = router or ModelRouter(self.config)
        self.broker = broker or ApprovalBroker(self.config)
        self.skill_store = skill_store or SkillStore(self.config)
        self.max_iterations = max_iterations
        self.approval_timeout = approval_timeout
        self.enable_tools = enable_tools
        # A tool-less loop (e.g. the headless mesh peer, where no human is
        # present to approve gated calls and remote input is untrusted) gets
        # no handlers or definitions at all — the model can only converse.
        if enable_tools:
            self.handlers, self.definitions = all_handlers(self.config)
        else:
            self.handlers, self.definitions = {}, []
        self._defs_by_name = {d.name: d for d in self.definitions}
        self.journal = ToolJournal(self.config)

    def _system_prompt(self) -> str:
        # Active skills are advertised each run, so newly approved skills
        # take effect on the next message without a restart.
        return SYSTEM_PROMPT + self.skill_store.prompt_block()

    # ------------------------------------------------------------------ run

    def run(self, messages: List[Dict], role: str = "chat") -> Iterator[AgentEvent]:
        convo = list(messages)
        if not convo or convo[0].get("role") != "system":
            convo.insert(0, {"role": "system", "content": self._system_prompt()})
        tools = _openai_tools(self.definitions)

        try:
            client, model = self.router.resolve(role)
        except ValueError as exc:
            yield AgentEvent("error", {"error": str(exc)})
            return

        for _ in range(self.max_iterations):
            tool_calls: List[Dict] = []
            assistant_text = ""
            try:
                for delta in client.chat(model, convo, tools=tools, stream=True):
                    if delta.kind == "text":
                        assistant_text += delta.text
                        yield AgentEvent("text", {"text": delta.text})
                    elif delta.kind == "tool_call":
                        tool_calls = delta.tool_calls or []
            except Exception as exc:
                yield AgentEvent("error", {"error": f"model call failed: {exc}"})
                return

            if not tool_calls:
                yield AgentEvent("done", {"text": assistant_text})
                return

            convo.append(
                {
                    "role": "assistant",
                    "content": assistant_text or None,
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                yield from self._execute(call, convo)

        yield AgentEvent("error", {"error": "max iterations reached"})

    # -------------------------------------------------------------- execute

    def _execute(self, call: Dict, convo: List[Dict]) -> Iterator[AgentEvent]:
        name = call.get("function", {}).get("name", "")
        raw_args = call.get("function", {}).get("arguments") or "{}"
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError:
            arguments = {}
        yield AgentEvent(
            "tool_call", {"id": call.get("id"), "tool": name, "arguments": arguments}
        )

        handler = self.handlers.get(name)
        definition = self._defs_by_name.get(name)
        if handler is None or definition is None:
            result: Dict = {"error": f"unknown tool: {name}"}
        else:
            approved = True
            if definition.approval_required:
                request = self.broker.create(name, arguments)
                yield AgentEvent(
                    "approval_pending",
                    {"approval_id": request.id, "tool": name, "arguments": arguments},
                )
                status = self.broker.wait(request.id, timeout=self.approval_timeout)
                approved = status == "approved"
                if not approved:
                    result = {"error": f"denied by user ({status})"}
            if approved:
                try:
                    result = handler(arguments, self.config)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}
            self.journal.record(
                tool=name,
                arguments=arguments,
                result=result,
                status="error" if "error" in result else "ok",
            )

        yield AgentEvent(
            "tool_result", {"id": call.get("id"), "tool": name, "result": result}
        )
        convo.append(
            {
                "role": "tool",
                "tool_call_id": call.get("id"),
                "content": json.dumps(result),
            }
        )
