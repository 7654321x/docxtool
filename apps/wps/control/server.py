"""Loopback-only WPS control server.

The server exposes lifecycle orchestration only. Recognition and formatting are
executed by the existing DocxTool package in the same Python process.
"""

from __future__ import annotations

from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from typing import Any, Dict

from docxtool.sdk import RecognitionPlan
from docxtool.version import package_version

from .document_transaction import DocumentTransactionError, DocumentTransactionManager
from .logging_adapter import configure_wps_logging, log_event
from .recognize_document import bind_preview, recognize_document

HOST = "127.0.0.1"
DEFAULT_PORT = 0
# HostSnapshot intentionally carries the current document's raw paragraph text
# to the local Binder. Keep a hard cap, but size it for large office documents.
MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_RECOGNITION_PLANS = 8
LOG_DETAIL_FIELDS = frozenset(
    {
        "applied_count", "applied_total", "batch_index", "binding_status", "block_count",
        "block_index", "busy", "command", "compatibility_warnings", "confirmed_count",
        "control_port", "current_status", "docxtool_version", "duration_ms", "end_utf16",
        "error_code", "error_type", "failed_count", "flushed_count", "headings",
        "host_paragraph_index", "http_status",
        "interval_ms", "method", "operation_id_short", "pane_instance_id", "paragraph_count",
        "paragraphs", "path", "plan_id_short", "plugin_storage_available", "previous_status",
        "request_id", "response_ok", "review", "review_count", "stage", "start_utf16",
        "table_paragraph_count", "token_present", "total_duration_ms", "unresolved",
        "unresolved_count", "validated_count", "wait_attempts",
    }
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


class WpsControlApplication:
    def __init__(self, app_root: Path, session_token: str) -> None:
        self.app_root = Path(app_root)
        self.session_token = session_token
        self.log_dir = configure_wps_logging(self.app_root)
        self.transactions = DocumentTransactionManager(self.log_dir)
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
                result = bind_preview(self._get_plan(plan_id), host_snapshot)
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
                    "skipped_count": int(result.get("unresolved_count", 0)),
                },
            )
            return result
        if path == "/v1/format/prepare":
            operation = self.transactions.prepare(
                str(body.get("source_path", "")),
                body.get("format_config") if isinstance(body.get("format_config"), dict) else None,
            )
            result = operation.format_result
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
            operation = self.transactions.commit(str(body.get("operation_id", "")))
            return {"operation_id": operation.operation_id, "state": operation.state}
        if path == "/v1/format/finalize":
            operation_id = str(body.get("operation_id", ""))
            self.transactions.finalize(operation_id)
            return {"operation_id": operation_id, "state": "finalized"}
        if path == "/v1/format/rollback":
            operation_id = str(body.get("operation_id", ""))
            self.transactions.rollback(operation_id)
            return {"operation_id": operation_id, "state": "rolled_back"}
        if path == "/v1/log":
            details = body.get("details") if isinstance(body.get("details"), dict) else {}
            safe_details = {
                str(key)[:60]: value
                for key, value in details.items()
                if key in LOG_DETAIL_FIELDS
                and (isinstance(value, (str, int, float, bool)) or value is None)
            }
            log_event(
                str(body.get("level", "INFO")),
                str(body.get("component", "host")),
                str(body.get("event", "runtime.event")),
                str(body.get("message", "")),
                safe_details,
            )
            return {"status": "logged"}
        raise DocumentTransactionError("WPS_CONTROL_ROUTE_NOT_FOUND")


def create_server(app_root: Path, session_token: str, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    application = WpsControlApplication(app_root, session_token)

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
            self.end_headers()
            self.wfile.write(data)

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
            if length < 0 or length > MAX_BODY_BYTES:
                raise DocumentTransactionError("WPS_CONTROL_REQUEST_TOO_LARGE")
            raw = self.rfile.read(length)
            if not raw:
                return {}
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise DocumentTransactionError("WPS_CONTROL_JSON_OBJECT_REQUIRED")
            return value

        def do_OPTIONS(self) -> None:  # noqa: N802
            log_event("DEBUG", "control", "request.start", "WPS Control 预检请求开始", {"method": "OPTIONS", "path": self.path})
            self.send_response(204)
            self._cors()
            self.end_headers()
            log_event("DEBUG", "control", "request.completed", "WPS Control 预检请求完成", {"method": "OPTIONS", "path": self.path, "http_status": 204})

        def do_GET(self) -> None:  # noqa: N802
            started_at = time.monotonic()
            log_event("INFO", "control", "request.start", "WPS Control 请求开始", {"method": "GET", "path": self.path})
            if self.path != "/v1/health":
                self._json(404, {"ok": False, "error_code": "WPS_CONTROL_ROUTE_NOT_FOUND"})
                log_event("ERROR", "control", "request.failed", "WPS Control 请求失败", {"method": "GET", "path": self.path, "http_status": 404, "error_code": "WPS_CONTROL_ROUTE_NOT_FOUND"})
                return
            if not self._authorized():
                self._json(401, {"ok": False, "error_code": "WPS_CONTROL_UNAUTHORIZED"})
                log_event("ERROR", "control", "request.failed", "WPS Control 请求失败", {"method": "GET", "path": self.path, "http_status": 401, "error_code": "WPS_CONTROL_UNAUTHORIZED"})
                return
            self._json(200, {"ok": True, "data": application.health()})
            log_event(
                "INFO", "control", "request.completed", "WPS Control 请求完成",
                {"method": "GET", "path": self.path, "http_status": 200, "duration_ms": int((time.monotonic() - started_at) * 1000)},
            )

        def do_POST(self) -> None:  # noqa: N802
            started_at = time.monotonic()
            request_id = self._request_id()
            log_event("INFO", "control", "request.start", "WPS Control 请求开始", {"method": "POST", "path": self.path, "request_id": request_id})
            if not self._authorized():
                self._json(401, {"ok": False, "error_code": "WPS_CONTROL_UNAUTHORIZED"})
                log_event("ERROR", "control", "request.failed", "WPS Control 请求失败", {"method": "POST", "path": self.path, "request_id": request_id, "http_status": 401, "error_code": "WPS_CONTROL_UNAUTHORIZED"})
                return
            try:
                body = self._read_body()
                data = application.dispatch(self.path, body, request_id=request_id)
                self._json(200, {"ok": True, "data": data})
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
                    "request.failed",
                    "WPS Control 请求执行失败",
                    {
                        "method": "POST", "path": self.path, "request_id": request_id, "error_code": code,
                        "error_type": type(exc).__name__, "http_status": status,
                        "duration_ms": int((time.monotonic() - started_at) * 1000),
                    },
                )
                self._json(status, {"ok": False, "error_code": code})

        def log_message(self, format: str, *args: object) -> None:
            log_event("DEBUG", "http", "access", format % args)

    return ThreadingHTTPServer((HOST, int(port)), Handler)


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
