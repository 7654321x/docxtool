"""Launcher for the DocxTool WPS app."""

from __future__ import annotations

import argparse
import errno
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from typing import List, Tuple
from urllib.request import Request, urlopen
from xml.etree import ElementTree

FROZEN = bool(getattr(sys, "frozen", False))
APP_ROOT = Path(getattr(sys, "_MEIPASS")) if FROZEN else Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT if FROZEN else APP_ROOT.parent.parent
SRC_ROOT = REPO_ROOT if FROZEN else REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from apps.wps.control.logging_adapter import configure_wps_logging, log_event  # noqa: E402
from apps.wps.control.server import DEFAULT_PORT, create_server  # noqa: E402
from apps.wps import account_store  # noqa: E402
from apps.wps.account_runtime import AccountRuntime  # noqa: E402
from apps.wps.login_window import show_login_register_window  # noqa: E402
from apps.wps.public_api import WpsPublicApi  # noqa: E402
from apps.wps import windows_startup  # noqa: E402

RUNTIME_DIR = APP_ROOT / "runtime"
_RUNTIME_CONFIG: dict = {}
CONTROL_RUNTIME_ROOT = Path(
    os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
) / "DocxTool" / "wps"
EXPECTED_WPSJS_VERSION = "2.2.3"
EXPECTED_RPC_VERSION = "1.1.0"
DEFAULT_WEB_PORT = 3889
WPS_ADDIN_NAME = "docxtool-wps-app"


def write_runtime_config(port: int, token: str) -> None:
    log_event("INFO", "launcher", "launcher.runtime_config.publish.start", "开始发布 WPS 运行配置")
    global _RUNTIME_CONFIG
    _RUNTIME_CONFIG = {
        "controlBaseUrl": f"http://127.0.0.1:{port}",
        "sessionToken": token,
    }
    log_event(
        "INFO",
        "launcher",
        "launcher.runtime_config.publish.completed",
        "WPS 运行配置已发布到同源内存端点",
        {"token_present": True},
    )


def clear_runtime_config() -> None:
    global _RUNTIME_CONFIG
    _RUNTIME_CONFIG = {}


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("WPS_PACKAGE_JSON_INVALID")
    return value


def verify_files() -> None:
    required = [
        "package.json", "manifest.xml", "ribbon.xml", "index.html", "main.js",
        "js/bootstrap-log.js", "js/bootstrap-complete.js", "js/ribbon.js", "images/taskpane.svg", "host-runtime.js",
        "taskpane.html", "taskpane.js", "format-config.js", "format-settings.html", "format-settings.js", "format-settings.css", "client-config.json",
        "reader/reader-client.js", "reader/reader-ui.js", "reader/reader.css",
        "images/check.svg", "images/eye.svg", "images/eye-off.svg", "images/taskpane-icons.svg",
        "images/login-window.png", "images/user.svg",
    ]
    if not FROZEN:
        required.extend([
            "account_store.py", "account_runtime.py", "format_profile_store.py",
            "public_api.py", "login_window.py",
            "desktop_runtime.py", "windows_startup.py",
            "control/server.py", "control/host_bridge.py", "control/format_current_document.py",
            "control/add_letterhead.py",
            "control/reader_routes.py",
            "control/document_transaction.py", "control/logging_adapter.py",
            "control/recognize_document.py", "control/monitor.py",
        ])
    missing = [item for item in required if not (APP_ROOT / item).is_file()]
    if missing:
        raise RuntimeError("WPS_APP_FILES_MISSING: " + ", ".join(missing))
    package = _read_json(APP_ROOT / "package.json")
    dependencies = package.get("devDependencies")
    overrides = package.get("overrides")
    if not isinstance(dependencies, dict) or dependencies.get("wpsjs") != EXPECTED_WPSJS_VERSION:
        raise RuntimeError("WPSJS_VERSION_NOT_PINNED")
    if not isinstance(overrides, dict) or overrides.get("wpsjs-rpc-sdk-new") != EXPECTED_RPC_VERSION:
        raise RuntimeError("WPSJS_RPC_VERSION_NOT_PINNED")
    from docxtool.document.importer import DocxImporter  # noqa: F401
    from docxtool.document.engine import export_doc  # noqa: F401
    from docxtool.sdk import bind_recognition_plan, recognize_docx  # noqa: F401


class _WpsStaticRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_ROOT), **kwargs)

    def log_message(self, _format, *_args) -> None:
        return None

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/runtime/config":
            if not _RUNTIME_CONFIG:
                self.send_error(503, "WPS runtime configuration unavailable")
                return
            data = json.dumps(_RUNTIME_CONFIG, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/runtime/runtime-config.js":
            self.send_error(404)
            return
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header(
            "Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"
        )
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


class _WpsStaticHttpServer(ThreadingHTTPServer):
    # 固定 3889 只能对应一个 WPS 会话，禁止新旧静态服务并存。
    allow_reuse_address = False


def _listening_pids(port: int) -> List[int]:
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pattern = re.compile(
        rf"^\s*TCP\s+127\.0\.0\.1:{port}\s+\S+\s+LISTENING\s+(\d+)\s*$",
        re.IGNORECASE,
    )
    return [
        int(match.group(1))
        for line in result.stdout.splitlines()
        if (match := pattern.match(line)) is not None
    ]


def _is_docxtool_static_service(port: int) -> bool:
    try:
        config_request = Request(
            f"http://127.0.0.1:{port}/runtime/config",
            headers={"Cache-Control": "no-cache"},
        )
        with urlopen(config_request, timeout=1) as response:
            config = json.loads(response.read().decode("utf-8"))
        control_url = config.get("controlBaseUrl")
        token = config.get("sessionToken")
        if (
            not isinstance(control_url, str)
            or not control_url.startswith("http://127.0.0.1:")
            or not isinstance(token, str)
            or not token
        ):
            return False
        health_request = Request(
            f"{control_url}/v1/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(health_request, timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return (
            isinstance(payload, dict)
            and payload.get("ok") is True
            and isinstance(payload.get("data"), dict)
            and payload["data"].get("service") == "docxtool-wps-control"
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _stop_previous_docxtool_service(port: int) -> bool:
    pids = sorted(set(_listening_pids(port)))
    pids = [pid for pid in pids if pid != os.getpid()]
    if not pids or not _is_docxtool_static_service(port):
        return False
    log_event(
        "WARNING",
        "launcher",
        "launcher.web.previous_service.detected",
        "检测到旧的 DocxTool WPS 本地服务，准备停止",
        {"error_code": "WPS_WEB_SERVER_PREVIOUS_SERVICE"},
    )
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(pids[0]), "/T", "/F"],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True,
        )
    except OSError as exc:
        log_event(
            "ERROR",
            "launcher",
            "launcher.web.previous_service.stop.failed",
            "旧 DocxTool WPS 本地服务停止失败",
            {
                "error_code": "WPS_WEB_SERVER_OLD_SERVICE_STOP_FAILED",
                "error_type": type(exc).__name__,
            },
        )
        raise RuntimeError("WPS_WEB_SERVER_OLD_SERVICE_STOP_FAILED") from exc
    if result.returncode != 0:
        error = RuntimeError("WPS_WEB_SERVER_OLD_SERVICE_STOP_FAILED")
        log_event(
            "ERROR",
            "launcher",
            "launcher.web.previous_service.stop.failed",
            "旧 DocxTool WPS 本地服务停止失败",
            {
                "error_code": "WPS_WEB_SERVER_OLD_SERVICE_STOP_FAILED",
                "error_type": type(error).__name__,
            },
        )
        raise error
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not _listening_pids(port):
            log_event(
                "INFO",
                "launcher",
                "launcher.web.previous_service.stop.completed",
                "旧 DocxTool WPS 本地服务已停止",
            )
            return True
        time.sleep(0.05)
    error = RuntimeError("WPS_WEB_SERVER_OLD_SERVICE_STOP_FAILED")
    log_event(
        "ERROR",
        "launcher",
        "launcher.web.previous_service.stop.failed",
        "旧 DocxTool WPS 本地服务停止后端口仍被占用",
        {
            "error_code": "WPS_WEB_SERVER_OLD_SERVICE_STOP_FAILED",
            "error_type": type(error).__name__,
        },
    )
    raise error


def _is_address_in_use(error: OSError) -> bool:
    return (
        error.errno in {errno.EADDRINUSE, 10048}
        or getattr(error, "winerror", None) == 10048
    )


def _publish_xml_path() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("APPDATA")
        if not root:
            raise RuntimeError("WPS_APPDATA_MISSING")
        return Path(root) / "kingsoft" / "wps" / "jsaddons" / "publish.xml"
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Containers" / "com.kingsoft.wpsoffice.mac" / "Data" / ".kingsoft" / "wps" / "jsaddons" / "publish.xml"
    return home / ".local" / "share" / "Kingsoft" / "wps" / "jsaddons" / "publish.xml"


def _publish_addin(web_port: int) -> None:
    log_event(
        "INFO", "launcher", "launcher.publish.start",
        "开始更新 WPS 加载项注册", {"web_port": web_port},
    )
    publish_path = _publish_xml_path()
    try:
        if publish_path.is_file():
            tree = ElementTree.parse(publish_path)
            root = tree.getroot()
        else:
            root = ElementTree.Element("jsplugins")
            tree = ElementTree.ElementTree(root)
    except ElementTree.ParseError as exc:
        log_event(
            "ERROR", "launcher", "launcher.publish.parse.failed",
            "WPS 加载项注册文件解析失败",
            {"error_code": "WPS_PUBLISH_XML_INVALID", "error_type": type(exc).__name__},
        )
        raise RuntimeError("WPS_PUBLISH_XML_INVALID") from exc
    if root.tag.rsplit("}", 1)[-1] != "jsplugins":
        log_event(
            "ERROR", "launcher", "launcher.publish.schema.failed",
            "WPS 加载项注册文件根节点无效",
            {"error_code": "WPS_PUBLISH_XML_SCHEMA_INVALID"},
        )
        raise RuntimeError("WPS_PUBLISH_XML_SCHEMA_INVALID")

    matches = [
        node
        for node in list(root)
        if node.tag.rsplit("}", 1)[-1] == "jspluginonline"
        and node.get("name") == WPS_ADDIN_NAME
    ]
    if matches:
        addin = matches[0]
        for duplicate in matches[1:]:
            root.remove(duplicate)
    else:
        namespace = root.tag[:-len("jsplugins")]
        addin = ElementTree.SubElement(root, f"{namespace}jspluginonline")
    addin.attrib.clear()
    addin.attrib.update(
        {
            "name": WPS_ADDIN_NAME,
            "type": "wps",
            "url": f"http://127.0.0.1:{web_port}/",
            "debug": "",
            "enable": "enable_dev",
            "install": "null",
        }
    )

    temporary = publish_path.with_name(publish_path.name + ".tmp")
    try:
        publish_path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(temporary, encoding="utf-8", xml_declaration=True)
        temporary.replace(publish_path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        log_event(
            "ERROR", "launcher", "launcher.publish.write.failed",
            "WPS 加载项注册文件写入失败",
            {"error_code": "WPS_PUBLISH_WRITE_FAILED", "error_type": type(exc).__name__},
        )
        raise
    log_event(
        "INFO", "launcher", "launcher.publish.completed",
        "WPS 加载项注册已更新", {"web_port": web_port},
    )


def _unpublish_addin() -> None:
    """Remove only this app's WPS add-in registration."""
    log_event(
        "INFO", "launcher", "launcher.unpublish.start", "开始移除 WPS 加载项注册"
    )
    publish_path = _publish_xml_path()
    if not publish_path.is_file():
        log_event(
            "INFO", "launcher", "launcher.unpublish.completed", "WPS 加载项注册无需移除",
            {"removed_count": 0},
        )
        return
    try:
        tree = ElementTree.parse(publish_path)
        root = tree.getroot()
    except ElementTree.ParseError as exc:
        log_event(
            "ERROR", "launcher", "launcher.unpublish.parse.failed",
            "WPS 加载项注册文件解析失败",
            {"error_code": "WPS_UNPUBLISH_XML_INVALID", "error_type": type(exc).__name__},
        )
        raise RuntimeError("WPS_UNPUBLISH_XML_INVALID") from exc
    if root.tag.rsplit("}", 1)[-1] != "jsplugins":
        log_event(
            "ERROR", "launcher", "launcher.unpublish.schema.failed",
            "WPS 加载项注册文件根节点无效",
            {"error_code": "WPS_UNPUBLISH_XML_SCHEMA_INVALID"},
        )
        raise RuntimeError("WPS_UNPUBLISH_XML_SCHEMA_INVALID")
    matches = [
        node
        for node in list(root)
        if node.tag.rsplit("}", 1)[-1] == "jspluginonline"
        and node.get("name") == WPS_ADDIN_NAME
    ]
    if not matches:
        log_event(
            "INFO", "launcher", "launcher.unpublish.completed", "WPS 加载项注册无需移除",
            {"removed_count": 0},
        )
        return
    for node in matches:
        root.remove(node)
    temporary = publish_path.with_name(publish_path.name + ".tmp")
    try:
        tree.write(temporary, encoding="utf-8", xml_declaration=True)
        temporary.replace(publish_path)
    except OSError as exc:
        log_event(
            "ERROR", "launcher", "launcher.unpublish.write.failed",
            "WPS 加载项注册文件写入失败",
            {"error_code": "WPS_UNPUBLISH_WRITE_FAILED", "error_type": type(exc).__name__},
        )
        raise RuntimeError("WPS_UNPUBLISH_WRITE_FAILED") from exc
    log_event(
        "INFO", "launcher", "launcher.unpublish.completed", "WPS 加载项注册已移除",
        {"removed_count": len(matches)},
    )


def _start_web_server(port: int) -> Tuple[ThreadingHTTPServer, int]:
    log_event(
        "INFO", "launcher", "launcher.web.create.start",
        "开始创建 WPS 插件网页服务", {"web_port": port},
    )
    try:
        server = _WpsStaticHttpServer(
            ("127.0.0.1", port), _WpsStaticRequestHandler
        )
    except OSError as exc:
        if port == DEFAULT_WEB_PORT and _is_address_in_use(exc):
            if _stop_previous_docxtool_service(port):
                try:
                    server = _WpsStaticHttpServer(
                        ("127.0.0.1", port), _WpsStaticRequestHandler
                    )
                except OSError as retry_exc:
                    exc = retry_exc
                else:
                    actual_port = int(server.server_address[1])
                    log_event(
                        "INFO",
                        "launcher",
                        "launcher.web.create.completed",
                        "WPS 插件网页服务创建完成",
                        {"web_port": actual_port},
                    )
                    return server, actual_port
        error_code = (
            "WPS_WEB_SERVER_PORT_IN_USE"
            if port == DEFAULT_WEB_PORT
            and _is_address_in_use(exc)
            else "WPS_WEB_SERVER_CREATE_FAILED"
        )
        log_event(
            "ERROR", "launcher", "launcher.web.create.failed",
            "WPS 插件网页服务创建失败",
            {"web_port": port, "error_code": error_code, "error_type": type(exc).__name__},
        )
        if error_code == "WPS_WEB_SERVER_PORT_IN_USE":
            raise RuntimeError(error_code) from exc
        raise
    actual_port = int(server.server_address[1])
    log_event(
        "INFO", "launcher", "launcher.web.create.completed",
        "WPS 插件网页服务创建完成", {"web_port": actual_port},
    )
    return server, actual_port


def _start_control(port: int, account_runtime=None) -> Tuple[object, int]:
    log_event("INFO", "launcher", "launcher.control.create.start", "开始创建 WPS Control Server")
    token = secrets.token_urlsafe(32)
    try:
        server = create_server(
            CONTROL_RUNTIME_ROOT,
            token,
            port,
            account_runtime=account_runtime,
            allowed_origin=f"http://127.0.0.1:{DEFAULT_WEB_PORT}",
        )
    except Exception as exc:
        log_event(
            "ERROR", "launcher", "launcher.control.create.failed",
            "WPS Control Server 创建失败",
            {
                "error_code": "WPS_CONTROL_CREATE_FAILED",
                "error_type": type(exc).__name__,
            },
        )
        raise
    actual_port = int(server.server_address[1])
    try:
        write_runtime_config(actual_port, token)
    except Exception as exc:
        log_event(
            "ERROR", "launcher", "launcher.control.config_failed",
            "Control Server 已创建但运行配置发布失败",
            {
                "control_port": actual_port,
                "error_code": "WPS_CONTROL_CONFIG_PUBLISH_FAILED",
                "error_type": type(exc).__name__,
            },
        )
        server.server_close()
        raise
    log_event(
        "INFO", "launcher", "launcher.control.create.completed", "WPS Control Server 创建完成",
        {"control_host": "127.0.0.1", "control_port": actual_port},
    )
    return server, actual_port


def control_only(port: int) -> None:
    verify_files()
    configure_wps_logging(CONTROL_RUNTIME_ROOT)
    server, actual_port = _start_control(port)
    log_event("INFO", "launcher", "control.start", "WPS Control Server 前台运行", {"port": actual_port})
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        clear_runtime_config()
        log_event("INFO", "launcher", "control.stop", "WPS Control Server 已停止")


def start(port: int, account_runtime=None, *, stop_event=None) -> None:
    if account_runtime is None:
        log_event(
            "ERROR", "launcher", "launcher.account_runtime.required",
            "WPS 插件服务必须绑定本地账号运行时",
            {"error_code": "WPS_ACCOUNT_RUNTIME_REQUIRED"},
        )
        raise RuntimeError("WPS_ACCOUNT_RUNTIME_REQUIRED")
    verify_files()
    configure_wps_logging(CONTROL_RUNTIME_ROOT)
    control_server, actual_port = _start_control(port, account_runtime)
    web_server = None
    control_thread = None
    thread_started = False
    account_started = False
    try:
        web_server, actual_web_port = _start_web_server(DEFAULT_WEB_PORT)
        control_thread = threading.Thread(
            target=control_server.serve_forever,
            kwargs={"poll_interval": 0.25},
            daemon=True,
        )
        log_event("INFO", "launcher", "launcher.control.thread.start", "开始启动 WPS Control Server 线程", {"control_port": actual_port})
        try:
            control_thread.start()
            thread_started = True
        except RuntimeError as exc:
            log_event("ERROR", "launcher", "launcher.control.thread.failed", "WPS Control Server 线程启动失败", {"control_port": actual_port, "error_code": "WPS_CONTROL_THREAD_START_FAILED", "error_type": type(exc).__name__})
            raise
        log_event("INFO", "launcher", "launcher.control.thread.started", "WPS Control Server 线程已启动", {"control_port": actual_port})
        account_runtime.start()
        account_started = True
        _publish_addin(actual_web_port)
        log_event(
            "INFO", "launcher", "launcher.session.start",
            "DocxTool WPS 后台服务已启动，请按需打开 WPS 文字",
            {"control_port": actual_port, "web_port": actual_web_port},
        )
        try:
            if stop_event is None:
                web_server.serve_forever(poll_interval=0.25)
            else:
                web_server.timeout = 0.25
                while not stop_event.is_set():
                    web_server.handle_request()
        except KeyboardInterrupt:
            log_event("INFO", "launcher", "launcher.interrupt.received", "收到用户中断，开始停止本地会话")
        except Exception as exc:
            log_event(
                "ERROR", "launcher", "launcher.web.serve.failed",
                "WPS 插件网页服务运行失败",
                {"web_port": actual_web_port, "error_code": "WPS_WEB_SERVER_FAILED", "error_type": type(exc).__name__},
            )
            raise
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_error = None

        def record_cleanup_failure(exc, event, message, error_code):
            nonlocal cleanup_error
            if cleanup_error is None:
                cleanup_error = exc
            log_event(
                "ERROR",
                "launcher",
                event,
                message,
                {"error_code": error_code, "error_type": type(exc).__name__},
            )

        if account_started:
            try:
                account_runtime.stop()
            except BaseException as exc:
                record_cleanup_failure(
                    exc,
                    "launcher.account_runtime.stop.failed",
                    "WPS 账号运行时停止失败",
                    "WPS_ACCOUNT_RUNTIME_STOP_FAILED",
                )
        if web_server is not None:
            try:
                web_server.server_close()
            except BaseException as exc:
                record_cleanup_failure(
                    exc,
                    "launcher.web.close.failed",
                    "WPS 插件网页服务关闭失败",
                    "WPS_WEB_SERVER_CLOSE_FAILED",
                )
            else:
                log_event("INFO", "launcher", "launcher.web.stop", "WPS 插件网页服务已停止")
        log_event("INFO", "launcher", "launcher.control.shutdown.start", "开始停止 WPS Control Server", {"control_port": actual_port})
        if thread_started:
            try:
                control_server.shutdown()
            except BaseException as exc:
                record_cleanup_failure(
                    exc,
                    "launcher.control.shutdown.failed",
                    "WPS Control Server 停止失败",
                    "WPS_CONTROL_SERVER_SHUTDOWN_FAILED",
                )
        try:
            control_server.server_close()
        except BaseException as exc:
            record_cleanup_failure(
                exc,
                "launcher.control.close.failed",
                "WPS Control Server 关闭失败",
                "WPS_CONTROL_SERVER_CLOSE_FAILED",
            )
        if thread_started:
            try:
                control_thread.join(timeout=3)
            except BaseException as exc:
                record_cleanup_failure(
                    exc,
                    "launcher.control.thread.join.failed",
                    "WPS Control Server 线程等待失败",
                    "WPS_CONTROL_THREAD_JOIN_FAILED",
                )
            else:
                try:
                    thread_alive = control_thread.is_alive()
                except BaseException as exc:
                    record_cleanup_failure(
                        exc,
                        "launcher.control.thread.state_check.failed",
                        "WPS Control Server 线程状态检查失败",
                        "WPS_CONTROL_THREAD_STATE_CHECK_FAILED",
                    )
                else:
                    if thread_alive:
                        timeout_error = RuntimeError("WPS_CONTROL_THREAD_STOP_TIMEOUT")
                        record_cleanup_failure(
                            timeout_error,
                            "launcher.control.thread.stop_timeout",
                            "WPS Control Server 线程停止超时",
                            "WPS_CONTROL_THREAD_STOP_TIMEOUT",
                        )
        if cleanup_error is None:
            log_event("INFO", "launcher", "launcher.control.shutdown.completed", "WPS Control Server 已停止", {"control_port": actual_port})
        log_event("INFO", "launcher", "launcher.runtime_config.cleanup.start", "开始清理 WPS 运行配置")
        try:
            clear_runtime_config()
        except BaseException as exc:
            record_cleanup_failure(
                exc,
                "launcher.runtime_config.cleanup.failed",
                "WPS 运行配置清理失败",
                "WPS_RUNTIME_CONFIG_CLEANUP_FAILED",
            )
        else:
            log_event("INFO", "launcher", "launcher.runtime_config.cleanup.completed", "WPS 运行配置清理完成")
        if cleanup_error is None:
            log_event("INFO", "launcher", "launcher.session.stop", "DocxTool WPS 本地会话已停止")
        elif primary_error is None:
            raise cleanup_error


def resolve_startup_account(api, *, force_login: bool = False) -> dict:
    """Always show the authentication window before starting WPS services."""
    initial_message = ""
    try:
        account = account_store.load_account()
    except account_store.LocalAccountCorruptedError:
        try:
            account_store.quarantine_corrupted_account()
        except OSError as exc:
            log_event(
                "ERROR",
                "account",
                "account.local_store.quarantine.failed",
                "本机账号数据隔离失败",
                {
                    "error_code": "WPS_LOCAL_ACCOUNT_QUARANTINE_FAILED",
                    "error_type": type(exc).__name__,
                },
            )
            raise RuntimeError("WPS_LOCAL_ACCOUNT_QUARANTINE_FAILED") from exc
        log_event(
            "ERROR",
            "account",
            "account.local_store.corrupted",
            "本机账号数据已损坏，已隔离并重新打开登录注册窗口",
            {"error_code": "WPS_LOCAL_ACCOUNT_CORRUPTED"},
        )
        account = {}
        initial_message = "检测到本地登录信息异常，请重新登录。"
    log_event(
        "INFO",
        "launcher",
        "launcher.account.window.open",
        "启动时打开登录注册窗口，等待界面完成账号认证",
        {
            "reason": "force_login" if force_login else "startup",
            "account_present": bool(account),
            "auto_login_requested": bool(account.get("auto_login")),
        },
    )
    return show_login_register_window(
        api=api,
        account_store=account_store,
        initial_username=account.get("username", ""),
        initial_password=(
            account.get("password", "") if account.get("remember_password") else ""
        ),
        device_key=account.get("device_key", ""),
        remember_password=bool(account.get("remember_password", False)),
        auto_login=bool(account.get("auto_login", False)),
        initial_message=initial_message,
        startup_enabled=windows_startup.is_enabled(),
    )


def run_desktop(port: int, *, force_login: bool = False) -> int:
    from apps.wps.desktop_runtime import (
        DesktopController,
        SingleInstance,
        ensure_application,
        shift_pressed,
    )

    application = ensure_application()
    instance = SingleInstance()
    if not instance.acquire():
        return 0
    _unpublish_addin()
    api = WpsPublicApi()
    account = resolve_startup_account(
        api,
        force_login=force_login or shift_pressed(),
    )
    if not account:
        log_event("INFO", "launcher", "launcher.account.window.closed", "登录注册窗口已关闭，停止启动")
        return 0
    controller = DesktopController(
        application=application,
        account_runtime=AccountRuntime(account, api),
        start_service=start,
        port=port,
    )
    instance.show_requested.connect(controller.show_settings)
    controller.start()
    exit_code = application.exec_()
    controller.shutdown()
    if controller.restart_login_requested:
        _unpublish_addin()
        instance.close()
        windows_startup.launch("--force-login")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="DocxTool WPS app launcher")
    parser.add_argument("action", nargs="?", default="start", choices=("start", "control", "verify"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="0 表示自动选择空闲 loopback 端口")
    parser.add_argument("--startup", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--force-login", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.action == "verify":
        configure_wps_logging(CONTROL_RUNTIME_ROOT)
        log_event("INFO", "launcher", "launcher.verify.start", "开始验证 WPS App 文件")
        verify_files()
        log_event("INFO", "launcher", "launcher.verify.completed", "WPS App 文件验证完成")
        print("WPS_APP_VERIFY_PASS")
        return 0
    if args.action == "control":
        control_only(args.port)
        return 0
    return run_desktop(args.port, force_login=args.force_login)


if __name__ == "__main__":
    raise SystemExit(main())
