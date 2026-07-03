"""Write agent for Aeon-V1 Layer 7.

WriteAgent is the ONLY component permitted to commit proposals into the
persistent memory system. It operates exclusively on proposals whose
status is 'approved_for_commit'.

create_proposal() is the entry point for agents that want to propose a memory
write. It creates a staging file and returns the proposal dict — the proposal
must then pass through ValidationAgent and ApprovalAgent before WriteAgent
will commit it.

SAFETY CONTRACT
===============
- Reads only from memory/staging/ (always path-guarded before access).
- Writes to memory/approved/ (staging archive) and the memory system via ingest().
- NEVER commits a proposal whose status != 'approved_for_commit'.
- Schema is re-validated at commit time (belt-and-suspenders).
- Every action — creation, block, commit, error — is written to the audit log.
- No subprocess, os.system, exec, eval, or network primitive is used.
- vault/core/ is never written by this module.

# LAYER 7 STABLE — DO NOT MODIFY WITHOUT EXPLICIT INSTRUCTION
"""
import json
from typing import Dict, List, Optional

from .config import Config
from .ingest import ingest
from .memory_store import _generate_id
from .schemas import make_staging_proposal, validate_staging_proposal
from .security import AuditLog, PathGuard, SecurityError
from .time_utils import utc_now_iso


# ---------------------------------------------------------------------------
# Proposal creation (staging entry point)
# ---------------------------------------------------------------------------

def create_proposal(
    proposed_by: str,
    content: str,
    memory_type: str,
    confidence: float,
    config: Config,
    trace_id: Optional[str] = None,
) -> Dict:
    """Create a new memory-write proposal in memory/staging/.

    This is the ONLY way an agent should initiate a memory write under
    Layer 7 governance. The returned proposal has status='pending'.

    Args:
        proposed_by:  Identifier of the agent or component making the proposal.
        content:      Text content to be ingested if approved.
        memory_type:  One of 'raw', 'episodic', 'semantic'.
        confidence:   Confidence score in [0.0, 1.0].
        config:       Config instance.
        trace_id:     Optional trace ID; generated if omitted.

    Returns:
        The proposal dict as written to disk.

    Raises:
        ValueError:   If the proposal fails schema validation before creation.
        SecurityError: If the staging path is not within approved directories.
    """
    staging_dir = config.memory_path / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    guard = PathGuard(config)
    audit = AuditLog(config)

    proposal = make_staging_proposal(
        proposed_by=proposed_by,
        content=content,
        memory_type=memory_type,
        confidence=confidence,
        timestamp=utc_now_iso(),
        trace_id=trace_id,
    )

    # Validate before touching disk.
    ok, reason = validate_staging_proposal(proposal)
    if not ok:
        raise ValueError(f"Proposal schema invalid: {reason}")

    proposal_id = proposal["trace_id"]
    path = staging_dir / f"{proposal_id}.json"
    guard.assert_allowed(path)

    path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    audit.append(proposal_id, "WriteAgent", "propose", f"staged by {proposed_by}")
    return proposal


# ---------------------------------------------------------------------------
# Write agent
# ---------------------------------------------------------------------------

class WriteAgent:
    """Commits approved proposals from staging into the memory system.

    This is the sole writer in the Layer 7 pipeline. No other component may
    call ingest() as a result of an agent-initiated write request.

    Direct calls to ingest() from trusted internal code (e.g. tests, scripts)
    are still valid — they bypass Layer 7 governance by design. Layer 7 governs
    agent-initiated writes only.
    """

    def __init__(self, config: Config) -> None:
        self.config    = config
        self._staging  = config.memory_path / "staging"
        self._approved = config.memory_path / "approved"
        self._guard    = PathGuard(config)
        self._audit    = AuditLog(config)
        self._staging.mkdir(parents=True, exist_ok=True)
        self._approved.mkdir(parents=True, exist_ok=True)

    def commit_proposal(self, proposal_id: str) -> Dict:
        """Commit one approved proposal into the memory system.

        Returns:
            ok          — True if committed successfully
            proposal_id — echoed back
            memory_id   — ID assigned by the memory system, or None on failure
            reason      — human-readable outcome
        """
        staging_path = self._staging / f"{proposal_id}.json"
        self._guard.assert_allowed(staging_path)

        if not staging_path.exists():
            self._audit.append(proposal_id, "WriteAgent", "commit", "not_found")
            return {
                "ok": False, "proposal_id": proposal_id,
                "memory_id": None, "reason": "not_found",
            }

        try:
            proposal = json.loads(staging_path.read_text(encoding="utf-8"))
        except Exception as exc:
            reason = f"parse_error: {exc}"
            self._audit.append(proposal_id, "WriteAgent", "commit", reason)
            return {
                "ok": False, "proposal_id": proposal_id,
                "memory_id": None, "reason": reason,
            }

        # Mandatory status gate — the only key that unlocks a commit.
        if proposal.get("status") != "approved_for_commit":
            reason = (
                f"BLOCKED: status is {proposal.get('status')!r}; "
                "requires 'approved_for_commit'."
            )
            self._audit.append(proposal_id, "WriteAgent", "commit", reason)
            return {
                "ok": False, "proposal_id": proposal_id,
                "memory_id": None, "reason": reason,
            }

        # Belt-and-suspenders schema re-check at commit time.
        ok, schema_reason = validate_staging_proposal(proposal)
        if not ok:
            reason = f"BLOCKED: schema invalid at commit time: {schema_reason}"
            self._audit.append(proposal_id, "WriteAgent", "commit", reason)
            return {
                "ok": False, "proposal_id": proposal_id,
                "memory_id": None, "reason": reason,
            }

        # Type-specific commit handler.
        try:
            if proposal.get("type") == "tool_addition":
                memory_id = _commit_tool_addition(proposal, self.config, self._guard)
            else:
                result = ingest(
                    text=proposal["content"],
                    source=f"layer7:{proposal.get('proposed_by', 'unknown')}",
                    config=self.config,
                )
                memory_id = (
                    (result.get("episodic") or {}).get("id")
                    or (result.get("semantic") or {}).get("id")
                    or (result.get("raw") or {}).get("id")
                    or _generate_id()
                )
        except Exception as exc:
            reason = f"commit_error: {exc}"
            self._audit.append(proposal_id, "WriteAgent", "commit", reason)
            return {
                "ok": False, "proposal_id": proposal_id,
                "memory_id": None, "reason": reason,
            }

        # Archive the committed proposal to memory/approved/.
        proposal["status"]       = "committed"
        proposal["committed_at"] = utc_now_iso()
        proposal["memory_id"]    = memory_id

        approved_path = self._approved / f"{proposal_id}.json"
        self._guard.assert_allowed(approved_path)
        approved_path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")

        # Remove from staging — the write is final.
        staging_path.unlink()

        self._audit.append(
            proposal_id, "WriteAgent", "commit",
            f"committed; memory_id={memory_id}",
        )
        return {
            "ok": True, "proposal_id": proposal_id,
            "memory_id": memory_id, "reason": "committed",
        }

    def commit_all_approved(self) -> List[Dict]:
        """Commit every proposal with status 'approved_for_commit'.

        Returns a list of per-proposal result dicts.
        """
        results = []
        for f in sorted(self._staging.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("status") == "approved_for_commit":
                results.append(self.commit_proposal(f.stem))
        return results

    def list_committed(self) -> List[Dict]:
        """Return all committed proposals archived in memory/approved/."""
        committed = []
        for f in sorted(self._approved.glob("*.json")):
            try:
                committed.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
        return committed

    def list_staging(self, status: Optional[str] = None) -> List[Dict]:
        """Return proposals in staging, optionally filtered by status."""
        proposals = []
        for f in sorted(self._staging.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if status is None or data.get("status") == status:
                    proposals.append(data)
            except Exception:
                pass
        return proposals


# ---------------------------------------------------------------------------
# Tool-addition commit handler (called by WriteAgent for type="tool_addition")
# ---------------------------------------------------------------------------

def _commit_tool_addition(proposal: Dict, config: Config, guard: PathGuard) -> str:
    """Write an approved tool addition to memory/tool_additions/.

    Returns the ID of the stored addition.
    """
    additions_dir = config.memory_path / "tool_additions"
    additions_dir.mkdir(parents=True, exist_ok=True)

    addition_id = proposal.get("trace_id", _generate_id())
    path = additions_dir / f"{addition_id}.json"
    guard.assert_allowed(path)

    try:
        tool_data = json.loads(proposal["content"])
    except (json.JSONDecodeError, KeyError):
        tool_data = {"raw_content": proposal.get("content", "")}

    record = {
        "id":           addition_id,
        "tool_data":    tool_data,
        "proposed_by":  proposal.get("proposed_by", "unknown"),
        "approved_by":  proposal.get("approved_by", "unknown"),
        "approved_at":  proposal.get("approved_at", utc_now_iso()),
        "trace_id":     proposal.get("trace_id", addition_id),
        "status":       "approved",
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return addition_id
