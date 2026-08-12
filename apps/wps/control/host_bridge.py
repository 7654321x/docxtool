"""Thread-safe long-poll bridge between the WPS Host and TaskPane."""

from __future__ import annotations

from copy import deepcopy
import threading
import time
from typing import Any, Dict, Optional


ALLOWED_COMMANDS = frozenset(
    {"preview", "apply", "clear_preview", "health", "panel_ready"}
)


class HostBridgeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class HostBridge:
    """Coordinate one active Host, one command slot, and revisioned UI state."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._closed = False
        self._host_context_id = ""
        self._host_generation = 0
        self._command_sequence = 0
        self._command: Optional[Dict[str, Any]] = None
        self._command_delivered = False
        self._state_revision = 1
        self._state: Dict[str, Any] = {
            "host_ready": False,
            "status": "NOT_READY",
            "stage": "host_waiting",
            "message": "WPS Host 尚未连接",
            "error_code": "",
            "active_request": None,
            "last_request": None,
        }

    def register_host(self, host_context_id: str) -> Dict[str, Any]:
        context = self._required_text(
            host_context_id, "WPS_HOST_CONTEXT_REQUIRED", maximum=160
        )
        with self._condition:
            self._require_open()
            if context == self._host_context_id:
                return {
                    "host_generation": self._host_generation,
                    "state_revision": self._state_revision,
                    "replaced": False,
                    "displaced_command": None,
                }

            replaced = bool(self._host_context_id)
            previous_command = deepcopy(self._command) if self._command else None
            previous_delivered = self._command_delivered
            previous_request_id = (
                str(previous_command.get("request_id", ""))
                if previous_command
                else ""
            )
            self._host_context_id = context
            self._host_generation += 1
            self._command = None
            self._command_delivered = False
            self._state = {
                "host_ready": False,
                "status": "NOT_READY",
                "stage": "host_registering",
                "message": "WPS Host 正在连接",
                "error_code": "WPS_HOST_CONTEXT_REPLACED" if replaced else "",
                "active_request": None,
                "last_request": (
                    {
                        "request_id": previous_request_id,
                        "command": str(previous_command.get("command", "")),
                        "request_status": "FAIL",
                        "error_code": "WPS_HOST_CONTEXT_REPLACED",
                    }
                    if previous_request_id
                    else None
                ),
            }
            self._state_revision += 1
            self._condition.notify_all()
            return {
                "host_generation": self._host_generation,
                "state_revision": self._state_revision,
                "replaced": replaced,
                "displaced_command": (
                    {
                        "request_id": previous_request_id,
                        "command": str(previous_command.get("command", "")),
                        "command_sequence": int(
                            previous_command.get("command_sequence", 0)
                        ),
                        "delivered": previous_delivered,
                    }
                    if previous_command
                    else None
                ),
            }

    def enqueue_command(
        self,
        request_id: str,
        command: str,
        pane_instance_id: str,
        host_generation: int,
        authorization: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        request = self._required_text(
            request_id, "WPS_REQUEST_ID_MISSING", maximum=160
        )
        command_name = self._required_text(
            command, "WPS_REQUEST_COMMAND_MISSING", maximum=40
        )
        pane = self._required_text(
            pane_instance_id, "WPS_PANE_INSTANCE_ID_MISSING", maximum=160
        )
        if command_name not in ALLOWED_COMMANDS:
            raise HostBridgeError("WPS_REQUEST_COMMAND_INVALID")
        if command_name == "apply":
            if not isinstance(authorization, dict):
                raise HostBridgeError("WPS_APPLY_AUTHORIZATION_REQUIRED")
            if authorization.get("request_id") != request:
                raise HostBridgeError("WPS_APPLY_AUTHORIZATION_MISMATCH")
            if not isinstance(authorization.get("config_version"), str) or not authorization["config_version"]:
                raise HostBridgeError("WPS_APPLY_CONFIG_VERSION_REQUIRED")
        with self._condition:
            self._require_open()
            self._require_generation(host_generation)
            if self._state.get("host_ready") is not True:
                raise HostBridgeError("WPS_HOST_NOT_READY")
            if self._command is not None:
                raise HostBridgeError("WPS_COMMAND_BUSY")
            self._command_sequence += 1
            self._command = {
                "schema_version": "wps-command-v2",
                "request_id": request,
                "command": command_name,
                "pane_instance_id": pane,
                "command_sequence": self._command_sequence,
                "host_generation": self._host_generation,
            }
            if command_name == "apply":
                self._command["authorization"] = {
                    "request_id": request,
                    "config_version": authorization["config_version"],
                }
            self._command_delivered = False
            self._state_revision += 1
            self._condition.notify_all()
            return {
                "request_id": request,
                "command_sequence": self._command_sequence,
                "state_revision": self._state_revision,
            }

    def ensure_command_available(self, host_generation: int) -> None:
        """Fail before external authorization when the bridge cannot accept work."""
        with self._condition:
            self._require_open()
            self._require_generation(host_generation)
            if self._state.get("host_ready") is not True:
                raise HostBridgeError("WPS_HOST_NOT_READY")
            if self._command is not None:
                raise HostBridgeError("WPS_COMMAND_BUSY")

    def validate_host(
        self, host_context_id: str, host_generation: int
    ) -> Dict[str, int]:
        context = self._required_text(
            host_context_id, "WPS_HOST_CONTEXT_REQUIRED", maximum=160
        )
        with self._condition:
            self._require_open()
            self._require_host(context, host_generation)
            return {
                "host_generation": self._host_generation,
                "state_revision": self._state_revision,
            }

    def wait_command(
        self,
        host_context_id: str,
        host_generation: int,
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        context = self._required_text(
            host_context_id, "WPS_HOST_CONTEXT_REQUIRED", maximum=160
        )
        timeout = self._valid_timeout(timeout_seconds)
        with self._condition:
            self._require_open()
            self._require_host(context, host_generation)
            deadline = time.monotonic() + timeout
            while True:
                self._require_open()
                if (
                    context != self._host_context_id
                    or host_generation != self._host_generation
                ):
                    raise HostBridgeError("WPS_HOST_CONTEXT_REPLACED")
                if self._command is not None and not self._command_delivered:
                    self._command_delivered = True
                    return {
                        "timed_out": False,
                        "command": deepcopy(self._command),
                    }
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"timed_out": True, "command": None}
                self._condition.wait(remaining)

    def publish_state(
        self,
        host_context_id: str,
        host_generation: int,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = self._required_text(
            host_context_id, "WPS_HOST_CONTEXT_REQUIRED", maximum=160
        )
        if not isinstance(state, dict):
            raise HostBridgeError("WPS_BRIDGE_STATE_OBJECT_REQUIRED")
        with self._condition:
            self._require_open()
            self._require_host(context, host_generation)
            self._state = deepcopy(state)
            self._state_revision += 1
            if self._command is not None and self._state_completes_command(state):
                self._command = None
                self._command_delivered = False
            self._condition.notify_all()
            return {
                "host_generation": self._host_generation,
                "state_revision": self._state_revision,
            }

    def wait_state(
        self,
        after_revision: int,
        host_generation: int,
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        revision = self._valid_nonnegative_int(
            after_revision, "WPS_BRIDGE_STATE_REVISION_INVALID"
        )
        generation = self._valid_nonnegative_int(
            host_generation, "WPS_HOST_GENERATION_INVALID"
        )
        timeout = self._valid_timeout(timeout_seconds)
        with self._condition:
            self._require_open()
            deadline = time.monotonic() + timeout
            while True:
                self._require_open()
                generation_changed = bool(
                    generation and generation != self._host_generation
                )
                if generation_changed or revision < self._state_revision:
                    return self._state_result(False, generation_changed)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._state_result(True, False)
                self._condition.wait(remaining)

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()

    def _state_result(
        self, timed_out: bool, generation_changed: bool
    ) -> Dict[str, Any]:
        return {
            "timed_out": timed_out,
            "generation_changed": generation_changed,
            "host_generation": self._host_generation,
            "state_revision": self._state_revision,
            "state": deepcopy(self._state),
        }

    def _state_completes_command(self, state: Dict[str, Any]) -> bool:
        if self._command is None:
            return False
        request_id = str(self._command.get("request_id", ""))
        for key in ("active_request", "last_request"):
            value = state.get(key)
            if not isinstance(value, dict):
                continue
            if (
                value.get("request_id") == request_id
                and value.get("request_status") in {"PASS", "FAIL"}
            ):
                return True
        return False

    def _require_host(self, host_context_id: str, host_generation: int) -> None:
        if host_context_id != self._host_context_id:
            raise HostBridgeError("WPS_HOST_CONTEXT_MISMATCH")
        self._require_generation(host_generation)

    def _require_generation(self, host_generation: int) -> None:
        generation = self._valid_nonnegative_int(
            host_generation, "WPS_HOST_GENERATION_INVALID"
        )
        if not self._host_context_id:
            raise HostBridgeError("WPS_HOST_NOT_REGISTERED")
        if generation != self._host_generation:
            raise HostBridgeError("WPS_HOST_GENERATION_MISMATCH")

    def _require_open(self) -> None:
        if self._closed:
            raise HostBridgeError("WPS_BRIDGE_CLOSED")

    @staticmethod
    def _required_text(value: object, code: str, maximum: int) -> str:
        if not isinstance(value, str) or not value or len(value) > maximum:
            raise HostBridgeError(code)
        return value

    @staticmethod
    def _valid_nonnegative_int(value: object, code: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise HostBridgeError(code)
        return value

    @staticmethod
    def _valid_timeout(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HostBridgeError("WPS_BRIDGE_WAIT_TIMEOUT_INVALID")
        timeout = float(value)
        if timeout < 0 or timeout > 25:
            raise HostBridgeError("WPS_BRIDGE_WAIT_TIMEOUT_INVALID")
        return timeout
