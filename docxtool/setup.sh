#!/usr/bin/env bash
# Prepare the Ubuntu upload package and its Nginx HTTPS reverse proxy.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PYTHON="${PYTHON:-python3.10}"
VENV_PYTHON="$ROOT/.venv/bin/python"
ENV_FILE="$ROOT/.env"
PID_FILE="$ROOT/var/runtime/docxtool.pid"
ORIGIN_HOST="origin.toolpp.cn"
CERTBOT_EMAIL=""

usage() {
    echo "Usage: ./setup.sh --certbot-email you@example.com" >&2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --certbot-email)
            CERTBOT_EMAIL="${2:-}"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            usage
            exit 1
            ;;
    esac
done

if [[ -z "$CERTBOT_EMAIL" ]]; then
    usage
    exit 1
fi

pid_is_active() {
    local pid="$1"
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] && kill -0 "$pid" 2>/dev/null
}

if [[ -f "$PID_FILE" ]]; then
    running_pid="$(<"$PID_FILE")"
    if pid_is_active "$running_pid"; then
        echo "DocxTool is running in the managed session (PID $running_pid). Stop that session before running setup." >&2
        exit 1
    fi
    rm -f -- "$PID_FILE"
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Missing $PYTHON. Install Python 3.10 and python3.10-venv first." >&2
    exit 1
fi

"$PYTHON" - <<'PY'
import sys
if sys.version_info[:2] != (3, 10):
    raise SystemExit("DocxTool production package requires Python 3.10.")
PY

"$PYTHON" -m venv "$ROOT/.venv"
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install --require-hashes -r "$ROOT/requirements.lock"

if [[ ! -f "$ENV_FILE" ]]; then
    cp "$ROOT/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "Created .env. Replace ADMIN_TOKEN and PROXY_SECRET, then run setup again." >&2
    exit 1
fi

env_value() {
    local key="$1"
    local line
    line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
    printf '%s' "${line#*=}"
}

if [[ "$(env_value PRODUCTION_MODE)" != "true" ]]; then
    echo "PRODUCTION_MODE must be exactly true in .env." >&2
    exit 1
fi
if [[ "$(env_value BIND_HOST)" != "127.0.0.1" ]]; then
    echo "BIND_HOST must be exactly 127.0.0.1 in .env." >&2
    exit 1
fi
if [[ "$(env_value PORT)" != "9527" ]]; then
    echo "PORT must be exactly 9527 in .env." >&2
    exit 1
fi
MAX_UPLOAD_SIZE_MB="$(env_value MAX_UPLOAD_SIZE_MB)"
if [[ ! "$MAX_UPLOAD_SIZE_MB" =~ ^[1-9][0-9]*$ ]]; then
    echo "MAX_UPLOAD_SIZE_MB must be a positive integer in .env." >&2
    exit 1
fi

PYTHONPATH="$ROOT/src" "$VENV_PYTHON" - "$ENV_FILE" <<'PY'
import os
import sys
from pathlib import Path

from docxtool.env import load_dotenv_file
from docxtool.web.secrets import validate_environment_secrets

load_dotenv_file(Path(sys.argv[1]))
validate_environment_secrets(os.environ)
PY

candidate="$(mktemp)"
trap 'rm -f -- "$candidate"' EXIT
sed "s/__MAX_UPLOAD_SIZE_MB__/${MAX_UPLOAD_SIZE_MB}/g" "$ROOT/nginx/docxtool.conf" > "$candidate"

sudo apt-get update
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo install -m 644 "$candidate" /etc/nginx/sites-available/docxtool
sudo ln -sfn /etc/nginx/sites-available/docxtool /etc/nginx/sites-enabled/docxtool
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx

# Do not reload the HTTP-only candidate before Certbot has completed TLS setup.
sudo certbot --nginx --non-interactive --agree-tos --email "$CERTBOT_EMAIL" --redirect -d "$ORIGIN_HOST"
sudo nginx -t
sudo systemctl reload nginx

echo "Setup complete. Run ./start.sh in the managed session."
