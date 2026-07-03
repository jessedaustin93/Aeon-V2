"""Tests for the ESP32-S3 hardware auth provider."""

from aeon.core import ESP32S3AuthProvider, HardwareAuthError
from aeon.core.approval_agent import AuthProvider


def test_esp32s3_provider_implements_auth_provider():
    provider = ESP32S3AuthProvider(port="COM9")

    assert isinstance(provider, AuthProvider)
    assert provider.provider_name() == "esp32_s3_usb_auth"


def test_esp32s3_provider_uses_trace_id_first():
    provider = ESP32S3AuthProvider()

    proposal_id = provider._proposal_id({"trace_id": "abc123", "id": "fallback"})

    assert proposal_id == "abc123"


def test_esp32s3_provider_limits_proposal_id_length():
    provider = ESP32S3AuthProvider()

    proposal_id = provider._proposal_id({"trace_id": "x" * 80})

    assert proposal_id == "x" * 64


def test_esp32s3_summary_includes_prompt_and_context():
    provider = ESP32S3AuthProvider()

    summary = provider._summary(
        "Approve write?",
        {"type": "semantic", "confidence": 0.9, "content": "hello\nworld"},
    )

    assert "Approve write?" in summary
    assert "type=semantic" in summary
    assert "confidence=0.9" in summary
    assert "hello world" in summary
    assert len(summary) <= 160


def test_hardware_auth_error_is_runtime_error():
    assert issubclass(HardwareAuthError, RuntimeError)
