"""Model status and delegation tools for Aeon's role/worker router."""
from typing import Dict, List

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition
from aeon.models.router import ModelRouter


def _worker_record(router: ModelRouter, worker) -> Dict:
    client = router._client(worker)
    loaded: List[str] = []
    error = ""
    try:
        loaded = client.list_models()
        worker.healthy = True
    except Exception as exc:
        worker.healthy = False
        error = f"{type(exc).__name__}: {exc}"
    record = {
        "name": worker.name,
        "base_url": worker.base_url,
        "configured_models": worker.models,
        "priority": worker.priority,
        "healthy": worker.healthy,
        "loaded_models": loaded,
    }
    if error:
        record["error"] = error
    return record


def model_status(arguments: Dict, config: Config) -> Dict:
    """Report configured role mapping and currently reachable model workers."""
    router = ModelRouter(config)
    workers = [_worker_record(router, worker) for worker in router.workers]
    by_url = {w["base_url"]: w for w in workers}
    roles = {}
    for role, model in sorted(router.roles.items()):
        try:
            client, resolved_model = router.resolve(role)
            selected = by_url.get(client.base_url, {})
            roles[role] = {
                "model": resolved_model,
                "worker": selected.get("name", ""),
                "base_url": client.base_url,
                "healthy": bool(selected.get("healthy", True)),
            }
        except Exception as exc:
            roles[role] = {"model": model, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "identity": "Aeon-V2 local-first runtime; not Claude or Anthropic.",
        "roles": roles,
        "workers": workers,
    }


def model_delegate(arguments: Dict, config: Config) -> Dict:
    """Run a bounded, tool-less prompt against a configured model role."""
    role = str(arguments.get("role") or "chat").strip()
    prompt = str(arguments.get("prompt") or "").strip()
    system = str(arguments.get("system") or "").strip()
    max_chars = int(arguments.get("max_chars") or 6000)
    if not prompt:
        return {"error": "prompt is required"}
    router = ModelRouter(config)
    client, model = router.resolve(role)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    text = ""
    for delta in client.chat(model, messages, tools=[], stream=False):
        if delta.kind == "text":
            text += delta.text
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars] + "\n[truncated]"
    worker = next((w for w in router.workers if w.base_url == client.base_url), None)
    return {
        "role": role,
        "model": model,
        "worker": worker.name if worker else "",
        "base_url": client.base_url,
        "text": text,
    }


DEFINITIONS = [
    ToolDefinition(
        name="model_status",
        description=(
            "Inspect Aeon's current local/OpenAI-compatible model routing: roles, "
            "selected workers, health, and loaded model IDs."
        ),
        parameters={"type": "object", "properties": {}},
        tags=["models"],
        approval_required=False,
    ),
    ToolDefinition(
        name="model_delegate",
        description=(
            "Ask a configured model role such as chat or deep to handle a bounded "
            "tool-less subtask, returning the model, worker, and response text."
        ),
        parameters={
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "description": "Configured model role to use, usually chat or deep.",
                },
                "prompt": {"type": "string", "description": "The subtask prompt."},
                "system": {
                    "type": "string",
                    "description": "Optional system instruction for the delegated call.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum response characters to return.",
                },
            },
            "required": ["prompt"],
        },
        tags=["models"],
        approval_required=False,
    ),
]

HANDLERS = {"model_status": model_status, "model_delegate": model_delegate}
