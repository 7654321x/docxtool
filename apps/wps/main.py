"""Launcher for the DocxTool WPS app."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
from typing import Tuple
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
from apps.wps.public_api import PublicApiError, WpsPublicApi  # noqa: E402

RUNTIME_DIR = APP_ROOT / "runtime"
RUNTIME_CONFIG = RUNTIME_DIR / "runtime-config.js"
CONTROL_RUNTIME_ROOT = Path(
    os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
) / "DocxTool" / "wps"
EXPECTED_WPSJS_VERSION = "2.2.3"
EXPECTED_RPC_VERSION = "1.1.0"
DEFAULT_WEB_PORT = 3889
WPS_ADDIN_NAME = "docxtool-wps-app"


def write_runtime_config(port: int, token: str) -> None:
    log_event("INFO", "launcher", "launcher.runtime_config.write.start", "开始写入 WPS 运行配置")
    temporary = RUNTIME_CONFIG.with_suffix(".tmp")
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "controlBaseUrl": f"http://127.0.0.1:{port}",
            "sessionToken": token,
        }
        text = "window.DocxToolWpsConfig=Object.freeze(" + json.dumps(payload, ensure_ascii=False) + ");\n"
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(RUNTIME_CONFIG)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        log_event(
            "ERROR", "launcher", "launcher.runtime_config.write.failed",
            "WPS 运行配置写入失败",
            {
                "error_code": "WPS_RUNTIME_CONFIG_WRITE_FAILED",
                "error_type": type(exc).__name__,
            },
        )
        raise
    log_event(
        "INFO",
        "launcher",
        "launcher.runtime_config.write.completed",
        "WPS 运行配置写入完成",
        {"config_file": RUNTIME_CONFIG.name, "token_present": True},
    )


def clear_runtime_config() -> None:
    RUNTIME_CONFIG.unlink(missing_ok=True)


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("WPS_PACKAGE_JSON_INVALID")
    return value


def verify_files() -> None:
    required = [
        "package.json", "manifest.xml", "ribbon.xml", "index.html", "main.js",
        "js/bootstrap-log.js", "js/bootstrap-complete.js", "js/ribbon.js", "images/taskpane.svg", "host-runtime.js",
        "taskpane.html", "taskpane.js", "client-config.json",
    ]
    if not FROZEN:
        required.extend([
            "account_store.py", "account_runtime.py", "public_api.py", "login_window.py",
            "control/server.py", "control/host_bridge.py", "control/format_current_document.py",
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

    def end_headers(self) -> None:
        self.send_header(
            "Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"
        )
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


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


def _start_web_server(port: int) -> Tuple[ThreadingHTTPServer, int]:
    log_event(
        "INFO", "launcher", "launcher.web.create.start",
        "开始创建 WPS 插件网页服务", {"web_port": port},
    )
    try:
        server = ThreadingHTTPServer(
            ("127.0.0.1", port), _WpsStaticRequestHandler
        )
    except OSError as exc:
        log_event(
            "ERROR", "launcher", "launcher.web.create.failed",
            "WPS 插件网页服务创建失败",
            {"web_port": port, "error_code": "WPS_WEB_SERVER_CREATE_FAILED", "error_type": type(exc).__name__},
        )
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


def start(port: int, account_runtime=None) -> None:
    verify_files()
    configure_wps_logging(CONTROL_RUNTIME_ROOT)
    control_server, actual_port = (
        _start_control(port)
        if account_runtime is None
        else _start_control(port, account_runtime)
    )
    web_server = None
    control_thread = None
    thread_started = False
    try:
        web_server, actual_web_port = _start_web_server(DEFAULT_WEB_PORT)
        _publish_addin(actual_web_port)
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
        log_event(
            "INFO", "launcher", "launcher.session.start",
            "DocxTool WPS 后台服务已启动，请按需打开 WPS 文字",
            {"control_port": actual_port, "web_port": actual_web_port},
        )
        if account_runtime is not None:
            account_runtime.start()
        try:
            web_server.serve_forever(poll_interval=0.25)
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
        if account_runtime is not None:
            account_runtime.stop()
        if web_server is not None:
            web_server.server_close()
            log_event("INFO", "launcher", "launcher.web.stop", "WPS 插件网页服务已停止")
        log_event("INFO", "launcher", "launcher.control.shutdown.start", "开始停止 WPS Control Server", {"control_port": actual_port})
        if thread_started:
            control_server.shutdown()
        control_server.server_close()
        if thread_started:
            control_thread.join(timeout=3)
            if control_thread.is_alive():
                log_event("ERROR", "launcher", "launcher.control.thread.stop_timeout", "WPS Control Server 线程停止超时", {"control_port": actual_port, "error_code": "WPS_CONTROL_THREAD_STOP_TIMEOUT"})
                raise RuntimeError("WPS_CONTROL_THREAD_STOP_TIMEOUT")
        log_event("INFO", "launcher", "launcher.control.shutdown.completed", "WPS Control Server 已停止", {"control_port": actual_port})
        log_event("INFO", "launcher", "launcher.runtime_config.cleanup.start", "开始清理 WPS 运行配置")
        try:
            clear_runtime_config()
        except Exception as exc:
            log_event(
                "ERROR", "launcher", "launcher.runtime_config.cleanup.failed",
                "WPS 运行配置清理失败", {"error_type": type(exc).__name__},
            )
            raise
        log_event("INFO", "launcher", "launcher.runtime_config.cleanup.completed", "WPS 运行配置清理完成")
        log_event("INFO", "launcher", "launcher.session.stop", "DocxTool WPS 本地会话已停止")


def resolve_startup_account(api) -> dict:
    """Load the local account or complete standalone login before startup."""
    account = account_store.load_account()
    if not account:
        log_event("INFO", "launcher", "launcher.account.window.open", "本机没有已保存账号，打开登录注册窗口")
        return show_login_register_window(api=api, account_store=account_store)
    if int(account["session_expires_at"]) > int(time.time()):
        log_event("INFO", "launcher", "launcher.account.loaded", "已读取本机账号，跳过登录窗口", {"session_valid": True})
        return account
    runtime = AccountRuntime(account, api)
    try:
        runtime.ensure_session()
    except PublicApiError as exc:
        if exc.network:
            log_event("WARNING", "launcher", "launcher.account.offline", "公网服务暂不可用，本地功能继续启动", {"error_code": exc.code})
            return account
        account_store.clear_account()
        log_event("WARNING", "launcher", "launcher.account.rejected", "已保存账号被服务器拒绝，重新打开登录窗口", {"error_code": exc.code})
        return show_login_register_window(api=api, account_store=account_store)
    refreshed = account_store.load_account()
    log_event("INFO", "launcher", "launcher.account.refreshed", "已静默刷新过期登录会话")
    return refreshed


def main() -> int:
    parser = argparse.ArgumentParser(description="DocxTool WPS app launcher")
    parser.add_argument("action", nargs="?", default="start", choices=("start", "control", "verify"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="0 表示自动选择空闲 loopback 端口")
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
    api = WpsPublicApi()
    account = resolve_startup_account(api)
    if not account:
        log_event("INFO", "launcher", "launcher.account.window.closed", "登录注册窗口已关闭，停止启动")
        return 0
    start(args.port, AccountRuntime(account, api))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
