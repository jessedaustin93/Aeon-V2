"""Mesh messaging tool — let Aeon post to an Agent Mesh thread."""
from typing import Dict

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition
from aeon.mesh import MeshClient, MeshConfig


def mesh_post(arguments: Dict, config: Config) -> Dict:
    client = MeshClient(MeshConfig.from_env())
    if not client.configured:
        return {"error": "mesh not configured (set AEON_MESH_HUB and AEON_MESH_TOKEN)"}
    result = client.post_message(
        thread_id=arguments.get("thread_id"),
        recipient=arguments["recipient"],
        content=arguments["content"],
        kind=arguments.get("kind", "message"),
    )
    return {"posted": True, "message_id": result.get("id")}


DEFINITIONS = [
    ToolDefinition(
        name="mesh_post",
        description="Post a message to an Agent Mesh thread (reach another agent/machine).",
        parameters={
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": "e.g. claude@x1"},
                "content": {"type": "string"},
                "thread_id": {"type": "string", "description": "Existing thread id (optional)"},
            },
            "required": ["recipient", "content"],
        },
        tags=["mesh"],
        # Outward-facing: posting to another machine is an exfiltration sink,
        # so it is approval-gated even though the mesh is tailnet-only.
        approval_required=True,
    ),
]

HANDLERS = {"mesh_post": mesh_post}
