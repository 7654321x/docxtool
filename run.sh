#!/usr/bin/env bash
set -euo pipefail

export BIND_HOST="${BIND_HOST:-127.0.0.1}"
export PORT="${PORT:-9527}"

exec python3 server.py
