"""Launcher for the DocxTool WPS app.

Run from the DocxTool repository root:

    python apps/wps/main.py start

The launcher starts the loopback control service, writes a short-lived runtime
configuration for the add-in, then delegates WPS registration/resource serving
to the established ``wpsjs`` CLI.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import urllib.request

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
    payload = {
        "controlBaseUrl": f"http://127.0.0.1:{port}",
        "sessionToken": token,
    }
    text = "window.DocxToolWpsConfig=Object.freeze(" + json.dumps(payload, ensure_ascii=False) + ");\n"
    temporary = RUNTIME_CONFIG.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(RUNTIME_CONFIG)


def clear_runtime_config() -> None:
    RUNTIME_CONFIG.unlink(missing_ok=True)


def verify_files() -> None:
    required = [
        "package.json",
        "manifest.xml",
        "ribbon.xml",
        "index.html",
        "main.js",
        "taskpane.html",
        "taskpane.js",
        "control/server.py",
        "control/format_current_document.py",
    ]
    missing = [item for item in required if not (APP_ROOT / item).is_file()]
    if missing:
        raise RuntimeError("WPS_APP_FILES_MISSING: " + ", ".join(missing))
    from docxtool.document.importer import DocxImporter  # noqa: F401
    from docxtool.document.engine import export_doc  # noqa: F401
    from docxtool.sdk import recognize_docx  # noqa: F401


def control_only(port: int) -> None:
    verify_files()
    token = secrets.token_urlsafe(32)
    write_runtime_config(port, token)
    server = create_server(APP_ROOT, token, port)
    log_event("INFO", "launcher", "control.start", "WPS Control Server 前台运行", {"port": port})
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        clear_runtime_config()


def start(port: int) -> None:
    verify_files()
    configure_wps_logging(APP_ROOT)
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError("NPX_NOT_FOUND: 请先安装 Node.js，并在 apps/wps 执行 npm install。")
    wpsjs = APP_ROOT / "node_modules" / ".bin" / ("wpsjs.cmd" if sys.platform == "win32" else "wpsjs")
    if not wpsjs.exists():
        raise RuntimeError("WPSJS_NOT_INSTALLED: 请先在 apps/wps 执行 npm install。")

    token = secrets.token_urlsafe(32)
    write_runtime_config(port, token)
    server = create_server(APP_ROOT, token, port)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True)
    thread.start()
    log_event(
        "INFO",
        "launcher",
        "session.start",
        "DocxTool WPS 本地会话已启动",
        {"control_port": port},
    )
    try:
        subprocess.run(
            [npx, "--no-install", "wpsjs", "debug", "-s"],
            cwd=str(APP_ROOT),
            check=True,
            shell=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        clear_runtime_config()
        log_event("INFO", "launcher", "session.stop", "DocxTool WPS 本地会话已停止")


def main() -> int:
    parser = argparse.ArgumentParser(description="DocxTool WPS app launcher")
    parser.add_argument("action", choices=("start", "control", "verify"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
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
