#!/usr/bin/env bash
# Start DocxTool in the current managed session; no Python systemd service is created.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="$ROOT/.env"
PYTHON="$ROOT/.venv/bin/python"
PID_DIR="$ROOT/var/runtime"
PID_FILE="$PID_DIR/docxtool.pid"

if [[ ! -x "$PYTHON" ]]; then
    echo "Python runtime is missing. Run ./setup.sh first." >&2
    exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
    echo "Missing .env. Run ./setup.sh, then configure .env." >&2
    exit 1
fi

pid_is_active() {
    local pid="$1"
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] && kill -0 "$pid" 2>/dev/null
}

mkdir -p "$PID_DIR"
if [[ -f "$PID_FILE" ]]; then
    running_pid="$(<"$PID_FILE")"
    if pid_is_active "$running_pid"; then
        echo "DocxTool is already running in this package (PID $running_pid)." >&2
        exit 1
    fi
    rm -f -- "$PID_FILE"
fi

PYTHONPATH="$ROOT/src" "$PYTHON" - "$ENV_FILE" <<'PY'
import os
import sys
from pathlib import Path

from docxtool.env import load_dotenv_file
from docxtool.web.secrets import validate_environment_secrets

load_dotenv_file(Path(sys.argv[1]))
validate_environment_secrets(os.environ)
PY

cleanup() {
    rm -f -- "$PID_FILE"
}

forward_signal() {
    if [[ -n "$server_pid" ]]; then
        kill -TERM "$server_pid" 2>/dev/null || true
    fi
}

trap cleanup EXIT
trap forward_signal INT TERM
cd "$ROOT"
server_pid=""
"$PYTHON" server.py &
server_pid="$!"
printf '%s\n' "$server_pid" > "$PID_FILE"
wait "$server_pid"
