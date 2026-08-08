"""Launcher for the DocxTool WPS app."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
from typing import List, Tuple

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


def write_runtime_config(port: int, token: str) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"controlBaseUrl": f"http://127.0.0.1:{port}", "sessionToken": token}
    text = "window.DocxToolWpsConfig=Object.freeze(" + json.dumps(payload, ensure_ascii=False) + ");\n"
    temporary = RUNTIME_CONFIG.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(RUNTIME_CONFIG)


def clear_runtime_config() -> None:
    RUNTIME_CONFIG.unlink(missing_ok=True)


def verify_files() -> None:
    required = [
        "package.json", "manifest.xml", "ribbon.xml", "index.html", "main.js",
        "taskpane.html", "taskpane.js", "control/server.py",
        "control/format_current_document.py", "control/document_transaction.py",
        "control/logging_adapter.py", "control/recognize_document.py",
    ]
    missing = [item for item in required if not (APP_ROOT / item).is_file()]
    if missing:
        raise RuntimeError("WPS_APP_FILES_MISSING: " + ", ".join(missing))
    from docxtool.document.importer import DocxImporter  # noqa: F401
    from docxtool.document.engine import export_doc  # noqa: F401
    from docxtool.sdk import recognize_docx  # noqa: F401


def _wpsjs_command() -> List[str]:
    wpsjs = APP_ROOT / "node_modules" / ".bin" / ("wpsjs.cmd" if sys.platform == "win32" else "wpsjs")
    if not wpsjs.exists():
        raise RuntimeError("WPSJS_NOT_INSTALLED: 请先在 apps/wps 执行 npm install。")
    if sys.platform != "win32":
        return [str(wpsjs), "debug", "-s"]
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise RuntimeError("POWERSHELL7_NOT_FOUND: Windows 启动 WPS 插件需要 PowerShell 7 (pwsh)。")
    quoted = str(wpsjs).replace("'", "''")
    return [pwsh, "-NoProfile", "-Command", f"& '{quoted}' debug -s"]


def _start_control(port: int) -> Tuple[object, int]:
    token = secrets.token_urlsafe(32)
    server = create_server(APP_ROOT, token, port)
    actual_port = int(server.server_address[1])
    try:
        write_runtime_config(actual_port, token)
    except Exception:
        server.server_close()
        raise
    return server, actual_port


def control_only(port: int) -> None:
    verify_files()
    configure_wps_logging(APP_ROOT)
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
    configure_wps_logging(APP_ROOT)
    command = _wpsjs_command()
    server, actual_port = _start_control(port)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True)
    thread.start()
    log_event("INFO", "launcher", "session.start", "DocxTool WPS 本地会话已启动", {"control_port": actual_port})
    try:
        subprocess.run(command, cwd=str(APP_ROOT), check=True, shell=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        clear_runtime_config()
        log_event("INFO", "launcher", "session.stop", "DocxTool WPS 本地会话已停止")


def main() -> int:
    parser = argparse.ArgumentParser(description="DocxTool WPS app launcher")
    parser.add_argument("action", choices=("start", "control", "verify"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="0 表示自动选择空闲 loopback 端口")
    args = parser.parse_args()
    if args.action == "verify":
        verify_files()
        print("WPS_APP_VERIFY_PASS")
        return 0
    if args.action == "control":
        control_only(args.port)
        return 0
    start(args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
