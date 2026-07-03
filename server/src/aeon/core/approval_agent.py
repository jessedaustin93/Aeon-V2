"""Human approval gate for Aeon-V1 Layer 7.

AuthProvider is the pluggable authentication interface. CLIAuthProvider is the
default — it reads yes/no from stdin. To add a dedicated hardware token, TOTP
device, or remote auth service in the future, subclass AuthProvider and pass
the instance to ApprovalAgent. No other code changes are required.

DESIGN PRINCIPLE
================
NO AUTO-APPROVAL is ever permitted under any code path.
Any proposal must pass through request_approval() before it can be committed.
A proposal that skips this gate is a security violation, not a fast path.

# LAYER 7 STABLE — DO NOT MODIFY WITHOUT EXPLICIT INSTRUCTION
"""
import json
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from .config import Config
from .security import AuditLog, PathGuard
from .time_utils import utc_now_iso


# ---------------------------------------------------------------------------
# Auth provider interface
# ---------------------------------------------------------------------------

class AuthProvider(ABC):
    """Pluggable human authentication interface.

    Implement this class to support different approval mechanisms:

        class HardwareTokenAuthProvider(AuthProvider):
            def request_approval(self, prompt, context):
                # block until physical button press or token validation
                ...

        class TOTPAuthProvider(AuthProvider):
            def request_approval(self, prompt, context):
                # verify a time-based one-time password
                ...

    Pass an instance to ApprovalAgent(config, auth_provider=...).
    """

    @abstractmethod
    def request_approval(self, prompt: str, context: Dict) -> Tuple[bool, str]:
        """Present an approval request to a human.

        Args:
            prompt:  Human-readable description of what is being approved.
            context: Structured proposal data (id, content, type, confidence …).

        Returns:
            (approved: bool, reason: str)
            reason is stored in the audit log; it should explain the decision.
        """

    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier written to the audit log and proposal record."""


# ---------------------------------------------------------------------------
# Default CLI implementation
# ---------------------------------------------------------------------------

class CLIAuthProvider(AuthProvider):
    """Command-line approval provider.

    Displays proposal details to stdout and reads a yes/no answer from stdin.
    Suitable for local development and manual review workflows.
    Replace with a hardware or network provider for higher-assurance environments.
    """

    def request_approval(self, prompt: str, context: Dict) -> Tuple[bool, str]:
        border = "=" * 62
        print(f"\n{border}")
        print("  AEON-V1  —  MEMORY WRITE APPROVAL REQUEST")
        print(border)
        print(f"  Trace ID    : {context.get('trace_id', 'unknown')}")
        print(f"  Proposed by : {context.get('proposed_by', 'unknown')}")
        print(f"  Memory type : {context.get('type', 'unknown')}")
        print(f"  Confidence  : {context.get('confidence', 'unknown')}")
        flags = context.get("content_flags")
        if flags:
            print(f"  *** FLAGS   : {flags}")
        print(f"  {'-' * 58}")
        content = str(context.get("content", ""))
        preview = content[:300] + ("…" if len(content) > 300 else "")
        for line in preview.splitlines():
            print(f"    {line}")
        print(border)
        print(f"  {prompt}")

        response = input("  Approve memory write? [yes/no]: ").strip().lower()
        if response in ("yes", "y"):
            return True, "approved via CLI"

        reason = input("  Rejection reason (Enter to skip): ").strip()
        return False, reason or "rejected via CLI"

    def provider_name(self) -> str:
        return "cli"


# ---------------------------------------------------------------------------
# Approval agent
# ---------------------------------------------------------------------------

class ApprovalAgent:
    """Human-gated approval stage for the Layer 7 write pipeline.

    Presents each 'approved_for_review' proposal to a human via AuthProvider.
    On approval  → marks status 'approved_for_commit', records who approved.
    On rejection → marks status 'rejected',             records reason.
    All decisions are written to the audit log.
    """

    def __init__(
        self,
        config: Config,
        auth_provider: Optional[AuthProvider] = None,
    ) -> None:
        self.config   = config
        self.auth     = auth_provider or CLIAuthProvider()
        self._staging = config.memory_path / "staging"
        self._guard   = PathGuard(config)
        self._audit   = AuditLog(config)
        self._staging.mkdir(parents=True, exist_ok=True)

    def approve_proposal(self, proposal_id: str) -> Dict:
        """Present one validated proposal for human approval.

        Returns:
            ok          — True if approved_for_commit
            proposal_id — echoed back
            decision    — 'approved' | 'rejected' | 'skipped' | 'error'
            reason      — human-readable explanation
        """
        path = self._staging / f"{proposal_id}.json"
        self._guard.assert_allowed(path)

        if not path.exists():
            self._audit.append(proposal_id, "ApprovalAgent", "approve", "not_found")
            return {
                "ok": False, "proposal_id": proposal_id,
                "decision": "error", "reason": "not_found",
            }

        try:
            proposal = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            reason = f"parse_error: {exc}"
            self._audit.append(proposal_id, "ApprovalAgent", "approve", reason)
            return {
                "ok": False, "proposal_id": proposal_id,
                "decision": "error", "reason": reason,
            }

        # Only 'approved_for_review' proposals reach the human gate.
        if proposal.get("status") != "approved_for_review":
            reason = (
                f"proposal status is {proposal.get('status')!r}; "
                "expected 'approved_for_review'"
            )
            self._audit.append(proposal_id, "ApprovalAgent", "approve", f"skipped: {reason}")
            return {
                "ok": False, "proposal_id": proposal_id,
                "decision": "skipped", "reason": reason,
            }

        prompt = (
            f"Proposal {proposal_id}: write "
            f"'{proposal.get('type', '?')}' memory "
            f"(confidence {proposal.get('confidence', '?')})."
        )

        # Human decision — the only code path that can advance this proposal.
        approved, reason = self.auth.request_approval(prompt, proposal)

        now = utc_now_iso()
        if approved:
            proposal["status"]      = "approved_for_commit"
            proposal["approved_at"] = now
            proposal["approved_by"] = self.auth.provider_name()
            path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
            self._audit.append(
                proposal_id, "ApprovalAgent", "approve",
                f"approved_for_commit via {self.auth.provider_name()}",
            )
            return {
                "ok": True, "proposal_id": proposal_id,
                "decision": "approved", "reason": reason,
            }
        else:
            proposal["status"]        = "rejected"
            proposal["rejected_at"]   = now
            proposal["rejected_by"]   = self.auth.provider_name()
            proposal["reject_reason"] = reason
            path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
            self._audit.append(
                proposal_id, "ApprovalAgent", "approve",
                f"rejected via {self.auth.provider_name()}: {reason}",
            )
            return {
                "ok": False, "proposal_id": proposal_id,
                "decision": "rejected", "reason": reason,
            }

    def process_queue(self) -> List[Dict]:
        """Present every 'approved_for_review' proposal for human approval.

        Returns a list of per-proposal result dicts.
        """
        results = []
        for f in sorted(self._staging.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("status") == "approved_for_review":
                results.append(self.approve_proposal(f.stem))
        return results
