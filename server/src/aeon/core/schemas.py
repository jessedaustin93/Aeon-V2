"""Schema definitions and validation for Aeon-V1 Layer 7.

All inter-agent messages and staging proposals MUST conform to these schemas.
Validation is pure — no I/O, no side effects, no imports from other layers.

# LAYER 7 STABLE — DO NOT MODIFY WITHOUT EXPLICIT INSTRUCTION
"""
from typing import Any, Dict, Optional, Tuple

# ---- constants ---------------------------------------------------------------

VALID_MEMORY_TYPES: frozenset = frozenset({"raw", "episodic", "semantic", "tool_addition"})

VALID_STATUSES: frozenset = frozenset({
    "pending",
    "approved_for_review",
    "approved_for_commit",
    "rejected",
    "committed",
})

VALID_ACTIONS: frozenset = frozenset({
    "propose",
    "validate",
    "approve",
    "reject",
    "commit",
    "read",
    "run",      # orchestrator → agent: execute one work cycle
    "write",    # agent → DataWriteAgent: request a memory-system write
})

# Required keys per schema
_MSG_REQUIRED = frozenset({
    "trace_id", "agent_id", "action", "target",
    "payload", "status", "timestamp", "requires_approval",
})
_PROPOSAL_REQUIRED = frozenset({
    "trace_id", "proposed_by", "content", "type",
    "confidence", "timestamp", "status",
})
_AUDIT_REQUIRED = frozenset({"trace_id", "agent", "action", "result", "timestamp"})


# ---- validators --------------------------------------------------------------

def validate_agent_message(msg: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate an inter-agent message. Returns (ok, reason)."""
    if not isinstance(msg, dict):
        return False, "Message must be a dict."
    missing = _MSG_REQUIRED - set(msg.keys())
    if missing:
        return False, f"Missing required fields: {sorted(missing)}"
    if not isinstance(msg.get("trace_id"), str) or not msg["trace_id"].strip():
        return False, "trace_id must be a non-empty string."
    if not isinstance(msg.get("agent_id"), str) or not msg["agent_id"].strip():
        return False, "agent_id must be a non-empty string."
    if msg.get("action") not in VALID_ACTIONS:
        return False, f"action must be one of {sorted(VALID_ACTIONS)}; got {msg.get('action')!r}."
    if not isinstance(msg.get("payload"), dict):
        return False, "payload must be a dict."
    if not isinstance(msg.get("requires_approval"), bool):
        return False, "requires_approval must be a bool."
    return True, "ok"


def validate_staging_proposal(proposal: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate a staging proposal. Returns (ok, reason)."""
    if not isinstance(proposal, dict):
        return False, "Proposal must be a dict."
    missing = _PROPOSAL_REQUIRED - set(proposal.keys())
    if missing:
        return False, f"Missing required fields: {sorted(missing)}"
    if not isinstance(proposal.get("trace_id"), str) or not proposal["trace_id"].strip():
        return False, "trace_id must be a non-empty string."
    if not isinstance(proposal.get("proposed_by"), str) or not proposal["proposed_by"].strip():
        return False, "proposed_by must be a non-empty string."
    if proposal.get("type") not in VALID_MEMORY_TYPES:
        return False, f"type must be one of {sorted(VALID_MEMORY_TYPES)}; got {proposal.get('type')!r}."
    confidence = proposal.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
        return False, "confidence must be a float in [0.0, 1.0]."
    if not isinstance(proposal.get("content"), str) or not proposal["content"].strip():
        return False, "content must be a non-empty string."
    status = proposal.get("status")
    if status not in VALID_STATUSES:
        return False, f"status must be one of {sorted(VALID_STATUSES)}; got {status!r}."
    return True, "ok"


def validate_audit_entry(entry: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate an audit log entry. Returns (ok, reason)."""
    if not isinstance(entry, dict):
        return False, "Audit entry must be a dict."
    missing = _AUDIT_REQUIRED - set(entry.keys())
    if missing:
        return False, f"Missing required fields: {sorted(missing)}"
    return True, "ok"


# ---- factories ---------------------------------------------------------------

def make_agent_message(
    agent_id: str,
    action: str,
    target: str,
    payload: Dict,
    status: str,
    timestamp: str,
    requires_approval: bool,
    trace_id: Optional[str] = None,
) -> Dict:
    """Construct a well-formed agent message dict."""
    from .memory_store import _generate_id  # local import — avoids circular load
    return {
        "trace_id":          trace_id or _generate_id(),
        "agent_id":          agent_id,
        "action":            action,
        "target":            target,
        "payload":           payload,
        "status":            status,
        "timestamp":         timestamp,
        "requires_approval": requires_approval,
    }


def make_staging_proposal(
    proposed_by: str,
    content: str,
    memory_type: str,
    confidence: float,
    timestamp: str,
    trace_id: Optional[str] = None,
) -> Dict:
    """Construct a well-formed staging proposal dict with status='pending'."""
    from .memory_store import _generate_id
    return {
        "trace_id":    trace_id or _generate_id(),
        "proposed_by": proposed_by,
        "content":     content,
        "type":        memory_type,
        "confidence":  round(float(confidence), 4),
        "timestamp":   timestamp,
        "status":      "pending",
    }
