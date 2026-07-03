"""Central in-process message bus for Aeon-V1.

All agent-to-agent (node-to-node) communication must go through this bus.
No component may call another agent's methods directly.

Usage
-----
Publish (fire-and-forget):
    bus.publish("some.topic", make_agent_message(...))

Request (synchronous reply from first matching handler):
    result = bus.request("agent.run.<agent_id>", make_agent_message(...))

Subscribe / unsubscribe:
    bus.subscribe("some.topic", handler)
    bus.unsubscribe("some.topic", handler)

Singleton access:
    from .bus import get_bus
    bus = get_bus()
"""
import threading
from typing import Any, Callable, Dict, List, Optional

from .schemas import validate_agent_message


class MessageBusError(Exception):
    """Raised on bus protocol violations (invalid message schema, etc.)."""


class MessageBus:
    """In-process publish/subscribe + synchronous request/reply message bus.

    - Thread-safe via RLock.
    - No external dependencies — pure Python.
    - Every outbound message is validated against the agent_message schema
      before delivery.  Invalid messages raise MessageBusError immediately.
    - publish(): delivers to ALL subscribers of a topic (fire-and-forget).
    - request(): delivers to subscribers in registration order; returns the
      first non-None handler result.  Returns None when no handler responds.
    """

    _instance: Optional["MessageBus"] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ singleton

    @classmethod
    def get(cls) -> "MessageBus":
        """Return the process-wide singleton bus, creating it on first call."""
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Discard the singleton and start fresh — intended for tests only."""
        with cls._class_lock:
            cls._instance = None

    # ------------------------------------------------------------------ subscribe

    def subscribe(self, topic: str, handler: Callable[[Dict], Any]) -> None:
        """Register *handler* to receive messages on *topic*.

        Handlers are called in registration order.  Duplicate registration of
        the same callable on the same topic is a no-op.
        """
        with self._lock:
            handlers = self._handlers.setdefault(topic, [])
            if handler not in handlers:
                handlers.append(handler)

    def unsubscribe(self, topic: str, handler: Callable) -> None:
        """Remove *handler* from *topic*.  Silent no-op if not registered."""
        with self._lock:
            handlers = self._handlers.get(topic, [])
            try:
                handlers.remove(handler)
            except ValueError:
                pass

    # ------------------------------------------------------------------ publish / request

    def publish(self, topic: str, message: Dict) -> None:
        """Validate *message* and deliver it to all subscribers of *topic*.

        Raises:
            MessageBusError: if the message fails schema validation.
        """
        self._validate(topic, message)
        with self._lock:
            handlers = list(self._handlers.get(topic, []))
        for handler in handlers:
            handler(message)

    def request(self, topic: str, message: Dict) -> Any:
        """Validate *message*, deliver it, and return the first non-None result.

        Handlers are tried in registration order.  The first handler that
        returns a non-None value wins and no further handlers are called.

        Returns None if no handler is registered for *topic* or if every
        registered handler returns None.

        Raises:
            MessageBusError: if the message fails schema validation.
        """
        self._validate(topic, message)
        with self._lock:
            handlers = list(self._handlers.get(topic, []))
        for handler in handlers:
            result = handler(message)
            if result is not None:
                return result
        return None

    # ------------------------------------------------------------------ introspection

    def topics(self) -> List[str]:
        """Return the list of topics that have at least one active subscriber."""
        with self._lock:
            return [t for t, h in self._handlers.items() if h]

    def subscriber_count(self, topic: str) -> int:
        """Return the number of handlers registered for *topic*."""
        with self._lock:
            return len(self._handlers.get(topic, []))

    # ------------------------------------------------------------------ internal

    def _validate(self, topic: str, message: Dict) -> None:
        ok, reason = validate_agent_message(message)
        if not ok:
            raise MessageBusError(
                f"Invalid message on topic {topic!r}: {reason}"
            )


def get_bus() -> MessageBus:
    """Convenience shortcut — returns the singleton MessageBus."""
    return MessageBus.get()
