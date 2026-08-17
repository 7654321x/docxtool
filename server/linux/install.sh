#!/usr/bin/env bash
# Install or update the DocxTool backend on Ubuntu 22.04.
# Run from the unpacked deployment package with sudo. It never writes secrets.
set -Eeuo pipefail

APP_DIR="/opt/docxtool"
ORIGIN_HOST=""
CERTBOT_EMAIL=""
NGINX_SITE_AVAILABLE="/etc/nginx/sites-available/docxtool"
NGINX_SITE_ENABLED="/etc/nginx/sites-enabled/docxtool"

usage() {
    cat <<'EOF'
Usage: sudo ./linux/install.sh --origin-host origin.example.com --certbot-email ops@example.com

Installs the loopback-only DocxTool service and its Nginx HTTPS reverse-proxy site.
Certbot obtains and manages the Let's Encrypt certificate through the Nginx integration.
EOF
}

while (($#)); do
    case "$1" in
        --origin-host)
            ORIGIN_HOST="${2:-}"
            shift 2
            ;;
        --certbot-email)
            CERTBOT_EMAIL="${2:-}"
            shift 2
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
if [[ ! "$CERTBOT_EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
    echo "--certbot-email must be a valid operations email address." >&2
    exit 2
fi
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ ! -f "$SOURCE_DIR/server.py" || ! -f "$SOURCE_DIR/requirements.lock" || ! -f "$SOURCE_DIR/linux/nginx-docxtool.conf" ]]; then
    echo "Run from the unpacked DocxTool server package." >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3.10 python3.10-venv python3-pip rsync nginx certbot python3-certbot-nginx

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

env_value() {
    local key="$1"
    awk -v key="$key" '
        index($0, key "=") == 1 { value = substr($0, length(key) + 2) }
        END { sub(/\r$/, "", value); print value }
    ' "$APP_DIR/.env"
}

production_config_errors=()
if [[ "$(env_value PRODUCTION_MODE)" != "true" ]]; then
    production_config_errors+=("PRODUCTION_MODE=true")
fi
if [[ "$(env_value BIND_HOST)" != "127.0.0.1" ]]; then
    production_config_errors+=("BIND_HOST=127.0.0.1")
fi
if [[ "$(env_value PORT)" != "9527" ]]; then
    production_config_errors+=("PORT=9527")
fi
for key in ADMIN_TOKEN PROXY_SECRET; do
    value="$(env_value "$key")"
    if [[ -z "$value" || "$value" == change-me-* ]]; then
        production_config_errors+=("$key=<random non-placeholder secret>")
    fi
done
if [[ "$(env_value ADMIN_TOKEN)" == "$(env_value PROXY_SECRET)" ]]; then
    production_config_errors+=("ADMIN_TOKEN and PROXY_SECRET must differ")
fi

sed "s|__ORIGIN_HOST__|$ORIGIN_HOST|g" "$APP_DIR/linux/nginx-docxtool.conf" > "$NGINX_SITE_AVAILABLE"
ln -sfn "$NGINX_SITE_AVAILABLE" "$NGINX_SITE_ENABLED"
nginx -t
systemctl enable --now nginx
systemctl reload nginx
certbot --nginx --non-interactive --agree-tos --email "$CERTBOT_EMAIL" --keep-until-expiring -d "$ORIGIN_HOST"
nginx -t
systemctl reload nginx

install -m 0644 "$APP_DIR/linux/docxtool.service" /etc/systemd/system/docxtool.service
systemctl daemon-reload

if ((${#production_config_errors[@]})); then
    cat <<EOF

Installation completed, but production configuration is incomplete.
Update $APP_DIR/.env with:
EOF
    printf ' - %s\n' "${production_config_errors[@]}"
    cat <<EOF
Then set the exact PROXY_SECRET as the Pages production Secret and start:
sudo systemctl enable --now docxtool
EOF
else
    systemctl enable --now docxtool
    echo "DocxTool started. Check: systemctl status docxtool --no-pager"
fi

echo "Nginx origin: https://$ORIGIN_HOST -> http://127.0.0.1:9527"
