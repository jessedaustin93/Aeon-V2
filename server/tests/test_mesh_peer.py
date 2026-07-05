import pytest

from aeon.core.config import Config
from aeon.agent.loop import AgentEvent
from aeon.mesh.peer import MeshPeer


class FakeMesh:
    def __init__(self, inboxes):
        # inboxes: list of message-lists returned on successive inbox() calls
        self.inboxes = list(inboxes)
        self.heartbeats = []
        self.posts = []
        self.acks = []

    @property
    def configured(self):
        return True

    def heartbeat(self, status="idle"):
        self.heartbeats.append(status)

    def inbox(self, after=0):
        return self.inboxes.pop(0) if self.inboxes else []

    def post_message(self, thread_id, recipient, content, kind="reply"):
        self.posts.append({"thread_id": thread_id, "recipient": recipient, "content": content})
        return {"id": 1000}

    def ack(self, message_id):
        self.acks.append(message_id)


class StubLoop:
    def __init__(self, reply="the mesh is healthy", raise_exc=False):
        self.reply = reply
        self.raise_exc = raise_exc

    def run(self, messages, role="chat"):
        if self.raise_exc:
            raise RuntimeError("loop boom")
        yield AgentEvent("text", {"text": self.reply})
        yield AgentEvent("done", {"text": self.reply})


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    return Config()


def test_answers_addressed_message(config):
    mesh = FakeMesh([[{"id": 5, "thread_id": "t1", "sender": "claude@x1", "content": "how is the mesh?"}]])
    peer = MeshPeer(config=config, mesh_client=mesh, loop=StubLoop())
    processed = peer.poll_once()
    assert processed == 1
    assert mesh.posts == [{"thread_id": "t1", "recipient": "claude@x1", "content": "the mesh is healthy"}]
    assert mesh.acks == [5]
    assert "running" in mesh.heartbeats


def test_cursor_advances(config):
    mesh = FakeMesh([
        [{"id": 5, "thread_id": "t1", "sender": "a", "content": "hi"}],
        [],
    ])
    peer = MeshPeer(config=config, mesh_client=mesh, loop=StubLoop())
    assert peer.poll_once() == 1
    assert peer._cursor == 5
    assert peer.poll_once() == 0


def test_loop_exception_posts_error_reply(config):
    mesh = FakeMesh([[{"id": 9, "thread_id": "t2", "sender": "claude@t3610", "content": "x"}]])
    peer = MeshPeer(config=config, mesh_client=mesh, loop=StubLoop(raise_exc=True))
    peer.poll_once()
    assert "error" in mesh.posts[0]["content"]
    assert mesh.acks == [9]


def test_empty_inbox_no_posts(config):
    mesh = FakeMesh([[]])
    peer = MeshPeer(config=config, mesh_client=mesh, loop=StubLoop())
    assert peer.poll_once() == 0
    assert mesh.posts == []
