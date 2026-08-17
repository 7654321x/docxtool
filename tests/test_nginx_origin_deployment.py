"""Static contracts for the single Ubuntu Nginx production path."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINUX_ROOT = ROOT / "server" / "linux"
INSTALLER = LINUX_ROOT / "install.sh"
NGINX_TEMPLATE = LINUX_ROOT / "nginx-docxtool.conf"


def _env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_linux_installer_uses_nginx_and_certbot_without_a_caddy_path() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "nginx certbot python3-certbot-nginx" in installer
    assert "--certbot-email" in installer
    assert 'NGINX_SITE_AVAILABLE="/etc/nginx/sites-available/docxtool"' in installer
    assert "nginx -t" in installer
    assert "systemctl enable --now nginx" in installer
    assert "certbot --nginx --non-interactive --agree-tos" in installer
    assert '"$ORIGIN_HOST"' in installer
    for forbidden in ("caddy", "Caddy", "/etc/caddy", "--replace-caddyfile"):
        assert forbidden not in installer


def test_nginx_template_proxies_only_to_loopback_ipv4() -> None:
    """Nginx disables its own body-size policy; Backend owns MAX_UPLOAD_SIZE_MB."""
    assert NGINX_TEMPLATE.is_file()
    assert not (LINUX_ROOT / "Caddyfile").exists()
    template = NGINX_TEMPLATE.read_text(encoding="utf-8")

    assert "listen 80;" in template
    assert "server_name __ORIGIN_HOST__;" in template
    assert "client_max_body_size 0;" in template
    assert "proxy_pass http://127.0.0.1:9527;" in template
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in template
    assert "[::]" not in template
    assert "0.0.0.0:9527" not in template
    assert "client_max_body_size 10m;" not in template
    assert "client_max_body_size 1m;" not in template


def test_linux_installer_uses_one_fixed_app_directory() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    service = (LINUX_ROOT / "docxtool.service").read_text(encoding="utf-8")

    assert 'APP_DIR="/opt/docxtool"' in installer
    assert "--app-dir" not in installer
    assert "WorkingDirectory=/opt/docxtool" in service
    assert "ExecStart=/opt/docxtool/.venv/bin/python /opt/docxtool/server.py" in service


def test_linux_installer_checks_production_configuration_before_starting_backend() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "env_value PRODUCTION_MODE" in installer
    assert "env_value BIND_HOST" in installer
    assert "env_value PORT" in installer
    assert 'for key in ADMIN_TOKEN PROXY_SECRET' in installer
    assert "production configuration is incomplete" in installer
    assert "systemctl enable --now docxtool" in installer


def test_root_and_server_environment_examples_have_distinct_development_and_production_defaults() -> None:
    development = _env_values(ROOT / ".env.example")
    production = _env_values(ROOT / "server" / ".env.example")

    assert development["BIND_HOST"] == production["BIND_HOST"] == "127.0.0.1"
    assert development["PORT"] == production["PORT"] == "9527"
    assert development["PRODUCTION_MODE"] == "false"
    assert development["FRONTEND_ORIGIN"] == ""
    assert production["PRODUCTION_MODE"] == "true"
    assert production["FRONTEND_ORIGIN"] == "https://docx.toolpp.cn"
    assert production["ADMIN_CONSOLE_ORIGIN"] == "https://docx.toolpp.cn"
    assert production["COOKIE_SECURE"] == "true"
    assert production["ADMIN_COOKIE_SECURE"] == "true"


def test_formal_production_docs_describe_one_nginx_ipv4_origin() -> None:
    documents = (
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        ROOT / "server" / "README.md",
        ROOT / "docs" / "API.md",
        ROOT / "docs" / "ARCHITECTURE.md",
        ROOT / "docs" / "DEPLOY.md",
        ROOT / "docs" / "design" / "UBUNTU_DIRECT_ORIGIN_DEPLOYMENT.md",
        ROOT / "docs" / "design" / "UNIFIED_WPS_PUBLIC_GATEWAY.md",
        ROOT / "WPS_SERVER_PRD.md",
        ROOT / "WPS_SERVER_TECHNICAL_DESIGN.md",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in documents)

    assert "Nginx" in text
    assert "Certbot" in text
    assert "origin.toolpp.cn" in text
    assert "43.130.232.115" in text
    assert "127.0.0.1:9527" in text
    assert "不配置 AAAA" in text
    assert "不开放 `9527`" in text
    assert "Caddy" not in text
