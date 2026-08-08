"""Loopback-only WPS control server.

The server exposes lifecycle orchestration only. Recognition and formatting are
executed by the existing DocxTool package in the same Python process.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any, Dict

from docxtool.version import package_version

from .document_transaction import DocumentTransactionError, DocumentTransactionManager
from .logging_adapter import configure_wps_logging, log_event
from .recognize_document import recognize_document

HOST = "127.0.0.1"
DEFAULT_PORT = 0
MAX_BODY_BYTES = 1024 * 1024


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", "")
    if isinstance(code, str) and code:
        return code
    text = str(error).strip()
    if text and text.upper() == text and len(text) <= 100:
        return text
    return "WPS_CONTROL_ERROR"


class WpsControlApplication:
    def __init__(self, app_root: Path, session_token: str) -> None:
        self.app_root = Path(app_root)
        self.session_token = session_token
        self.log_dir = configure_wps_logging(self.app_root)
        self.transactions = DocumentTransactionManager(self.log_dir)

    def health(self) -> Dict[str, Any]:
        return {
            "status": "ready",
            "service": "docxtool-wps-control",
            "docxtool_version": package_version(),
            "host": HOST,
        }

    def dispatch(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        if path == "/v1/recognize":
            return recognize_document(
                str(body.get("source_path", "")),
                log_dir=self.log_dir,
                format_config=body.get("format_config") if isinstance(body.get("format_config"), dict) else None,
            )
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
                if isinstance(value, (str, int, float, bool)) or value is None
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
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
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
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/v1/health":
                self._json(404, {"ok": False, "error_code": "WPS_CONTROL_ROUTE_NOT_FOUND"})
                return
            if not self._authorized():
                self._json(401, {"ok": False, "error_code": "WPS_CONTROL_UNAUTHORIZED"})
                return
            self._json(200, {"ok": True, "data": application.health()})

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                self._json(401, {"ok": False, "error_code": "WPS_CONTROL_UNAUTHORIZED"})
                return
            try:
                body = self._read_body()
                data = application.dispatch(self.path, body)
                self._json(200, {"ok": True, "data": data})
            except Exception as exc:
                code = _error_code(exc if isinstance(exc, Exception) else Exception(str(exc)))
                log_event(
                    "ERROR",
                    "control",
                    "request.failed",
                    "WPS Control 请求执行失败",
                    {"path": self.path, "error_code": code, "error_type": type(exc).__name__},
                )
                status = 404 if code == "WPS_CONTROL_ROUTE_NOT_FOUND" else 400
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
