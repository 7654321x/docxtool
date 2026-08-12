"""Loopback-only WPS control server.

The server exposes lifecycle orchestration only. Recognition and formatting are
executed by the existing DocxTool package in the same Python process.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from typing import Any, Dict, Optional

from docxtool.sdk import RecognitionPlan
from docxtool.document.style_config import ConfigValidationError, validate_format_config
from docxtool.version import package_version

from .document_transaction import DocumentTransactionError, DocumentTransactionManager
from .host_bridge import HostBridge, HostBridgeError
from .logging_adapter import configure_wps_logging, log_event, sanitize_wps_log_fields
from .monitor import CommandMonitor
from .recognize_document import bind_preview, recognize_document

HOST = "127.0.0.1"
DEFAULT_PORT = 0
# HostSnapshot intentionally carries the current document's raw paragraph text
# to the local Binder. Keep a hard cap, but size it for large office documents.
MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_RECOGNITION_PLANS = 8
BUSINESS_ROUTES = frozenset(
    {
        "/v1/recognize",
        "/v1/recognize/bind",
        "/v1/format/upgrade/reserve",
        "/v1/format/upgrade/prepare",
        "/v1/format/upgrade/prepare-converted",
        "/v1/format/prepare",
        "/v1/format/commit",
        "/v1/format/finalize",
        "/v1/format/rollback",
    }
)
BRIDGE_ROUTES = frozenset(
    {
        "/v1/bridge/host/register",
        "/v1/bridge/host/wait",
        "/v1/bridge/command",
        "/v1/bridge/state",
        "/v1/bridge/state/wait",
    }
)
BRIDGE_WAIT_ROUTES = frozenset(
    {"/v1/bridge/host/wait", "/v1/bridge/state/wait"}
)


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", "")
    if isinstance(code, str) and code:
        return code
    text = str(error).strip()
    if text and text.upper() == text and len(text) <= 100:
        return text
    return "WPS_CONTROL_ERROR"


def _safe_warnings(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[Any] = []
    for item in value[:50]:
        if isinstance(item, str):
            result.append(item[:500])
        elif isinstance(item, dict):
            result.append(
                {
                    str(key)[:80]: raw
                    for key, raw in item.items()
                    if isinstance(raw, (str, int, float, bool)) or raw is None
                }
            )
    return result


def _safe_log_details(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return sanitize_wps_log_fields(value)


def _request_failure_event(code: str) -> str:
    return {
        "WPS_CONTROL_UNAUTHORIZED": "control.auth.rejected",
        "WPS_CONTROL_INVALID_CONTENT_LENGTH": "control.body.length_invalid",
        "WPS_CONTROL_NEGATIVE_CONTENT_LENGTH": "control.body.length_negative",
        "WPS_CONTROL_REQUEST_TOO_LARGE": "control.body.too_large",
        "WPS_CONTROL_BODY_TRUNCATED": "control.body.truncated",
        "WPS_CONTROL_JSON_INVALID": "control.body.json_invalid",
        "WPS_CONTROL_JSON_OBJECT_REQUIRED": "control.body.object_required",
        "WPS_CONTROL_ROUTE_NOT_FOUND": "control.route.not_found",
        "WPS_COMMAND_BUSY": "control.command.busy",
        "WPS_MONITOR_NOT_RUNNING": "control.monitor.unavailable",
        "WPS_HOST_NOT_REGISTERED": "bridge.host.not_registered",
        "WPS_HOST_NOT_READY": "bridge.host.not_ready",
        "WPS_HOST_CONTEXT_MISMATCH": "bridge.host.context_mismatch",
        "WPS_HOST_CONTEXT_REPLACED": "bridge.host.context_replaced",
        "WPS_HOST_CONTEXT_REQUIRED": "bridge.host.context_required",
        "WPS_HOST_GENERATION_MISMATCH": "bridge.host.generation_mismatch",
        "WPS_HOST_GENERATION_INVALID": "bridge.host.generation_invalid",
        "WPS_REQUEST_ID_MISSING": "bridge.command.request_id_missing",
        "WPS_REQUEST_COMMAND_MISSING": "bridge.command.command_missing",
        "WPS_REQUEST_COMMAND_INVALID": "bridge.command.invalid",
        "WPS_PANE_INSTANCE_ID_MISSING": "bridge.command.pane_instance_missing",
        "WPS_BRIDGE_STATE_OBJECT_REQUIRED": "bridge.state.object_required",
        "WPS_BRIDGE_STATE_REVISION_INVALID": "bridge.state.revision_invalid",
        "WPS_BRIDGE_CLOSED": "bridge.closed",
        "WPS_BRIDGE_WAIT_TIMEOUT_INVALID": "bridge.wait.timeout_invalid",
        "WPS_PUBLIC_ACCOUNT_REQUIRED": "public.account.required",
        "WPS_PUBLIC_AUTHORIZATION_REJECTED": "public.authorization.rejected",
        "WPS_APPLY_AUTHORIZATION_REQUIRED": "bridge.command.authorization_required",
        "WPS_APPLY_AUTHORIZATION_MISMATCH": "bridge.command.authorization_mismatch",
        "WPS_APPLY_CONFIG_VERSION_REQUIRED": "bridge.command.config_version_required",
        "WPS_APPLY_FORMAT_CONFIG_REQUIRED": "bridge.command.format_config_required",
    }.get(code, "control.request.execution_failed")


class WpsControlHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type,
        monitor: CommandMonitor,
        host_bridge: HostBridge,
    ) -> None:
        self.command_monitor = monitor
        self.host_bridge = host_bridge
        super().__init__(server_address, handler)

    def server_close(self) -> None:
        self.host_bridge.close()
        log_event(
            "INFO",
            "bridge",
            "bridge.waiters.closed",
            "WPS 通信桥等待请求已关闭",
        )
        self.command_monitor.stop()
        super().server_close()


class WpsControlApplication:
    def __init__(self, app_root: Path, session_token: str, account_runtime=None) -> None:
        self.app_root = Path(app_root)
        self.session_token = session_token
        self.log_dir = configure_wps_logging(self.app_root)
        self.transactions = DocumentTransactionManager(self.log_dir)
        self.host_bridge = HostBridge()
        self.account_runtime = account_runtime
        self._authorization_lock = threading.RLock()
        self._authorized_requests: Dict[str, Dict[str, Any]] = {}
        self._plans: "OrderedDict[str, RecognitionPlan]" = OrderedDict()
        self._plans_lock = threading.RLock()

    def _remember_plan(self, plan: RecognitionPlan) -> None:
        with self._plans_lock:
            self._plans[plan.plan_id] = plan
            self._plans.move_to_end(plan.plan_id)
            while len(self._plans) > MAX_RECOGNITION_PLANS:
                self._plans.popitem(last=False)

    def _get_plan(self, plan_id: str) -> RecognitionPlan:
        with self._plans_lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                raise DocumentTransactionError("WPS_RECOGNITION_PLAN_NOT_FOUND")
            return plan

    def health(self) -> Dict[str, Any]:
        return {
            "status": "ready",
            "service": "docxtool-wps-control",
            "docxtool_version": package_version(),
            "host": HOST,
        }

    def account_summary(self) -> Dict[str, Any]:
        if self.account_runtime is None:
            return {
                "signed_in": False,
                "network_available": False,
                "apply_available": False,
                "pending_result_count": 0,
                "error_code": "WPS_PUBLIC_ACCOUNT_REQUIRED",
            }
        return {"signed_in": True, **self.account_runtime.summary()}

    def _authorize_apply(self, request_id: str) -> Dict[str, Any]:
        if self.account_runtime is None:
            raise DocumentTransactionError("WPS_PUBLIC_ACCOUNT_REQUIRED")
        result = self.account_runtime.authorize_format(request_id)
        if result.get("allowed") is not True:
            raise DocumentTransactionError("WPS_PUBLIC_AUTHORIZATION_REJECTED")
        config = result.get("format_config")
        if not isinstance(config, dict):
            raise DocumentTransactionError("WPS_APPLY_FORMAT_CONFIG_REQUIRED")
        try:
            validated = validate_format_config(config)
        except ConfigValidationError as exc:
            log_event(
                "ERROR",
                "public",
                "public.format.config.validation_failed",
                "公网下发的排版配置校验失败",
                {"request_id": request_id, "error_code": exc.code},
            )
            raise
        return {
            "request_id": request_id,
            "config_version": str(result.get("config_version", "")),
            "format_config": validated,
        }

    def _claim_apply_authorization(self, request_id: str) -> Dict[str, Any]:
        with self._authorization_lock:
            pending = self._authorized_requests.get(request_id)
            if pending is None:
                raise DocumentTransactionError("WPS_APPLY_AUTHORIZATION_REQUIRED")
            if pending["state"] != "authorized":
                raise DocumentTransactionError("WPS_APPLY_AUTHORIZATION_CONSUMED")
            pending["state"] = "starting"
            return deepcopy(pending["format_config"])

    def _bind_apply_operation(self, request_id: str, operation_id: str) -> None:
        with self._authorization_lock:
            pending = self._authorized_requests.get(request_id)
            if pending is None:
                raise DocumentTransactionError("WPS_APPLY_AUTHORIZATION_REQUIRED")
            if pending["state"] != "starting":
                raise DocumentTransactionError("WPS_APPLY_AUTHORIZATION_CONSUMED")
            pending["state"] = "executing"
            pending["operation_id"] = operation_id

    def _require_apply_operation(
        self, request_id: str, operation_id: str
    ) -> Dict[str, Any]:
        with self._authorization_lock:
            pending = self._authorized_requests.get(request_id)
            if pending is None:
                raise DocumentTransactionError("WPS_APPLY_AUTHORIZATION_REQUIRED")
            if (
                pending["state"] != "executing"
                or pending["operation_id"] != operation_id
            ):
                raise DocumentTransactionError("WPS_APPLY_OPERATION_MISMATCH")
            return deepcopy(pending["format_config"])

    def _discard_unbound_operation(
        self, operation_id: str, request_id: str
    ) -> None:
        try:
            self.transactions.rollback(operation_id, request_id=request_id)
        except Exception as exc:
            log_event(
                "ERROR",
                "transaction",
                "transaction.unbound.cleanup.failed",
                "授权上下文失效后清理未绑定事务失败",
                {
                    "operation_id_short": operation_id[:12],
                    "request_id": request_id,
                    "error_code": _error_code(exc),
                    "error_type": type(exc).__name__,
                },
            )

    def _queue_completed_authorization(
        self, state: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        completed = None
        for key in ("active_request", "last_request"):
            candidate = state.get(key)
            if isinstance(candidate, dict) and candidate.get("request_status") in {"PASS", "FAIL"}:
                completed = candidate
                break
        if completed is None or completed.get("command") != "apply":
            return None
        request_id = str(completed.get("request_id", ""))
        pending = self._authorized_requests.get(request_id)
        if pending is None or self.account_runtime is None:
            return None
        duration_ms = completed.get("duration_ms")
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
            duration_ms = int((time.monotonic() - pending["started_at"]) * 1000)
        status = "success" if completed["request_status"] == "PASS" else "failed"
        error_code = "" if status == "success" else str(completed.get("error_code", "WPS_COMMAND_FAILED"))
        if status == "failed":
            self.transactions.rollback_request(request_id)
        self.account_runtime.report_format_result(
            request_id, status, duration_ms, error_code
        )
        self._authorized_requests.pop(request_id, None)
        log_event(
            "INFO",
            "public",
            "public.format.result.queued",
            "WPS 排版结果已进入公网补报队列",
            {
                "request_id": request_id,
                "request_status": status,
                "duration_ms": duration_ms,
            },
        )
        return {"result_sync_status": "pending", "result_sync_error_code": ""}

    def dispatch_bridge(
        self,
        path: str,
        body: Dict[str, Any],
        request_id: str = "",
    ) -> Dict[str, Any]:
        if path == "/v1/bridge/host/register":
            with self._authorization_lock:
                result = self.host_bridge.register_host(body.get("host_context_id"))
                displaced = result.get("displaced_command")
                if (
                    isinstance(displaced, dict)
                    and displaced.get("command") == "apply"
                ):
                    displaced_id = str(displaced.get("request_id", ""))
                    pending = self._authorized_requests.get(displaced_id)
                    if pending is not None and self.account_runtime is not None:
                        duration_ms = int(
                            (time.monotonic() - pending["started_at"]) * 1000
                        )
                        self.account_runtime.report_format_result(
                            displaced_id,
                            "failed",
                            duration_ms,
                            "WPS_HOST_CONTEXT_REPLACED",
                        )
                        self._authorized_requests.pop(displaced_id, None)
                        log_event(
                            "WARNING",
                            "public",
                            "public.format.result.queued.host_replaced",
                            "Host 更换导致排版请求失败，结果已进入补报队列",
                            {
                                "request_id": displaced_id,
                                "request_status": "failed",
                                "duration_ms": duration_ms,
                                "error_code": "WPS_HOST_CONTEXT_REPLACED",
                            },
                        )
            log_event(
                "INFO",
                "bridge",
                (
                    "bridge.host.replaced"
                    if result["replaced"]
                    else "bridge.host.registered"
                ),
                "WPS Host 通信上下文已注册",
                {
                    "request_id": request_id,
                    "host_generation": result["host_generation"],
                    "state_revision": result["state_revision"],
                    "replaced": result["replaced"],
                },
            )
            return result
        if path == "/v1/bridge/host/wait":
            result = self.host_bridge.wait_command(
                body.get("host_context_id"),
                body.get("host_generation"),
                body.get("timeout_seconds"),
            )
            command = result.get("command")
            if isinstance(command, dict):
                log_event(
                    "INFO",
                    "bridge",
                    "bridge.command.delivered",
                    "WPS Host 已领取通信桥命令",
                    {
                        "request_id": str(command.get("request_id", "")),
                        "command": str(command.get("command", "")),
                        "command_sequence": int(
                            command.get("command_sequence", 0)
                        ),
                        "host_generation": int(
                            command.get("host_generation", 0)
                        ),
                    },
                )
            return result
        if path == "/v1/bridge/command":
            command_name = body.get("command")
            authorization = None
            with self._authorization_lock:
                self.host_bridge.ensure_command_available(body.get("host_generation"))
                if command_name == "apply":
                    authorization = self._authorize_apply(str(body.get("request_id", "")))
                    log_event(
                        "INFO",
                        "public",
                        "public.format.authorize.allowed",
                        "WPS 一键排版已获得公网授权",
                        {"request_id": authorization["request_id"], "config_version": authorization["config_version"]},
                    )
                try:
                    host_authorization = None
                    if authorization is not None:
                        host_authorization = {
                            "request_id": authorization["request_id"],
                            "config_version": authorization["config_version"],
                        }
                        self._authorized_requests[authorization["request_id"]] = {
                            "started_at": time.monotonic(),
                            "config_version": authorization["config_version"],
                            "format_config": authorization["format_config"],
                            "host_generation": int(body.get("host_generation", 0)),
                            "state": "authorized",
                            "operation_id": "",
                        }
                    result = self.host_bridge.enqueue_command(
                        body.get("request_id"),
                        command_name,
                        body.get("pane_instance_id"),
                        body.get("host_generation"),
                        host_authorization,
                    )
                except HostBridgeError as exc:
                    if authorization is not None and self.account_runtime is not None:
                        self._authorized_requests.pop(
                            authorization["request_id"], None
                        )
                        try:
                            self.account_runtime.report_format_result(
                                authorization["request_id"], "failed", 0, _error_code(exc)
                            )
                        except Exception as report_error:
                            log_event(
                                "ERROR",
                                "public",
                                "public.format.result.failed",
                                "WPS 命令入槽失败，且失败结果未能回传公网服务",
                                {
                                    "request_id": authorization["request_id"],
                                    "primary_error_code": _error_code(exc),
                                    "error_code": _error_code(report_error),
                                    "error_type": type(report_error).__name__,
                                },
                            )
                    raise
            log_event(
                "INFO",
                "bridge",
                "bridge.command.enqueued",
                "任务窗格命令已进入通信桥",
                {
                    "request_id": result["request_id"],
                    "command": str(body.get("command", "")),
                    "command_sequence": result["command_sequence"],
                    "host_generation": int(body.get("host_generation", 0)),
                    "state_revision": result["state_revision"],
                },
            )
            return result
        if path == "/v1/bridge/state":
            state = body.get("state")
            with self._authorization_lock:
                self.host_bridge.validate_host(
                    body.get("host_context_id"), body.get("host_generation")
                )
                if isinstance(state, dict):
                    result_sync = self._queue_completed_authorization(state)
                else:
                    result_sync = None
                if result_sync is not None:
                    state = {**state, **result_sync}
                result = self.host_bridge.publish_state(
                    body.get("host_context_id"),
                    body.get("host_generation"),
                    state,
                )
            log_event(
                "INFO",
                "bridge",
                "bridge.state.published",
                "WPS Host 状态已发布到通信桥",
                {
                    "request_id": request_id,
                    "host_generation": result["host_generation"],
                    "state_revision": result["state_revision"],
                    "current_status": (
                        str(state.get("status", ""))
                        if isinstance(state, dict)
                        else ""
                    ),
                    "stage": (
                        str(state.get("stage", ""))
                        if isinstance(state, dict)
                        else ""
                    ),
                },
            )
            return result
        if path == "/v1/bridge/state/wait":
            result = self.host_bridge.wait_state(
                body.get("after_revision"),
                body.get("host_generation"),
                body.get("timeout_seconds"),
            )
            result["account"] = self.account_summary()
            return result
        raise DocumentTransactionError("WPS_CONTROL_ROUTE_NOT_FOUND")

    def dispatch(
        self,
        path: str,
        body: Dict[str, Any],
        request_id: str = "",
    ) -> Dict[str, Any]:
        if path == "/v1/recognize":
            started_at = time.monotonic()
            log_event(
                "INFO", "control", "recognize.request.start",
                "开始处理 WPS 识别请求", {"request_id": request_id},
            )
            try:
                session = recognize_document(
                    str(body.get("source_path", "")),
                    log_dir=self.log_dir,
                    format_config=(
                        body.get("format_config")
                        if isinstance(body.get("format_config"), dict)
                        else None
                    ),
                    request_id=request_id,
                )
                self._remember_plan(session.plan)
                result = session.public_result
            except Exception as exc:
                log_event(
                    "ERROR", "control", "recognize.request.failed",
                    "WPS 识别请求失败",
                    {
                        "request_id": request_id,
                        "duration_ms": int((time.monotonic() - started_at) * 1000),
                        "http_status": 400,
                        "error_code": _error_code(exc),
                        "error_type": type(exc).__name__,
                    },
                )
                raise
            log_event(
                "INFO", "control", "recognize.request.completed",
                "WPS 识别请求完成",
                {
                    "request_id": request_id,
                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                    "http_status": 200,
                    "block_count": int(result.get("block_count", 0)),
                },
            )
            return result
        if path == "/v1/recognize/bind":
            started_at = time.monotonic()
            log_event(
                "INFO", "control", "bind.request.start",
                "开始处理 WPS 绑定请求", {"request_id": request_id},
            )
            try:
                plan_id = str(body.get("plan_id", ""))
                host_snapshot = body.get("host_snapshot")
                if not isinstance(host_snapshot, dict):
                    raise DocumentTransactionError("WPS_HOST_SNAPSHOT_REQUIRED")
                result = bind_preview(
                    self._get_plan(plan_id), host_snapshot, request_id=request_id
                )
            except Exception as exc:
                log_event(
                    "ERROR", "control", "bind.request.failed",
                    "WPS 绑定请求失败",
                    {
                        "request_id": request_id,
                        "duration_ms": int((time.monotonic() - started_at) * 1000),
                        "http_status": 400,
                        "error_code": _error_code(exc),
                        "error_type": type(exc).__name__,
                    },
                )
                raise
            log_event(
                "INFO", "control", "bind.request.completed",
                "WPS 绑定请求完成",
                {
                    "request_id": request_id,
                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                    "http_status": 200,
                    "confirmed_count": int(result.get("confirmed_count", 0)),
                    "review_count": int(result.get("binding_review_count", 0)),
                    "preview_eligible_count": int(result.get("preview_eligible_count", 0)),
                    "skipped_count": int(result.get("unresolved_count", 0)),
                },
            )
            return result
        if path == "/v1/format/upgrade/reserve":
            started_at = time.monotonic()
            command = str(body.get("command", ""))
            log_event("INFO", "control", "format.upgrade.reserve.request.start", "开始预留旧格式升级事务", {"request_id": request_id, "stage": "format_upgrade_reserve"})
            try:
                if command == "apply":
                    self._claim_apply_authorization(request_id)
                operation = self.transactions.reserve_upgrade(
                    str(body.get("source_path", "")),
                    command=command,
                    request_id=request_id,
                )
                if command == "apply":
                    try:
                        self._bind_apply_operation(
                            request_id, operation.operation_id
                        )
                    except Exception:
                        self._discard_unbound_operation(
                            operation.operation_id, request_id
                        )
                        raise
            except Exception as exc:
                log_event("ERROR", "control", "format.upgrade.reserve.request.failed", "旧格式升级事务预留失败", {"request_id": request_id, "stage": "format_upgrade_reserve", "duration_ms": int((time.monotonic() - started_at) * 1000), "error_type": type(exc).__name__, "error_code": _error_code(exc)})
                raise
            log_event("INFO", "control", "format.upgrade.reserve.request.completed", "旧格式升级事务预留完成", {"request_id": request_id, "stage": "format_upgrade_reserve", "operation_id_short": operation.operation_id[:12], "duration_ms": int((time.monotonic() - started_at) * 1000)})
            return {
                "operation_id": operation.operation_id,
                "state": operation.state,
                "conversion_path": str(operation.conversion_path),
                "target_path": str(operation.target_path),
                "source_format": operation.source_path.suffix.lower().lstrip("."),
            }
        if path == "/v1/format/upgrade/prepare":
            started_at = time.monotonic()
            operation_id = str(body.get("operation_id", ""))
            log_event("INFO", "control", "format.upgrade.prepare.request.start", "开始处理旧格式升级排版请求", {"request_id": request_id, "stage": "format_upgrade_prepare", "operation_id_short": operation_id[:12]})
            try:
                format_config = self._require_apply_operation(
                    request_id, operation_id
                )
                operation = self.transactions.prepare_upgrade(
                    operation_id,
                    format_config,
                    request_id=request_id,
                )
            except Exception as exc:
                log_event("ERROR", "control", "format.upgrade.prepare.request.failed", "旧格式升级排版请求失败", {"request_id": request_id, "stage": "format_upgrade_prepare", "operation_id_short": operation_id[:12], "duration_ms": int((time.monotonic() - started_at) * 1000), "error_type": type(exc).__name__, "error_code": _error_code(exc)})
                raise
            result = operation.format_result
            if result is None:
                raise DocumentTransactionError("WPS_TRANSACTION_INVALID_STATE")
            log_event("INFO", "control", "format.upgrade.prepare.request.completed", "旧格式升级排版请求完成", {"request_id": request_id, "stage": "format_upgrade_prepare", "operation_id_short": operation.operation_id[:12], "log_file": result.log_path.name, "duration_ms": int((time.monotonic() - started_at) * 1000)})
            return {
                "operation_id": operation.operation_id,
                "state": operation.state,
                "document_mode": result.document_mode,
                "paragraph_count": result.paragraph_count,
                "heading_count": result.heading_count,
                "body_count": result.body_count,
                "compatibility_warnings": _safe_warnings(
                    result.export_stats.get("compatibility_warnings", [])
                ),
                "log_file": result.log_path.name,
            }
        if path == "/v1/format/upgrade/prepare-converted":
            started_at = time.monotonic()
            operation_id = str(body.get("operation_id", ""))
            log_event(
                "INFO",
                "control",
                "format.upgrade.prepare_converted.request.start",
                "开始准备原样发布 WPS 转换结果",
                {
                    "request_id": request_id,
                    "stage": "format_upgrade_prepare_converted",
                    "operation_id_short": operation_id[:12],
                },
            )
            try:
                operation = self.transactions.prepare_converted_upgrade(
                    operation_id,
                    request_id=request_id,
                )
            except Exception as exc:
                log_event(
                    "ERROR",
                    "control",
                    "format.upgrade.prepare_converted.request.failed",
                    "WPS 转换结果发布准备失败",
                    {
                        "request_id": request_id,
                        "stage": "format_upgrade_prepare_converted",
                        "operation_id_short": operation_id[:12],
                        "duration_ms": int(
                            (time.monotonic() - started_at) * 1000
                        ),
                        "error_type": type(exc).__name__,
                        "error_code": _error_code(exc),
                    },
                )
                raise
            log_event(
                "INFO",
                "control",
                "format.upgrade.prepare_converted.request.completed",
                "WPS 转换结果发布准备完成",
                {
                    "request_id": request_id,
                    "stage": "format_upgrade_prepare_converted",
                    "operation_id_short": operation.operation_id[:12],
                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                },
            )
            return {
                "operation_id": operation.operation_id,
                "state": operation.state,
            }
        if path == "/v1/format/prepare":
            started_at = time.monotonic()
            log_event("INFO", "control", "format.prepare.request.start", "开始处理 WPS 排版准备请求", {"request_id": request_id, "stage": "format_prepare"})
            try:
                format_config = self._claim_apply_authorization(request_id)
                operation = self.transactions.prepare(
                    str(body.get("source_path", "")),
                    format_config,
                    request_id=request_id,
                )
                try:
                    self._bind_apply_operation(request_id, operation.operation_id)
                except Exception:
                    self._discard_unbound_operation(
                        operation.operation_id, request_id
                    )
                    raise
            except Exception as exc:
                log_event("ERROR", "control", "format.prepare.request.failed", "WPS 排版准备请求失败", {"request_id": request_id, "stage": "format_prepare", "duration_ms": int((time.monotonic() - started_at) * 1000), "error_type": type(exc).__name__, "error_code": _error_code(exc)})
                raise
            result = operation.format_result
            if result is None:
                raise DocumentTransactionError("WPS_TRANSACTION_INVALID_STATE")
            log_event("INFO", "control", "format.prepare.request.completed", "WPS 排版准备请求完成", {"request_id": request_id, "stage": "format_prepare", "operation_id_short": operation.operation_id[:12], "log_file": result.log_path.name, "duration_ms": int((time.monotonic() - started_at) * 1000)})
            return {
                "operation_id": operation.operation_id,
                "state": operation.state,
                "document_mode": result.document_mode,
                "paragraph_count": result.paragraph_count,
                "heading_count": result.heading_count,
                "body_count": result.body_count,
                "compatibility_warnings": _safe_warnings(
                    result.export_stats.get("compatibility_warnings", [])
                ),
                "log_file": result.log_path.name,
            }
        if path == "/v1/format/commit":
            started_at = time.monotonic()
            operation_id = str(body.get("operation_id", ""))
            log_event("INFO", "control", "format.commit.request.start", "开始处理 WPS 排版提交请求", {"request_id": request_id, "stage": "format_commit", "operation_id_short": operation_id[:12]})
            try:
                existing = self.transactions.get(operation_id, request_id)
                if existing.command == "apply":
                    self._require_apply_operation(request_id, operation_id)
                operation = self.transactions.commit(operation_id, request_id=request_id)
            except Exception as exc:
                log_event("ERROR", "control", "format.commit.request.failed", "WPS 排版提交请求失败", {"request_id": request_id, "stage": "format_commit", "operation_id_short": operation_id[:12], "duration_ms": int((time.monotonic() - started_at) * 1000), "error_type": type(exc).__name__, "error_code": _error_code(exc)})
                raise
            log_event("INFO", "control", "format.commit.request.completed", "WPS 排版提交请求完成", {"request_id": request_id, "stage": "format_commit", "operation_id_short": operation_id[:12], "duration_ms": int((time.monotonic() - started_at) * 1000)})
            return {"operation_id": operation.operation_id, "state": operation.state}
        if path == "/v1/format/finalize":
            operation_id = str(body.get("operation_id", ""))
            started_at = time.monotonic()
            log_event("INFO", "control", "format.finalize.request.start", "开始处理 WPS 排版完成请求", {"request_id": request_id, "stage": "format_finalize", "operation_id_short": operation_id[:12]})
            try:
                existing = self.transactions.get(operation_id, request_id)
                if existing.command == "apply":
                    self._require_apply_operation(request_id, operation_id)
                self.transactions.finalize(operation_id, request_id=request_id)
            except Exception as exc:
                log_event("ERROR", "control", "format.finalize.request.failed", "WPS 排版完成请求失败", {"request_id": request_id, "stage": "format_finalize", "operation_id_short": operation_id[:12], "duration_ms": int((time.monotonic() - started_at) * 1000), "error_type": type(exc).__name__, "error_code": _error_code(exc)})
                raise
            log_event("INFO", "control", "format.finalize.request.completed", "WPS 排版完成请求完成", {"request_id": request_id, "stage": "format_finalize", "operation_id_short": operation_id[:12], "duration_ms": int((time.monotonic() - started_at) * 1000)})
            return {"operation_id": operation_id, "state": "finalized"}
        if path == "/v1/format/rollback":
            operation_id = str(body.get("operation_id", ""))
            started_at = time.monotonic()
            log_event("WARNING", "control", "format.rollback.request.start", "开始处理 WPS 排版回滚请求", {"request_id": request_id, "stage": "format_rollback", "operation_id_short": operation_id[:12]})
            try:
                existing = self.transactions.get(operation_id, request_id)
                if existing.command == "apply":
                    self._require_apply_operation(request_id, operation_id)
                self.transactions.rollback(
                    operation_id,
                    request_id=request_id,
                    preserve_conversion=bool(body.get("preserve_conversion")),
                )
            except Exception as exc:
                log_event("ERROR", "control", "format.rollback.request.failed", "WPS 排版回滚请求失败", {"request_id": request_id, "stage": "format_rollback", "operation_id_short": operation_id[:12], "duration_ms": int((time.monotonic() - started_at) * 1000), "error_type": type(exc).__name__, "error_code": _error_code(exc)})
                raise
            log_event("WARNING", "control", "format.rollback.request.completed", "WPS 排版回滚请求完成", {"request_id": request_id, "stage": "format_rollback", "operation_id_short": operation_id[:12], "duration_ms": int((time.monotonic() - started_at) * 1000)})
            return {"operation_id": operation_id, "state": "rolled_back"}
        if path == "/v1/log":
            safe_details = _safe_log_details(body.get("details"))
            log_event(
                str(body.get("level", "INFO")),
                str(body.get("component", "host")),
                str(body.get("event", "runtime.event")),
                str(body.get("message", "")),
                safe_details,
            )
            return {"status": "logged"}
        raise DocumentTransactionError("WPS_CONTROL_ROUTE_NOT_FOUND")


def create_server(
    app_root: Path,
    session_token: str,
    port: int = DEFAULT_PORT,
    *,
    account_runtime=None,
) -> WpsControlHttpServer:
    application = WpsControlApplication(app_root, session_token, account_runtime)
    monitor = CommandMonitor(application.dispatch)

    class Handler(BaseHTTPRequestHandler):
        server_version = "DocxToolWps/1"

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Authorization, Content-Type, X-DocxTool-Request-Id",
            )
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _json(self, status: int, payload: Dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            request_id = self._request_id()
            if request_id:
                self.send_header("X-DocxTool-Request-Id", request_id)
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError as exc:
                log_event(
                    "ERROR",
                    "control",
                    "control.response.write_failed",
                    "WPS Control 响应写入失败",
                    {
                        "path": self.path,
                        "http_status": status,
                        "error_code": "WPS_CONTROL_RESPONSE_WRITE_FAILED",
                        "error_type": type(exc).__name__,
                    },
                )
                raise

        def _authorized(self) -> bool:
            return self.headers.get("Authorization", "") == f"Bearer {application.session_token}"

        def _request_id(self) -> str:
            return self.headers.get("X-DocxTool-Request-Id", "")[:120]

        def _read_body(self) -> Dict[str, Any]:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise DocumentTransactionError("WPS_CONTROL_INVALID_CONTENT_LENGTH") from exc
            if length < 0:
                raise DocumentTransactionError("WPS_CONTROL_NEGATIVE_CONTENT_LENGTH")
            if length > MAX_BODY_BYTES:
                raise DocumentTransactionError("WPS_CONTROL_REQUEST_TOO_LARGE")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise DocumentTransactionError("WPS_CONTROL_BODY_TRUNCATED")
            if not raw:
                return {}
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DocumentTransactionError("WPS_CONTROL_JSON_INVALID") from exc
            if not isinstance(value, dict):
                raise DocumentTransactionError("WPS_CONTROL_JSON_OBJECT_REQUIRED")
            return value

        def do_OPTIONS(self) -> None:  # noqa: N802
            is_quiet_route = self.path == "/v1/log" or self.path in BRIDGE_ROUTES
            if not is_quiet_route:
                log_event("DEBUG", "control", "request.start", "WPS Control 预检请求开始", {"method": "OPTIONS", "path": self.path})
            self.send_response(204)
            self._cors()
            self.end_headers()
            if not is_quiet_route:
                log_event("DEBUG", "control", "request.completed", "WPS Control 预检请求完成", {"method": "OPTIONS", "path": self.path, "http_status": 204})

        def do_GET(self) -> None:  # noqa: N802
            started_at = time.monotonic()
            request_id = self._request_id()
            log_event("INFO", "control", "request.start", "WPS Control 请求开始", {"method": "GET", "path": self.path, "request_id": request_id})
            if self.path not in {"/v1/health", "/v1/account"}:
                self._json(404, {"ok": False, "error_code": "WPS_CONTROL_ROUTE_NOT_FOUND"})
                log_event("ERROR", "control", "control.route.not_found", "WPS Control 路由不存在", {"method": "GET", "path": self.path, "request_id": request_id, "http_status": 404, "error_code": "WPS_CONTROL_ROUTE_NOT_FOUND"})
                return
            if not self._authorized():
                self._json(401, {"ok": False, "error_code": "WPS_CONTROL_UNAUTHORIZED"})
                log_event("ERROR", "control", "control.auth.rejected", "WPS Control 请求鉴权失败", {"method": "GET", "path": self.path, "request_id": request_id, "http_status": 401, "error_code": "WPS_CONTROL_UNAUTHORIZED"})
                return
            data = application.health() if self.path == "/v1/health" else application.account_summary()
            self._json(200, {"ok": True, "data": data})
            log_event(
                "INFO", "control", "request.completed", "WPS Control 请求完成",
                {"method": "GET", "path": self.path, "request_id": request_id, "http_status": 200, "duration_ms": int((time.monotonic() - started_at) * 1000)},
            )

        def do_POST(self) -> None:  # noqa: N802
            started_at = time.monotonic()
            request_id = self._request_id()
            is_log_route = self.path == "/v1/log"
            is_bridge_route = self.path in BRIDGE_ROUTES
            is_quiet_route = is_log_route or is_bridge_route
            if not is_quiet_route:
                log_event("INFO", "control", "request.start", "WPS Control 请求开始", {"method": "POST", "path": self.path, "request_id": request_id})
            if not self._authorized():
                self._json(401, {"ok": False, "error_code": "WPS_CONTROL_UNAUTHORIZED"})
                event = "log.ingest.failed" if is_log_route else "request.failed"
                if not is_log_route:
                    event = "control.auth.rejected"
                log_event("ERROR", "control", event, "WPS Control 请求鉴权失败", {"method": "POST", "path": self.path, "request_id": request_id, "http_status": 401, "error_code": "WPS_CONTROL_UNAUTHORIZED"})
                return
            try:
                body = self._read_body()
                if is_log_route:
                    data = application.dispatch(self.path, body, request_id=request_id)
                elif is_bridge_route:
                    data = application.dispatch_bridge(
                        self.path, body, request_id=request_id
                    )
                elif self.path in BUSINESS_ROUTES:
                    data = monitor.submit(self.path, body, request_id=request_id)
                else:
                    raise DocumentTransactionError("WPS_CONTROL_ROUTE_NOT_FOUND")
                self._json(200, {"ok": True, "data": data})
                if not is_quiet_route:
                    log_event(
                        "INFO", "control", "request.completed", "WPS Control 请求完成",
                        {"method": "POST", "path": self.path, "request_id": request_id, "http_status": 200, "duration_ms": int((time.monotonic() - started_at) * 1000)},
                    )
            except Exception as exc:
                code = _error_code(exc if isinstance(exc, Exception) else Exception(str(exc)))
                status = 404 if code == "WPS_CONTROL_ROUTE_NOT_FOUND" else 400
                log_event(
                    "ERROR",
                    "control",
                    "log.ingest.failed" if is_log_route else _request_failure_event(code),
                    "WPS Control 请求执行失败",
                    {
                        "method": "POST", "path": self.path, "request_id": request_id, "error_code": code,
                        "cause_event": code,
                        "error_type": type(exc).__name__, "http_status": status,
                        "duration_ms": int((time.monotonic() - started_at) * 1000),
                    },
                )
                self._json(status, {"ok": False, "error_code": code})

        def log_message(self, format: str, *args: object) -> None:
            if self.path == "/v1/log" or self.path in BRIDGE_ROUTES:
                return
            log_event("DEBUG", "http", "access", format % args)

    server = WpsControlHttpServer(
        (HOST, int(port)), Handler, monitor, application.host_bridge
    )
    try:
        monitor.start()
    except Exception:
        ThreadingHTTPServer.server_close(server)
        raise
    return server


def run_server(app_root: Path, session_token: str, port: int = DEFAULT_PORT) -> None:
    server = create_server(app_root, session_token, port)
    actual_port = int(server.server_address[1])
    log_event(
        "INFO",
        "control",
        "server.start",
        "WPS Control Server 已启动",
        {"host": HOST, "port": actual_port, "docxtool_version": package_version()},
    )
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        log_event("INFO", "control", "server.stop", "WPS Control Server 已停止")
