"""ESP32-S3 USB hardware approval provider for Aeon-V1 Layer 7.

This module implements the AuthProvider extension point without changing
ApprovalAgent. It talks to a dedicated ESP32-S3 button token over USB CDC
serial using newline-delimited JSON.

SAFETY GUARANTEE
================
NO AUTO-APPROVAL is ever permitted. request_approval() returns True only after
an explicit approval message for the exact proposal id is received from the
hardware device. Button presses that are not tied to an armed request are ignored
by the firmware.
"""
import json
import time
from typing import Dict, Optional, Tuple

from .approval_agent import AuthProvider


class HardwareAuthError(RuntimeError):
    """Raised when the hardware auth provider cannot reach the USB token."""


class ESP32S3AuthProvider(AuthProvider):
    """Physical button approval provider for the ESP32-S3 auth device.

    Args:
        port: Serial port such as COM5, /dev/ttyACM0, or /dev/cu.usbmodem101.
              If omitted, the provider scans serial ports for a device that
              answers with device == "aeon-v1-auth".
        baudrate: USB CDC baudrate. The firmware accepts 115200 by convention.
        approval_timeout: Seconds to wait for the operator to hold the button.
        serial_timeout: Per-read timeout in seconds.
    """

    DEVICE_NAME = "aeon-v1-auth"

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = 115200,
        approval_timeout: float = 30.0,
        serial_timeout: float = 0.25,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.approval_timeout = approval_timeout
        self.serial_timeout = serial_timeout

    def provider_name(self) -> str:
        return "esp32_s3_usb_auth"

    def request_approval(self, prompt: str, context: Dict) -> Tuple[bool, str]:
        """Arm the hardware token and wait for physical button approval."""
        proposal_id = self._proposal_id(context)
        summary = self._summary(prompt, context)
        deadline = time.monotonic() + self.approval_timeout

        print("\n" + "=" * 62)
        print("  AEON-V1  -  HARDWARE APPROVAL REQUEST")
        print("=" * 62)
        print(f"  Proposal ID : {proposal_id}")
        print(f"  Provider    : {self.provider_name()}")
        print(f"  Port        : {self.port or 'auto-discover'}")
        print(f"  Prompt      : {prompt}")
        print("  Hold the ESP32-S3 auth button for one second to approve.")
        print("=" * 62)

        serial_mod = self._serial_module()
        port = self.port or self._discover_port(serial_mod)
        request = {
            "type": "approval_request",
            "id": proposal_id,
            "summary": summary,
            "expires_ms": int(self.approval_timeout * 1000),
        }

        with serial_mod.Serial(port, self.baudrate, timeout=self.serial_timeout) as ser:
            time.sleep(0.2)
            self._drain(ser)
            self._send(ser, request)

            while time.monotonic() < deadline:
                message = self._read_message(ser)
                if not message:
                    continue
                msg_type = message.get("type")
                msg_id = str(message.get("id", ""))

                if msg_type == "approval" and msg_id == proposal_id:
                    if message.get("approved") is True:
                        held_ms = message.get("held_ms", "unknown")
                        return True, f"approved via ESP32-S3 hardware token; held_ms={held_ms}"
                    return False, "hardware token returned non-approved decision"

                if msg_type == "expired" and msg_id == proposal_id:
                    return False, "hardware approval request expired"

                if msg_type == "error":
                    return False, f"hardware token error: {message.get('message', 'unknown')}"

            self._send(ser, {"type": "cancel", "id": proposal_id})
            return False, "hardware approval timed out"

    def _serial_module(self):
        try:
            import serial
            import serial.tools.list_ports
        except ImportError as exc:
            raise HardwareAuthError(
                "pyserial is required for ESP32S3AuthProvider. "
                "Install it with: pip install pyserial"
            ) from exc
        return serial

    def _discover_port(self, serial_mod) -> str:
        for port_info in serial_mod.tools.list_ports.comports():
            candidate = port_info.device
            try:
                with serial_mod.Serial(candidate, self.baudrate, timeout=self.serial_timeout) as ser:
                    time.sleep(0.2)
                    self._drain(ser)
                    self._send(ser, {"type": "hello"})
                    deadline = time.monotonic() + 1.5
                    while time.monotonic() < deadline:
                        message = self._read_message(ser)
                        if message.get("type") == "hello" and message.get("device") == self.DEVICE_NAME:
                            return candidate
            except Exception:
                continue
        raise HardwareAuthError("No ESP32-S3 auth device found on available serial ports")

    def _proposal_id(self, context: Dict) -> str:
        for key in ("trace_id", "id", "proposal_id"):
            value = context.get(key)
            if value:
                return str(value)[:64]
        return "unknown-proposal"

    def _summary(self, prompt: str, context: Dict) -> str:
        content = str(context.get("content", ""))
        preview = content.replace("\r", " ").replace("\n", " ")[:80]
        parts = [
            prompt,
            f"type={context.get('type', 'unknown')}",
            f"confidence={context.get('confidence', 'unknown')}",
        ]
        if preview:
            parts.append(f"content={preview}")
        return " | ".join(parts)[:160]

    def _send(self, ser, message: Dict) -> None:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        ser.write(payload)
        ser.flush()

    def _read_message(self, ser) -> Dict:
        raw = ser.readline()
        if not raw:
            return {}
        try:
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                return {}
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    def _drain(self, ser) -> None:
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            if not ser.readline():
                break
