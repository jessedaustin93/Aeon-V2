"""Native Agent Mesh peer.

Polls the hub inbox and answers addressed messages by running Aeon's own
AgentLoop, then posts the reply back to the thread. Replaces the PTY-based
scripts/aeon_bridge.py: no subprocess CLI, Aeon answers as itself.
"""
import time
from typing import Callable, Dict, Optional

from aeon.core.config import Config
from aeon.agent.loop import AgentLoop

from .client import MeshClient, MeshConfig


class MeshPeer:
    def __init__(
        self,
        config: Optional[Config] = None,
        mesh_client: Optional[MeshClient] = None,
        loop: Optional[AgentLoop] = None,
        poll_seconds: float = 1.0,
    ):
        self.config = config or Config()
        self.mesh = mesh_client or MeshClient(MeshConfig.from_env())
        self.loop = loop or AgentLoop(config=self.config)
        self.poll_seconds = poll_seconds
        self._cursor = 0

    def _answer(self, content: str) -> str:
        reply = ""
        for event in self.loop.run([{"role": "user", "content": content}]):
            if event.kind == "text":
                reply += event.data.get("text", "")
            elif event.kind == "done" and not reply:
                reply = event.data.get("text", "")
            elif event.kind == "error":
                reply += f"\n[error: {event.data.get('error')}]"
        return reply.strip() or "(no response)"

    def poll_once(self) -> int:
        self.mesh.heartbeat("idle")
        messages = self.mesh.inbox(after=self._cursor)
        processed = 0
        for message in messages:
            msg_id = message.get("id")
            thread_id = message.get("thread_id")
            sender = message.get("sender", "")
            content = message.get("content", "")
            try:
                self.mesh.heartbeat("running")
                reply = self._answer(content)
            except Exception as exc:  # one bad message must not wedge the peer
                reply = f"[aeon error handling message: {exc}]"
            try:
                self.mesh.post_message(thread_id=thread_id, recipient=sender, content=reply)
                self.mesh.ack(msg_id)
            except Exception:
                pass
            if isinstance(msg_id, int):
                self._cursor = max(self._cursor, msg_id)
            processed += 1
        return processed

    def run_forever(self, should_stop: Callable[[], bool] = lambda: False) -> None:
        while not should_stop():
            try:
                self.poll_once()
            except Exception:
                pass
            time.sleep(self.poll_seconds)


def main() -> None:
    peer = MeshPeer()
    if not peer.mesh.configured:
        raise SystemExit("Mesh not configured: set AEON_MESH_HUB and AEON_MESH_TOKEN")
    print(f"Aeon mesh peer online as {peer.mesh.config.agent_id}")
    peer.run_forever()


if __name__ == "__main__":
    main()
