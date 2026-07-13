#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

: "${BIND_HOST:=127.0.0.1}"
: "${PORT:=9527}"

exec python3 server.py
