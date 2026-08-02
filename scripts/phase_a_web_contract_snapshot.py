"""Capture or compare a redacted Phase A Web behavior contract."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
from pathlib import Path
import threading
from typing import Any

from docxtool.web import app


_RESPONSE_HEADERS = {
    "access-control-allow-methods",
    "access-control-allow-origin",
    "allow",
    "cache-control",
    "content-type",
    "referrer-policy",
    "x-content-type-options",
    "x-frame-options",
}
_REQUESTS = (
    ("GET", "/health", {}),
    ("GET", "/ready", {}),
    ("GET", "/version", {}),
    ("GET", "/api/version", {}),
    ("GET", "/", {}),
    ("GET", "/admin/login", {}),
    ("GET", "/definitely-missing", {}),
    (
        "OPTIONS",
        "/api/version",
        {
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    ),
)


def _response_contract(path: str, method: str, headers: dict[str, str]) -> dict[str, Any]:
    server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        selected_headers = {
            key.casefold(): value
            for key, value in response.getheaders()
            if key.casefold() in _RESPONSE_HEADERS
        }
    finally:
        connection.close()
        thread.join(5)
        server.server_close()
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        body_contract: dict[str, Any] = {
            "kind": "bytes",
            "length": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
    else:
        body_contract = {
            "kind": "json",
            "keys": sorted(value) if isinstance(value, dict) else [],
            "types": (
                {key: type(item).__name__ for key, item in sorted(value.items())}
                if isinstance(value, dict)
                else type(value).__name__
            ),
        }
    return {
        "status": response.status,
        "headers": selected_headers,
        "body": body_contract,
    }


def capture() -> dict[str, Any]:
    return {
        "schema": "phase-a-web-contract-v1",
        "config": {
            key: getattr(app, key)
            for key in (
                "PORT",
                "BIND_HOST",
                "APP_VERSION",
                "FILE_RETENTION_POLICY",
                "FILE_TTL",
                "MAX_SIZE",
                "MAX_WORKERS",
                "MAX_QUEUE",
                "PROCESS_TIMEOUT",
                "RATE_WINDOW",
                "TASK_RETENTION_HOURS",
                "MAX_CACHED_TASKS",
            )
        },
        "paths": {
            key: Path(getattr(app, key)).name
            for key in ("LOG_DIR", "RUNTIME_DIR", "RUNTIME_TMP_DIR", "UPLOAD_DIR", "OUTPUT_DIR")
        },
        "path_exists": {
            key: Path(getattr(app, key)).is_dir()
            for key in ("LOG_DIR", "RUNTIME_DIR", "RUNTIME_TMP_DIR", "UPLOAD_DIR", "OUTPUT_DIR")
        },
        "routes": {
            path: app._route_path(path)
            for path in (
                "/",
                "/api/health",
                "/api/ready",
                "/api/version",
                "/api/status/a",
                "/api/auth/me",
                "/api/presets/x",
                "/admin/login",
            )
        },
        "handler": {
            "bases": [item.__name__ for item in app.Handler.__mro__],
            "methods": sorted(
                key for key, value in app.Handler.__dict__.items() if callable(value)
            ),
        },
        "runtime": {
            "tasks_type": type(app.TASKS).__name__,
            "queue_type": type(app.TASK_QUEUE).__name__,
            "worker_state_keys": sorted(app.WORKER_STATE),
            "task_count": len(app.TASKS),
            "queue_count": len(app.TASK_QUEUE),
        },
        "responses": {
            f"{method} {path}": _response_contract(path, method, headers)
            for method, path, headers in _REQUESTS
        },
    }


def _normalized(value: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(value))
    result.get("handler", {}).pop("module", None)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    payload = capture()
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if args.compare is None:
        return 0
    before = json.loads(args.compare.read_text(encoding="utf-8"))
    if _normalized(before) != _normalized(payload):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
