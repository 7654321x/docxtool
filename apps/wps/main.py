"""Launcher for the DocxTool WPS app."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import List, Set, Tuple

APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT.parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from apps.wps.control.logging_adapter import configure_wps_logging, log_event  # noqa: E402
from apps.wps.control.server import DEFAULT_PORT, create_server  # noqa: E402

RUNTIME_DIR = APP_ROOT / "runtime"
RUNTIME_CONFIG = RUNTIME_DIR / "runtime-config.js"
CONTROL_RUNTIME_ROOT = Path(
    os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
) / "DocxTool" / "wps"
EXPECTED_WPSJS_VERSION = "2.2.3"
EXPECTED_RPC_VERSION = "1.1.0"


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
        "js/bootstrap-log.js", "js/bootstrap-complete.js", "js/ribbon.js", "host-runtime.js",
        "taskpane.html", "taskpane.js", "control/server.py",
        "control/format_current_document.py", "control/document_transaction.py",
        "control/logging_adapter.py", "control/recognize_document.py",
        "control/monitor.py",
    ]
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


def _verify_installed_node_runtime() -> None:
    wpsjs_package = APP_ROOT / "node_modules" / "wpsjs" / "package.json"
    rpc_package = APP_ROOT / "node_modules" / "wpsjs-rpc-sdk-new" / "package.json"
    if not wpsjs_package.is_file() or not rpc_package.is_file():
        raise RuntimeError("WPSJS_NOT_INSTALLED: 请先在 apps/wps 执行 npm install。")
    if str(_read_json(wpsjs_package).get("version", "")) != EXPECTED_WPSJS_VERSION:
        raise RuntimeError("WPSJS_INSTALLED_VERSION_MISMATCH")
    if str(_read_json(rpc_package).get("version", "")) != EXPECTED_RPC_VERSION:
        raise RuntimeError("WPSJS_RPC_INSTALLED_VERSION_MISMATCH")


def _wpsjs_command() -> List[str]:
    _verify_installed_node_runtime()
    wpsjs = APP_ROOT / "node_modules" / ".bin" / ("wpsjs.cmd" if sys.platform == "win32" else "wpsjs")
    if not wpsjs.exists():
        raise RuntimeError("WPSJS_EXECUTABLE_MISSING")
    if sys.platform != "win32":
        command = [str(wpsjs), "debug"]
        log_event(
            "INFO", "launcher", "launcher.wpsjs.command.resolved", "wpsjs 启动命令已确认",
            {"executable": wpsjs.name, "wpsjs_version": EXPECTED_WPSJS_VERSION},
        )
        return command
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise RuntimeError("POWERSHELL7_NOT_FOUND: Windows 启动 WPS 插件需要 PowerShell 7 (pwsh)。")
    quoted = str(wpsjs).replace("'", "''")
    command = [pwsh, "-NoProfile", "-Command", f"& '{quoted}' debug"]
    log_event(
        "INFO", "launcher", "launcher.wpsjs.command.resolved", "wpsjs 启动命令已确认",
        {"executable": Path(pwsh).name, "wpsjs_version": EXPECTED_WPSJS_VERSION},
    )
    return command


def _visible_top_level_window_process_ids() -> Set[int]:
    import ctypes
    from ctypes import wintypes

    visible_process_ids: Set[int] = set()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]

    @callback_type
    def collect_visible_window(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if process_id.value:
                visible_process_ids.add(int(process_id.value))
        return True

    if not user32.EnumWindows(collect_visible_window, 0):
        error_code = ctypes.get_last_error()
        if error_code:
            raise OSError(error_code, "EnumWindows failed")
    return visible_process_ids


def _wps_process_count() -> int:
    if sys.platform != "win32":
        return 0
    completed = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq wps.exe", "/FO", "CSV", "/NH"],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )
    rows = csv.reader(completed.stdout.splitlines())
    wps_process_ids = {
        int(row[1])
        for row in rows
        if len(row) > 1
        and str(row[0]).strip().casefold() == "wps.exe"
        and str(row[1]).strip().isdigit()
    }
    return len(wps_process_ids & _visible_top_level_window_process_ids())


def _require_wps_stopped() -> None:
    log_event(
        "INFO",
        "launcher",
        "launcher.wps.process_check.start",
        "开始检查是否已有可见 WPS 文字窗口",
    )
    try:
        process_count = _wps_process_count()
    except (OSError, subprocess.CalledProcessError) as exc:
        log_event(
            "ERROR",
            "launcher",
            "launcher.wps.process_check.failed",
            "WPS 文字窗口检查失败",
            {
                "error_code": "WPS_PROCESS_CHECK_FAILED",
                "error_type": type(exc).__name__,
            },
        )
        raise RuntimeError("WPS_PROCESS_CHECK_FAILED") from exc
    if process_count:
        log_event(
            "ERROR",
            "launcher",
            "launcher.wps.restart_required",
            "检测到已打开的 WPS 文字窗口，请关闭后重新启动 DocxTool",
            {
                "error_code": "WPS_RESTART_REQUIRED",
                "process_count": process_count,
            },
        )
        raise RuntimeError("WPS_RESTART_REQUIRED")
    log_event(
        "INFO",
        "launcher",
        "launcher.wps.process_check.completed",
        "未检测到已打开的 WPS 文字窗口",
        {"process_count": 0},
    )


def _start_control(port: int) -> Tuple[object, int]:
    log_event("INFO", "launcher", "launcher.control.create.start", "开始创建 WPS Control Server")
    token = secrets.token_urlsafe(32)
    try:
        server = create_server(CONTROL_RUNTIME_ROOT, token, port)
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


def start(port: int) -> None:
    verify_files()
    configure_wps_logging(CONTROL_RUNTIME_ROOT)
    _require_wps_stopped()
    command = _wpsjs_command()
    server, actual_port = _start_control(port)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True)
    thread_started = False
    started_at = time.monotonic()
    try:
        log_event("INFO", "launcher", "launcher.control.thread.start", "开始启动 WPS Control Server 线程", {"control_port": actual_port})
        try:
            thread.start()
            thread_started = True
        except RuntimeError as exc:
            log_event("ERROR", "launcher", "launcher.control.thread.failed", "WPS Control Server 线程启动失败", {"control_port": actual_port, "error_code": "WPS_CONTROL_THREAD_START_FAILED", "error_type": type(exc).__name__})
            raise
        log_event("INFO", "launcher", "launcher.control.thread.started", "WPS Control Server 线程已启动", {"control_port": actual_port})
        log_event("INFO", "launcher", "launcher.session.start", "DocxTool WPS 本地会话已启动", {"control_port": actual_port})
        log_event("INFO", "launcher", "launcher.wpsjs.start", "开始启动 wpsjs")
        completed = subprocess.run(command, cwd=str(APP_ROOT), check=True, shell=False)
        log_event(
            "INFO", "launcher", "launcher.wpsjs.exit", "wpsjs 已退出",
            {"return_code": completed.returncode, "duration_ms": int((time.monotonic() - started_at) * 1000)},
        )
    except KeyboardInterrupt:
        log_event("INFO", "launcher", "launcher.interrupt.received", "收到用户中断，开始停止本地会话")
    except subprocess.CalledProcessError as exc:
        log_event(
            "ERROR",
            "launcher",
            "launcher.wpsjs.exit_failed",
            "wpsjs 异常退出",
            {
                "error_code": "WPSJS_PROCESS_FAILED",
                "error_type": type(exc).__name__,
                "return_code": exc.returncode,
                "duration_ms": int((time.monotonic() - started_at) * 1000),
            },
        )
        raise
    except OSError as exc:
        log_event(
            "ERROR",
            "launcher",
            "launcher.wpsjs.start_failed",
            "wpsjs 进程启动失败",
            {
                "error_code": "WPSJS_PROCESS_START_FAILED",
                "error_type": type(exc).__name__,
                "duration_ms": int((time.monotonic() - started_at) * 1000),
            },
        )
        raise
    finally:
        log_event("INFO", "launcher", "launcher.control.shutdown.start", "开始停止 WPS Control Server", {"control_port": actual_port})
        if thread_started:
            server.shutdown()
        server.server_close()
        if thread_started:
            thread.join(timeout=3)
            if thread.is_alive():
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
    start(args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
