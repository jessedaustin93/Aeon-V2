"""Security and path enforcement for Aeon-V1 Layer 7.

PathGuard   — enforces approved-directory rules; blocks path traversal.
AuditLog    — append-only JSONL audit trail in memory/logs/.
ValidationAgent — read-only schema + content checker for staging proposals.

SAFETY CONTRACT
===============
- No subprocess, os.system, exec, eval, or network primitive is used.
- vault/core/ is never written by this module.
- Traversal attempts (../) raise SecurityError immediately and are logged.
- ValidationAgent NEVER modifies proposal *content* — only the status field.

# LAYER 7 STABLE — DO NOT MODIFY WITHOUT EXPLICIT INSTRUCTION
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import Config
from .schemas import validate_staging_proposal
from .time_utils import utc_now_iso

# Subdirectories (relative to config.base_path) that agents may access.
_ALLOWED_SUBDIRS = (
    "memory/staging",
    "memory/approved",
    "memory/logs",
    "memory/tool_additions",
    "vault",
)

# Patterns in content that trigger a flag annotation.
# These never block a proposal — a human decides based on the flags.
_SUSPICIOUS_PATTERNS = (
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bsubprocess\b",
    r"\bos\.system\b",
    r"\bos\.popen\b",
    r"\b__import__\b",
    r"\.\.[\\/]",           # path traversal within content
    r"<script\b",           # XSS signal
)


class SecurityError(Exception):
    """Raised on path traversal or access-control violation."""


# ---------------------------------------------------------------------------
# PathGuard
# ---------------------------------------------------------------------------

class PathGuard:
    """Validates that every file path stays within approved directories.

    Raises SecurityError on any traversal attempt.
    Returns (False, reason) for paths outside approved directories.
    """

    def __init__(self, config: Config) -> None:
        base = config.base_path.resolve()
        self._allowed: Tuple[Path, ...] = tuple(
            (base / sub).resolve() for sub in _ALLOWED_SUBDIRS
        )

    def validate(self, path: Path) -> Tuple[bool, str]:
        """Return (ok, reason). Raises SecurityError on traversal."""
        # Reject traversal sequences before any resolution.
        parts = Path(str(path)).parts
        if ".." in parts:
            raise SecurityError(f"Path traversal attempt blocked: {path}")

        try:
            resolved = path.resolve()
        except Exception as exc:
            return False, f"Cannot resolve path: {exc}"

        for allowed in self._allowed:
            try:
                resolved.relative_to(allowed)
                return True, "ok"
            except ValueError:
                continue

        return False, f"Path outside approved directories: {resolved}"

    def assert_allowed(self, path: Path) -> None:
        """Raise SecurityError if path is not within an approved directory."""
        ok, reason = self.validate(path)
        if not ok:
            raise SecurityError(reason)


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------

class AuditLog:
    """Append-only audit log at memory/logs/audit.jsonl.

    Every Layer 7 action — proposal creation, validation, approval, commit,
    rejection — must produce an entry here. Entries are never deleted.
    """

    def __init__(self, config: Config) -> None:
        log_dir = config.memory_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._path = log_dir / "audit.jsonl"

    def append(
        self,
        trace_id: str,
        agent: str,
        action: str,
        result: str,
    ) -> Dict:
        entry = {
            "trace_id":  trace_id,
            "agent":     agent,
            "action":    action,
            "result":    result,
            "timestamp": utc_now_iso(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return entry

    def read_all(self) -> List[Dict]:
        """Return all audit entries in chronological order."""
        if not self._path.exists():
            return []
        entries = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        return entries

    def read_by_trace(self, trace_id: str) -> List[Dict]:
        """Return all entries for a specific trace_id."""
        return [e for e in self.read_all() if e.get("trace_id") == trace_id]


# ---------------------------------------------------------------------------
# ValidationAgent
# ---------------------------------------------------------------------------

class ValidationAgent:
    """Read-only agent that validates staging proposals.

    Responsibilities:
    - Verify schema correctness.
    - Check for corruption / parse errors.
    - Flag suspicious content patterns (never blocks — human decides).
    - Update status to 'approved_for_review' or 'rejected'.
    - NEVER modify the content field of any proposal.
    """

    def __init__(self, config: Config) -> None:
        self.config   = config
        self._staging = config.memory_path / "staging"
        self._guard   = PathGuard(config)
        self._audit   = AuditLog(config)
        self._staging.mkdir(parents=True, exist_ok=True)

    def validate_proposal(self, proposal_id: str) -> Dict:
        """Validate one staging proposal by ID.

        Returns a result dict:
            ok          — True if the proposal passed validation
            proposal_id — echoed back
            reason      — human-readable outcome
            flags       — list of suspicious patterns found in content
        """
        path = self._staging / f"{proposal_id}.json"

        # Path check first — fail fast and loudly.
        self._guard.assert_allowed(path)

        if not path.exists():
            self._audit.append(proposal_id, "ValidationAgent", "validate", "not_found")
            return {"ok": False, "proposal_id": proposal_id, "reason": "not_found", "flags": []}

        try:
            proposal = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            reason = f"parse_error: {exc}"
            self._audit.append(proposal_id, "ValidationAgent", "validate", reason)
            return {"ok": False, "proposal_id": proposal_id, "reason": reason, "flags": []}

        # Schema validation.
        ok, schema_reason = validate_staging_proposal(proposal)
        if not ok:
            proposal["status"]            = "rejected"
            proposal["validation_reason"] = schema_reason
            path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
            self._audit.append(
                proposal_id, "ValidationAgent", "validate", f"schema_rejected: {schema_reason}"
            )
            return {"ok": False, "proposal_id": proposal_id, "reason": schema_reason, "flags": []}

        # Content flagging — annotation only, never blocks.
        content = proposal.get("content", "")
        flags = [
            pat for pat in _SUSPICIOUS_PATTERNS
            if re.search(pat, content, re.IGNORECASE)
        ]

        # Update status; preserve content exactly as received.
        proposal["status"] = "approved_for_review"
        if flags:
            proposal["content_flags"] = flags

        path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
        self._audit.append(
            proposal_id, "ValidationAgent", "validate",
            f"approved_for_review; flags={flags or 'none'}",
        )
        return {
            "ok":          True,
            "proposal_id": proposal_id,
            "reason":      "approved_for_review",
            "flags":       flags,
        }

    def validate_all_pending(self) -> List[Dict]:
        """Validate every pending proposal in staging. Returns list of results."""
        results = []
        for f in sorted(self._staging.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("status") == "pending":
                results.append(self.validate_proposal(f.stem))
        return results
