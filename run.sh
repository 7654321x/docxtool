#!/usr/bin/env bash
set -euo pipefail

export BIND_HOST="${BIND_HOST:-127.0.0.1}"
export PORT="${PORT:-9527}"

: "${ADMIN_TOKEN:?请先设置 ADMIN_TOKEN，例如 export ADMIN_TOKEN='长随机管理密钥'}"
: "${PROXY_SECRET:?请先设置 PROXY_SECRET，例如 export PROXY_SECRET='长随机代理密钥'}"

exec python3 server.py
