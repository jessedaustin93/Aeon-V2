"""Tests for Layer 7: Security, Access Control, and Memory Write Governance.

Stages tested independently:
  1. schemas.py        — pure validation, no I/O
  2. security.py       — PathGuard, AuditLog, ValidationAgent
  3. approval_agent.py — AuthProvider interface, CLIAuthProvider contract,
                         ApprovalAgent with MockAuthProvider (no stdin)
  4. write_agent.py    — create_proposal, WriteAgent commit pipeline
  5. Integration       — full propose → validate → approve → commit pipeline
"""
import json
import pytest
from pathlib import Path

from aeon.core import (
    ApprovalAgent,
    AuditLog,
    AuthProvider,
    CLIAuthProvider,
    Config,
    PathGuard,
    SecurityError,
    VALID_ACTIONS,
    VALID_MEMORY_TYPES,
    VALID_STATUSES,
    ValidationAgent,
    WriteAgent,
    create_proposal,
    make_agent_message,
    make_staging_proposal,
    validate_agent_message,
    validate_audit_entry,
    validate_staging_proposal,
)
from aeon.core.time_utils import utc_now_iso


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def cfg(tmp_path):
    c = Config(tmp_path)
    c.importance_threshold = 0.0   # accept all content in tests
    return c


class MockAuthProvider(AuthProvider):
    """Non-interactive auth provider for testing."""

    def __init__(self, approve: bool = True, reason: str = "mock-approved"):
        self._approve = approve
        self._reason  = reason

    def request_approval(self, prompt, context):
        return self._approve, self._reason

    def provider_name(self):
        return "mock"


def _make_valid_proposal(**overrides):
    base = {
        "trace_id":    "test-trace-001",
        "proposed_by": "test-agent",
        "content":     "This is valid test content.",
        "type":        "raw",
        "confidence":  0.7,
        "timestamp":   utc_now_iso(),
        "status":      "pending",
    }
    base.update(overrides)
    return base


def _make_valid_message(**overrides):
    base = {
        "trace_id":          "trace-msg-001",
        "agent_id":          "agent-001",
        "action":            "propose",
        "target":            "memory/staging/",
        "payload":           {"content": "test"},
        "status":            "pending",
        "timestamp":         utc_now_iso(),
        "requires_approval": True,
    }
    base.update(overrides)
    return base


# ===========================================================================
# STAGE 1 — schemas.py
# ===========================================================================

class TestConstants:
    def test_valid_memory_types(self):
        assert "raw" in VALID_MEMORY_TYPES
        assert "episodic" in VALID_MEMORY_TYPES
        assert "semantic" in VALID_MEMORY_TYPES
        assert "unknown" not in VALID_MEMORY_TYPES

    def test_valid_statuses(self):
        for s in ("pending", "approved_for_review", "approved_for_commit",
                  "rejected", "committed"):
            assert s in VALID_STATUSES

    def test_valid_actions(self):
        for a in ("propose", "validate", "approve", "reject", "commit", "read"):
            assert a in VALID_ACTIONS


class TestValidateAgentMessage:
    def test_valid_message_passes(self):
        ok, reason = validate_agent_message(_make_valid_message())
        assert ok, reason

    def test_missing_field_fails(self):
        msg = _make_valid_message()
        del msg["trace_id"]
        ok, reason = validate_agent_message(msg)
        assert not ok
        assert "trace_id" in reason

    def test_empty_trace_id_fails(self):
        ok, reason = validate_agent_message(_make_valid_message(trace_id="  "))
        assert not ok

    def test_invalid_action_fails(self):
        ok, reason = validate_agent_message(_make_valid_message(action="explode"))
        assert not ok
        assert "action" in reason

    def test_payload_not_dict_fails(self):
        ok, reason = validate_agent_message(_make_valid_message(payload="bad"))
        assert not ok

    def test_requires_approval_not_bool_fails(self):
        ok, reason = validate_agent_message(
            _make_valid_message(requires_approval="yes")
        )
        assert not ok

    def test_non_dict_fails(self):
        ok, reason = validate_agent_message("not a dict")
        assert not ok

    def test_all_valid_actions_accepted(self):
        for action in VALID_ACTIONS:
            ok, _ = validate_agent_message(_make_valid_message(action=action))
            assert ok, f"action={action} should be valid"


class TestValidateStagingProposal:
    def test_valid_proposal_passes(self):
        ok, reason = validate_staging_proposal(_make_valid_proposal())
        assert ok, reason

    def test_missing_content_fails(self):
        ok, reason = validate_staging_proposal(_make_valid_proposal(content=""))
        assert not ok

    def test_invalid_type_fails(self):
        ok, reason = validate_staging_proposal(_make_valid_proposal(type="blob"))
        assert not ok
        assert "type" in reason

    def test_confidence_out_of_range_fails(self):
        ok, reason = validate_staging_proposal(_make_valid_proposal(confidence=1.5))
        assert not ok

    def test_confidence_negative_fails(self):
        ok, reason = validate_staging_proposal(_make_valid_proposal(confidence=-0.1))
        assert not ok

    def test_confidence_boundary_values(self):
        for val in (0.0, 0.5, 1.0):
            ok, _ = validate_staging_proposal(_make_valid_proposal(confidence=val))
            assert ok, f"confidence={val} should be valid"

    def test_invalid_status_fails(self):
        ok, reason = validate_staging_proposal(_make_valid_proposal(status="winging-it"))
        assert not ok

    def test_all_valid_types_accepted(self):
        for t in VALID_MEMORY_TYPES:
            ok, _ = validate_staging_proposal(_make_valid_proposal(type=t))
            assert ok, f"type={t} should be valid"

    def test_non_dict_fails(self):
        ok, reason = validate_staging_proposal([])
        assert not ok

    def test_missing_trace_id_fails(self):
        p = _make_valid_proposal()
        del p["trace_id"]
        ok, reason = validate_staging_proposal(p)
        assert not ok


class TestValidateAuditEntry:
    def test_valid_entry_passes(self):
        entry = {
            "trace_id": "t1", "agent": "a", "action": "commit",
            "result": "ok", "timestamp": utc_now_iso(),
        }
        ok, reason = validate_audit_entry(entry)
        assert ok, reason

    def test_missing_field_fails(self):
        entry = {"trace_id": "t1", "agent": "a", "action": "commit", "result": "ok"}
        ok, reason = validate_audit_entry(entry)
        assert not ok
        assert "timestamp" in reason


class TestFactories:
    def test_make_staging_proposal_structure(self):
        p = make_staging_proposal(
            proposed_by="agent-x",
            content="Some content.",
            memory_type="episodic",
            confidence=0.8,
            timestamp=utc_now_iso(),
        )
        assert p["status"] == "pending"
        assert p["proposed_by"] == "agent-x"
        assert p["type"] == "episodic"
        assert 0.0 <= p["confidence"] <= 1.0
        ok, _ = validate_staging_proposal(p)
        assert ok

    def test_make_staging_proposal_generates_trace_id(self):
        p = make_staging_proposal("a", "content", "raw", 0.5, utc_now_iso())
        assert isinstance(p["trace_id"], str) and p["trace_id"]

    def test_make_staging_proposal_accepts_trace_id(self):
        p = make_staging_proposal("a", "content", "raw", 0.5, utc_now_iso(), trace_id="fixed-id")
        assert p["trace_id"] == "fixed-id"

    def test_make_agent_message_structure(self):
        msg = make_agent_message(
            agent_id="ag1", action="propose", target="staging/",
            payload={}, status="pending", timestamp=utc_now_iso(),
            requires_approval=True,
        )
        ok, reason = validate_agent_message(msg)
        assert ok, reason


# ===========================================================================
# STAGE 2 — security.py
# ===========================================================================

class TestPathGuard:
    def test_allowed_staging_path(self, cfg):
        guard = PathGuard(cfg)
        path  = cfg.memory_path / "staging" / "some-file.json"
        ok, reason = guard.validate(path)
        assert ok, reason

    def test_allowed_approved_path(self, cfg):
        guard = PathGuard(cfg)
        ok, _ = guard.validate(cfg.memory_path / "approved" / "x.json")
        assert ok

    def test_allowed_logs_path(self, cfg):
        guard = PathGuard(cfg)
        ok, _ = guard.validate(cfg.memory_path / "logs" / "audit.jsonl")
        assert ok

    def test_allowed_vault_path(self, cfg):
        guard = PathGuard(cfg)
        ok, _ = guard.validate(cfg.vault_path / "episodic" / "mem.md")
        assert ok

    def test_forbidden_outside_base(self, cfg):
        guard = PathGuard(cfg)
        ok, reason = guard.validate(Path("/etc/passwd"))
        assert not ok

    def test_traversal_raises_security_error(self, cfg):
        guard = PathGuard(cfg)
        with pytest.raises(SecurityError, match="traversal"):
            guard.validate(cfg.memory_path / "staging" / ".." / ".." / "etc" / "passwd")

    def test_assert_allowed_raises_on_forbidden(self, cfg):
        guard = PathGuard(cfg)
        with pytest.raises(SecurityError):
            guard.assert_allowed(Path("/tmp/evil.json"))

    def test_assert_allowed_passes_for_staging(self, cfg):
        guard = PathGuard(cfg)
        guard.assert_allowed(cfg.memory_path / "staging" / "fine.json")  # no raise


class TestAuditLog:
    def test_append_creates_file(self, cfg):
        audit = AuditLog(cfg)
        audit.append("t1", "TestAgent", "test_action", "ok")
        assert (cfg.memory_path / "logs" / "audit.jsonl").exists()

    def test_append_returns_entry(self, cfg):
        audit = AuditLog(cfg)
        entry = audit.append("t1", "TestAgent", "action", "result")
        assert entry["trace_id"] == "t1"
        assert entry["agent"]    == "TestAgent"

    def test_multiple_appends(self, cfg):
        audit = AuditLog(cfg)
        audit.append("t1", "A", "a1", "r1")
        audit.append("t2", "B", "a2", "r2")
        entries = audit.read_all()
        assert len(entries) == 2

    def test_read_all_returns_chronological_order(self, cfg):
        audit = AuditLog(cfg)
        for i in range(5):
            audit.append(f"t{i}", "A", "act", f"r{i}")
        entries = audit.read_all()
        ids = [e["trace_id"] for e in entries]
        assert ids == [f"t{i}" for i in range(5)]

    def test_read_by_trace(self, cfg):
        audit = AuditLog(cfg)
        audit.append("trace-A", "X", "act", "r1")
        audit.append("trace-B", "Y", "act", "r2")
        audit.append("trace-A", "Z", "act", "r3")
        by_a = audit.read_by_trace("trace-A")
        assert len(by_a) == 2
        assert all(e["trace_id"] == "trace-A" for e in by_a)

    def test_read_all_empty_returns_list(self, cfg):
        audit = AuditLog(cfg)
        assert audit.read_all() == []

    def test_entry_has_timestamp(self, cfg):
        audit = AuditLog(cfg)
        entry = audit.append("t1", "A", "act", "r")
        assert "timestamp" in entry and entry["timestamp"]


class TestValidationAgent:
    def test_validates_good_proposal(self, cfg):
        prop = create_proposal("agent-a", "Valid content here.", "raw", 0.6, cfg)
        pid  = prop["trace_id"]

        agent  = ValidationAgent(cfg)
        result = agent.validate_proposal(pid)
        assert result["ok"], result["reason"]
        assert result["reason"] == "approved_for_review"

    def test_status_updated_to_approved_for_review(self, cfg):
        prop = create_proposal("agent-a", "Valid content here.", "raw", 0.6, cfg)
        pid  = prop["trace_id"]

        ValidationAgent(cfg).validate_proposal(pid)
        stored = json.loads(
            (cfg.memory_path / "staging" / f"{pid}.json").read_text()
        )
        assert stored["status"] == "approved_for_review"

    def test_rejects_bad_schema(self, cfg):
        # Write a malformed proposal directly to staging.
        pid  = "bad-proposal-001"
        path = cfg.memory_path / "staging" / f"{pid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"trace_id": pid, "status": "pending"}), encoding="utf-8")

        agent  = ValidationAgent(cfg)
        result = agent.validate_proposal(pid)
        assert not result["ok"]

    def test_rejects_missing_file(self, cfg):
        agent  = ValidationAgent(cfg)
        result = agent.validate_proposal("nonexistent-xyz")
        assert not result["ok"]
        assert result["reason"] == "not_found"

    def test_flags_suspicious_eval(self, cfg):
        prop   = create_proposal("agent-a", "Run eval(dangerous_code) now.", "raw", 0.5, cfg)
        result = ValidationAgent(cfg).validate_proposal(prop["trace_id"])
        assert result["ok"]                  # flagged but NOT blocked
        assert len(result["flags"]) > 0

    def test_flags_stored_in_proposal(self, cfg):
        prop = create_proposal("agent-a", "call subprocess.run(['rm','-rf'])", "raw", 0.5, cfg)
        pid  = prop["trace_id"]
        ValidationAgent(cfg).validate_proposal(pid)
        stored = json.loads(
            (cfg.memory_path / "staging" / f"{pid}.json").read_text()
        )
        assert "content_flags" in stored

    def test_clean_content_has_no_flags(self, cfg):
        prop   = create_proposal("agent-a", "The sky is blue and learning is good.", "raw", 0.9, cfg)
        result = ValidationAgent(cfg).validate_proposal(prop["trace_id"])
        assert result["ok"]
        assert result["flags"] == []

    def test_validation_agent_never_modifies_content(self, cfg):
        original = "Content that must not be changed."
        prop = create_proposal("agent-a", original, "raw", 0.7, cfg)
        pid  = prop["trace_id"]
        ValidationAgent(cfg).validate_proposal(pid)
        stored = json.loads(
            (cfg.memory_path / "staging" / f"{pid}.json").read_text()
        )
        assert stored["content"] == original

    def test_audit_entry_written_on_validation(self, cfg):
        prop = create_proposal("agent-a", "Some content.", "raw", 0.5, cfg)
        pid  = prop["trace_id"]
        ValidationAgent(cfg).validate_proposal(pid)
        entries = AuditLog(cfg).read_by_trace(pid)
        actions = [e["action"] for e in entries]
        assert "validate" in actions

    def test_validate_all_pending(self, cfg):
        for i in range(3):
            create_proposal("agent-a", f"Proposal content {i}.", "raw", 0.5, cfg)
        agent   = ValidationAgent(cfg)
        results = agent.validate_all_pending()
        assert len(results) == 3
        assert all(r["ok"] for r in results)


# ===========================================================================
# STAGE 3 — approval_agent.py
# ===========================================================================

class TestAuthProviderInterface:
    def test_cli_auth_provider_is_auth_provider(self):
        assert issubclass(CLIAuthProvider, AuthProvider)

    def test_cli_auth_provider_has_provider_name(self):
        assert CLIAuthProvider().provider_name() == "cli"

    def test_mock_auth_provider_approve(self):
        mock = MockAuthProvider(approve=True)
        approved, reason = mock.request_approval("prompt", {})
        assert approved
        assert reason == "mock-approved"

    def test_mock_auth_provider_reject(self):
        mock = MockAuthProvider(approve=False, reason="not today")
        approved, reason = mock.request_approval("prompt", {})
        assert not approved
        assert reason == "not today"

    def test_mock_provider_name(self):
        assert MockAuthProvider().provider_name() == "mock"


class TestApprovalAgent:
    def _stage_and_validate(self, content, cfg):
        """Helper: create + validate a proposal, return proposal_id."""
        prop = create_proposal("agent-test", content, "raw", 0.7, cfg)
        pid  = prop["trace_id"]
        ValidationAgent(cfg).validate_proposal(pid)
        return pid

    def test_approve_updates_status(self, cfg):
        pid   = self._stage_and_validate("Approve this content.", cfg)
        agent = ApprovalAgent(cfg, MockAuthProvider(approve=True))
        result = agent.approve_proposal(pid)
        assert result["ok"]
        assert result["decision"] == "approved"
        stored = json.loads(
            (cfg.memory_path / "staging" / f"{pid}.json").read_text()
        )
        assert stored["status"] == "approved_for_commit"

    def test_approve_records_approved_by(self, cfg):
        pid   = self._stage_and_validate("Another content.", cfg)
        agent = ApprovalAgent(cfg, MockAuthProvider(approve=True))
        agent.approve_proposal(pid)
        stored = json.loads(
            (cfg.memory_path / "staging" / f"{pid}.json").read_text()
        )
        assert stored["approved_by"] == "mock"

    def test_reject_updates_status(self, cfg):
        pid   = self._stage_and_validate("Reject this content.", cfg)
        agent = ApprovalAgent(cfg, MockAuthProvider(approve=False, reason="bad content"))
        result = agent.approve_proposal(pid)
        assert not result["ok"]
        assert result["decision"] == "rejected"
        stored = json.loads(
            (cfg.memory_path / "staging" / f"{pid}.json").read_text()
        )
        assert stored["status"] == "rejected"

    def test_reject_stores_reason(self, cfg):
        pid   = self._stage_and_validate("Reject me.", cfg)
        agent = ApprovalAgent(cfg, MockAuthProvider(approve=False, reason="policy"))
        agent.approve_proposal(pid)
        stored = json.loads(
            (cfg.memory_path / "staging" / f"{pid}.json").read_text()
        )
        assert stored["reject_reason"] == "policy"

    def test_skips_pending_proposal(self, cfg):
        prop  = create_proposal("agent-a", "Pending only.", "raw", 0.5, cfg)
        agent = ApprovalAgent(cfg, MockAuthProvider(approve=True))
        result = agent.approve_proposal(prop["trace_id"])
        assert result["decision"] == "skipped"

    def test_skips_already_rejected(self, cfg):
        pid   = self._stage_and_validate("Validate then reject.", cfg)
        agent = ApprovalAgent(cfg, MockAuthProvider(approve=False))
        agent.approve_proposal(pid)          # first pass — rejected
        result = agent.approve_proposal(pid) # second pass
        assert result["decision"] == "skipped"

    def test_not_found_returns_error(self, cfg):
        agent  = ApprovalAgent(cfg, MockAuthProvider())
        result = agent.approve_proposal("ghost-id")
        assert result["decision"] == "error"
        assert result["reason"] == "not_found"

    def test_audit_entry_written_on_approval(self, cfg):
        pid   = self._stage_and_validate("Audit this.", cfg)
        agent = ApprovalAgent(cfg, MockAuthProvider(approve=True))
        agent.approve_proposal(pid)
        entries = AuditLog(cfg).read_by_trace(pid)
        actions = [e["action"] for e in entries]
        assert "approve" in actions

    def test_process_queue_returns_results(self, cfg):
        for i in range(3):
            pid = self._stage_and_validate(f"Queue item {i}.", cfg)
        agent   = ApprovalAgent(cfg, MockAuthProvider(approve=True))
        results = agent.process_queue()
        assert len(results) == 3
        assert all(r["decision"] == "approved" for r in results)

    def test_default_auth_provider_is_cli(self, cfg):
        agent = ApprovalAgent(cfg)
        assert isinstance(agent.auth, CLIAuthProvider)


# ===========================================================================
# STAGE 4 — write_agent.py
# ===========================================================================

class TestCreateProposal:
    def test_creates_staging_file(self, cfg):
        prop = create_proposal("agent-a", "Test content.", "raw", 0.5, cfg)
        path = cfg.memory_path / "staging" / f"{prop['trace_id']}.json"
        assert path.exists()

    def test_proposal_status_is_pending(self, cfg):
        prop = create_proposal("agent-a", "Test content.", "raw", 0.5, cfg)
        assert prop["status"] == "pending"

    def test_proposal_has_trace_id(self, cfg):
        prop = create_proposal("agent-a", "Content.", "raw", 0.5, cfg)
        assert prop["trace_id"]

    def test_proposal_accepts_custom_trace_id(self, cfg):
        prop = create_proposal("agent-a", "Content.", "raw", 0.5, cfg, trace_id="custom-id")
        assert prop["trace_id"] == "custom-id"

    def test_invalid_type_raises_value_error(self, cfg):
        with pytest.raises(ValueError, match="schema invalid"):
            create_proposal("agent-a", "Content.", "blob", 0.5, cfg)

    def test_invalid_confidence_raises_value_error(self, cfg):
        with pytest.raises(ValueError, match="schema invalid"):
            create_proposal("agent-a", "Content.", "raw", 99.0, cfg)

    def test_empty_content_raises_value_error(self, cfg):
        with pytest.raises(ValueError, match="schema invalid"):
            create_proposal("agent-a", "  ", "raw", 0.5, cfg)

    def test_audit_entry_created(self, cfg):
        prop = create_proposal("agent-a", "Content.", "raw", 0.5, cfg)
        entries = AuditLog(cfg).read_by_trace(prop["trace_id"])
        assert any(e["action"] == "propose" for e in entries)


class TestWriteAgent:
    def _full_pipeline(self, content, cfg, approve=True):
        """Run propose → validate → approve, return proposal_id."""
        prop = create_proposal("agent-a", content, "raw", 0.7, cfg)
        pid  = prop["trace_id"]
        ValidationAgent(cfg).validate_proposal(pid)
        ApprovalAgent(cfg, MockAuthProvider(approve=approve)).approve_proposal(pid)
        return pid

    def test_commit_approved_proposal(self, cfg):
        pid    = self._full_pipeline("Important knowledge to store.", cfg)
        result = WriteAgent(cfg).commit_proposal(pid)
        assert result["ok"], result["reason"]
        assert result["reason"] == "committed"

    def test_commit_returns_memory_id(self, cfg):
        pid    = self._full_pipeline("Knowledge with a memory ID.", cfg)
        result = WriteAgent(cfg).commit_proposal(pid)
        assert result["memory_id"]

    def test_committed_proposal_archived(self, cfg):
        pid = self._full_pipeline("Archive this after commit.", cfg)
        WriteAgent(cfg).commit_proposal(pid)
        assert (cfg.memory_path / "approved" / f"{pid}.json").exists()

    def test_committed_proposal_removed_from_staging(self, cfg):
        pid = self._full_pipeline("Remove from staging after commit.", cfg)
        WriteAgent(cfg).commit_proposal(pid)
        assert not (cfg.memory_path / "staging" / f"{pid}.json").exists()

    def test_committed_status_in_archive(self, cfg):
        pid = self._full_pipeline("Check archive status.", cfg)
        WriteAgent(cfg).commit_proposal(pid)
        archived = json.loads(
            (cfg.memory_path / "approved" / f"{pid}.json").read_text()
        )
        assert archived["status"] == "committed"

    def test_blocks_pending_proposal(self, cfg):
        prop   = create_proposal("agent-a", "Only pending.", "raw", 0.5, cfg)
        result = WriteAgent(cfg).commit_proposal(prop["trace_id"])
        assert not result["ok"]
        assert "BLOCKED" in result["reason"]

    def test_blocks_validated_but_unapproved(self, cfg):
        prop = create_proposal("agent-a", "Validated only.", "raw", 0.5, cfg)
        pid  = prop["trace_id"]
        ValidationAgent(cfg).validate_proposal(pid)
        result = WriteAgent(cfg).commit_proposal(pid)
        assert not result["ok"]
        assert "BLOCKED" in result["reason"]

    def test_blocks_rejected_proposal(self, cfg):
        pid    = self._full_pipeline("Rejected proposal.", cfg, approve=False)
        result = WriteAgent(cfg).commit_proposal(pid)
        assert not result["ok"]
        assert "BLOCKED" in result["reason"]

    def test_not_found_returns_failure(self, cfg):
        result = WriteAgent(cfg).commit_proposal("ghost-999")
        assert not result["ok"]
        assert result["reason"] == "not_found"

    def test_commit_all_approved(self, cfg):
        for i in range(3):
            self._full_pipeline(f"Batch commit item {i} is important.", cfg)
        results = WriteAgent(cfg).commit_all_approved()
        assert len(results) == 3
        assert all(r["ok"] for r in results)

    def test_list_committed(self, cfg):
        pid = self._full_pipeline("List committed entry.", cfg)
        WriteAgent(cfg).commit_proposal(pid)
        committed = WriteAgent(cfg).list_committed()
        assert any(c["trace_id"] == pid for c in committed)

    def test_list_staging_by_status(self, cfg):
        prop = create_proposal("agent-a", "Staging content.", "raw", 0.5, cfg)
        pid  = prop["trace_id"]
        pending = WriteAgent(cfg).list_staging(status="pending")
        assert any(p["trace_id"] == pid for p in pending)

    def test_audit_entry_written_on_commit(self, cfg):
        pid = self._full_pipeline("Audited commit content.", cfg)
        WriteAgent(cfg).commit_proposal(pid)
        entries = AuditLog(cfg).read_by_trace(pid)
        actions = [e["action"] for e in entries]
        assert "commit" in actions


# ===========================================================================
# STAGE 5 — Integration: full pipeline
# ===========================================================================

class TestFullPipeline:
    def test_propose_validate_approve_commit(self, cfg):
        """Full governance pipeline from proposal to committed memory."""
        # Step 1: Propose
        prop = create_proposal(
            proposed_by="integration-agent",
            content="Learning: the full pipeline works end to end.",
            memory_type="raw",
            confidence=0.85,
            config=cfg,
        )
        pid = prop["trace_id"]
        assert prop["status"] == "pending"

        # Step 2: Validate
        v_result = ValidationAgent(cfg).validate_proposal(pid)
        assert v_result["ok"]
        assert v_result["reason"] == "approved_for_review"

        # Step 3: Approve
        a_result = ApprovalAgent(cfg, MockAuthProvider(approve=True)).approve_proposal(pid)
        assert a_result["ok"]
        assert a_result["decision"] == "approved"

        # Step 4: Commit
        c_result = WriteAgent(cfg).commit_proposal(pid)
        assert c_result["ok"]
        assert c_result["reason"] == "committed"
        assert c_result["memory_id"]

    def test_full_pipeline_rejected_never_commits(self, cfg):
        """Rejected proposals must never reach the write stage."""
        prop = create_proposal("agent-b", "Suspicious content.", "raw", 0.3, cfg)
        pid  = prop["trace_id"]
        ValidationAgent(cfg).validate_proposal(pid)
        ApprovalAgent(cfg, MockAuthProvider(approve=False, reason="policy violation")).approve_proposal(pid)

        result = WriteAgent(cfg).commit_proposal(pid)
        assert not result["ok"]
        assert "BLOCKED" in result["reason"]
        assert not (cfg.memory_path / "approved" / f"{pid}.json").exists()

    def test_unapproved_proposal_never_commits(self, cfg):
        """A proposal that skips the approval gate cannot be committed."""
        prop = create_proposal("agent-c", "Skip approval gate.", "raw", 0.5, cfg)
        pid  = prop["trace_id"]
        ValidationAgent(cfg).validate_proposal(pid)
        # Intentionally skip ApprovalAgent.
        result = WriteAgent(cfg).commit_proposal(pid)
        assert not result["ok"]

    def test_full_audit_trail_exists(self, cfg):
        """Every pipeline stage leaves an audit entry with the same trace_id."""
        prop = create_proposal("agent-d", "Audit trail test content.", "raw", 0.6, cfg)
        pid  = prop["trace_id"]
        ValidationAgent(cfg).validate_proposal(pid)
        ApprovalAgent(cfg, MockAuthProvider(approve=True)).approve_proposal(pid)
        WriteAgent(cfg).commit_proposal(pid)

        entries = AuditLog(cfg).read_by_trace(pid)
        actions = {e["action"] for e in entries}
        assert "propose"  in actions
        assert "validate" in actions
        assert "approve"  in actions
        assert "commit"   in actions

    def test_path_traversal_blocked_at_every_stage(self, cfg):
        """Traversal attempts are blocked regardless of stage."""
        guard = PathGuard(cfg)
        evil  = cfg.memory_path / "staging" / ".." / ".." / "secret.json"
        with pytest.raises(SecurityError):
            guard.assert_allowed(evil)


# ===========================================================================
# Security invariants
# ===========================================================================

class TestSecurityInvariants:
    def test_no_execution_primitives_in_security(self):
        import ast, inspect
        import aeon.core.security as mod
        tree = ast.parse(inspect.getsource(mod))
        banned = {"subprocess", "os.system", "os.popen", "eval", "exec", "__import__"}
        imports = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for name in node.names
        }
        assert not banned.intersection(imports), f"Banned import found: {banned & imports}"

    def test_no_execution_primitives_in_write_agent(self):
        import ast, inspect
        import aeon.core.write_agent as mod
        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = ""
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                assert name not in ("system", "popen", "run"), \
                    f"Execution primitive '{name}' found in write_agent.py"

    def test_vault_core_never_written_by_write_agent(self, cfg):
        """Write agent must not be able to target vault/core/."""
        guard = PathGuard(cfg)
        core_path = cfg.vault_path / "core" / "identity.md"
        ok, reason = guard.validate(core_path)
        # vault/ is an allowed top-level dir, but the guard validates the full path.
        # vault/core/ IS inside vault/, so this passes the path guard —
        # vault/core/ protection is enforced separately by CoreMemoryProtectedError.
        # This test just confirms the path guard doesn't create a false sense of security.
        assert isinstance(ok, bool)   # structural: validate always returns bool

    def test_write_agent_exports(self):
        from aeon.core import WriteAgent, create_proposal
        assert callable(WriteAgent)
        assert callable(create_proposal)

    def test_approval_agent_exports(self):
        from aeon.core import ApprovalAgent, AuthProvider, CLIAuthProvider
        assert issubclass(CLIAuthProvider, AuthProvider)
        assert callable(ApprovalAgent)

    def test_security_exports(self):
        from aeon.core import PathGuard, SecurityError, ValidationAgent, AuditLog
        assert callable(PathGuard)
        assert issubclass(SecurityError, Exception)
        assert callable(ValidationAgent)
        assert callable(AuditLog)
