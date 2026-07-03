"""Write authorization guard for Aeon-V1.

Enforces that, within an agent execution context, only the designated
DataWriteAgent may call memory-system write functions:
    ingest(), reflect(), simulate_action(), evaluate_simulation(),
    select_next_task()

Outside any agent context (tests, scripts, direct API use) writes are
always permitted — the guard is a no-op unless AgentNode.run() is active.

Thread-local state is used so concurrent agents in different threads are
fully isolated from each other.
"""
import threading
from typing import Optional

_ctx = threading.local()


class WriteAuthorizationError(Exception):
    """Raised when an agent attempts a memory write without authorization."""


# ---------------------------------------------------------------------------
# State queries
# ---------------------------------------------------------------------------

def _in_agent_context() -> bool:
    return bool(getattr(_ctx, "agent_id", None))


def is_write_authorized() -> bool:
    """Return True if the current thread may perform a memory-system write."""
    if not _in_agent_context():
        return True  # tests, scripts, direct API — always permitted
    return bool(getattr(_ctx, "write_authorized", False))


def assert_write_authorized(operation: str = "write") -> None:
    """Raise WriteAuthorizationError if the running agent is not authorized to write.

    Called at the top of every guarded write function. Passes silently when:
      - There is no active agent context (tests / direct API calls).
      - The active context belongs to DataWriteAgent (write_authorized=True).
    """
    if not is_write_authorized():
        agent_id = getattr(_ctx, "agent_id", "unknown")
        role = getattr(_ctx, "role", "unknown")
        raise WriteAuthorizationError(
            f"Agent {agent_id!r} (role={role!r}) attempted unauthorized write: "
            f"{operation!r}. All memory writes must go through the DataWriteAgent "
            "via the message bus."
        )


# ---------------------------------------------------------------------------
# Context managers
# ---------------------------------------------------------------------------

class _AgentRunContext:
    """Marks the current thread as executing a specific AgentNode.run() cycle.

    Sets write_authorized=False — agents are not write-authorized by default.
    Stacks safely: nested contexts restore the previous state on exit, so a
    bus request handled synchronously within an agent run works correctly.
    """

    __slots__ = ("_agent_id", "_role", "_prev_id", "_prev_role", "_prev_auth")

    def __init__(self, agent_id: str, role: str) -> None:
        self._agent_id = agent_id
        self._role = role
        self._prev_id: Optional[str] = None
        self._prev_role: Optional[str] = None
        self._prev_auth: bool = False

    def __enter__(self) -> "_AgentRunContext":
        self._prev_id   = getattr(_ctx, "agent_id",        None)
        self._prev_role = getattr(_ctx, "role",             None)
        self._prev_auth = getattr(_ctx, "write_authorized", False)
        _ctx.agent_id        = self._agent_id
        _ctx.role            = self._role
        _ctx.write_authorized = False
        return self

    def __exit__(self, *_: object) -> None:
        _ctx.agent_id        = self._prev_id
        _ctx.role            = self._prev_role
        _ctx.write_authorized = self._prev_auth


class _WriteAuthorizedContext:
    """Temporarily grants write authorization to the current thread.

    Used exclusively inside DataWriteAgent handlers. Stacks over any
    existing _AgentRunContext and restores the previous auth state on exit.
    """

    __slots__ = ("_prev_auth",)

    def __init__(self) -> None:
        self._prev_auth: bool = False

    def __enter__(self) -> "_WriteAuthorizedContext":
        self._prev_auth = getattr(_ctx, "write_authorized", False)
        _ctx.write_authorized = True
        return self

    def __exit__(self, *_: object) -> None:
        _ctx.write_authorized = self._prev_auth


def agent_run_context(agent_id: str, role: str) -> _AgentRunContext:
    """Return a context manager that marks a thread as executing the given agent."""
    return _AgentRunContext(agent_id, role)


def write_authorized_context() -> _WriteAuthorizedContext:
    """Return a context manager that grants write authorization.

    Must only be entered inside DataWriteAgent request handlers.
    """
    return _WriteAuthorizedContext()
