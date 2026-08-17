#!/usr/bin/env bash
# Install or update the DocxTool backend on Ubuntu 22.04.
# Run from the unpacked deployment package with sudo. It never writes secrets.
set -Eeuo pipefail

APP_DIR="/opt/docxtool"
ORIGIN_HOST=""
REPLACE_CADDYFILE=false

usage() {
    cat <<'EOF'
Usage: sudo ./linux/install.sh --origin-host origin.example.com [--app-dir /opt/docxtool] [--replace-caddyfile]

Installs the loopback-only DocxTool service and a Caddy HTTPS reverse proxy.
--replace-caddyfile is required before replacing an existing Caddyfile.
EOF
}

while (($#)); do
    case "$1" in
        --origin-host)
            ORIGIN_HOST="${2:-}"
            shift 2
            ;;
        --app-dir)
            APP_DIR="${2:-}"
            shift 2
            ;;
        --replace-caddyfile)
            REPLACE_CADDYFILE=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "Run this installer with sudo." >&2
    exit 1
fi
if [[ ! "$ORIGIN_HOST" =~ ^[A-Za-z0-9.-]+$ || "$ORIGIN_HOST" != *.* ]]; then
    echo "--origin-host must be a DNS hostname, for example origin.example.com." >&2
    exit 2
fi
if [[ "$APP_DIR" != /opt/* ]]; then
    echo "--app-dir must stay under /opt." >&2
    exit 2
fi

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ ! -f "$SOURCE_DIR/server.py" || ! -f "$SOURCE_DIR/requirements.lock" ]]; then
    echo "Run from the unpacked DocxTool server package." >&2
    exit 1
fi

if [[ -s /etc/caddy/Caddyfile && "$REPLACE_CADDYFILE" != true ]]; then
    echo "Existing /etc/caddy/Caddyfile detected. Re-run with --replace-caddyfile after confirming it does not serve another site." >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3.10 python3.10-venv python3-pip rsync \
    debian-keyring debian-archive-keyring apt-transport-https curl gpg

if ! command -v caddy >/dev/null 2>&1; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        -o /etc/apt/sources.list.d/caddy-stable.list
    chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    chmod o+r /etc/apt/sources.list.d/caddy-stable.list
    apt-get update
    apt-get install -y caddy
fi

if ! id -u docxtool >/dev/null 2>&1; then
    useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin docxtool
fi

install -d -o docxtool -g docxtool -m 0750 "$APP_DIR"
rsync -a --delete \
    --exclude '.env' \
    --exclude '.venv/' \
    --exclude 'var/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "$SOURCE_DIR/" "$APP_DIR/"
install -d -o docxtool -g docxtool -m 0750 \
    "$APP_DIR/var/data" "$APP_DIR/var/logs" "$APP_DIR/var/outputs" \
    "$APP_DIR/var/runtime" "$APP_DIR/var/uploads"

python3.10 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install --require-hashes -r "$APP_DIR/requirements.lock"
chown -R docxtool:docxtool "$APP_DIR"

if [[ ! -f "$APP_DIR/.env" ]]; then
    install -o docxtool -g docxtool -m 0600 "$APP_DIR/.env.example" "$APP_DIR/.env"
fi

sed "s|__ORIGIN_HOST__|$ORIGIN_HOST|g" "$APP_DIR/linux/Caddyfile" > /etc/caddy/Caddyfile
install -m 0644 "$APP_DIR/linux/docxtool.service" /etc/systemd/system/docxtool.service
systemctl daemon-reload
systemctl enable caddy
systemctl restart caddy
systemctl enable docxtool

if grep -Eq '^(ADMIN_TOKEN|PROXY_SECRET)=($|change-me-)' "$APP_DIR/.env"; then
    cat <<EOF

Installation completed, but DocxTool is intentionally not started yet.
1. Generate two different secrets: sudo -u docxtool $APP_DIR/.venv/bin/python $APP_DIR/scripts/generate_secrets.py
2. Edit $APP_DIR/.env and set production configuration.
3. Set the exact PROXY_SECRET as the Pages production Secret.
4. Start: sudo systemctl enable --now docxtool
EOF
else
    systemctl enable --now docxtool
    echo "DocxTool started. Check: systemctl status docxtool --no-pager"
fi

echo "Caddy origin: https://$ORIGIN_HOST -> http://127.0.0.1:9527"
