"""Static contracts for the tracked Ubuntu managed-session deployment package."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "docxtool"
SETUP = PACKAGE / "setup.sh"
START = PACKAGE / "start.sh"
NGINX_TEMPLATE = PACKAGE / "nginx" / "docxtool.conf"


def _env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_deployment_scripts_use_nginx_certbot_and_a_managed_session() -> None:
    setup = SETUP.read_text(encoding="utf-8")
    start = START.read_text(encoding="utf-8")

    assert "nginx certbot python3-certbot-nginx" in setup
    assert "--certbot-email" in setup
    assert "certbot --nginx --non-interactive --agree-tos" in setup
    assert setup.index("certbot --nginx") < setup.rindex("systemctl reload nginx")
    assert "Do not reload the HTTP-only candidate" in setup
    assert "systemctl" not in start
    assert "docxtool.pid" in setup
    assert "docxtool.pid" in start
    assert "validate_environment_secrets" in setup
    assert "validate_environment_secrets" in start
    for forbidden in ("caddy", "Caddy", "/etc/caddy", "docxtool.service"):
        assert forbidden not in setup
        assert forbidden not in start


def test_nginx_template_uses_the_backend_upload_limit_and_loopback_only() -> None:
    template = NGINX_TEMPLATE.read_text(encoding="utf-8")

    assert "listen 80;" in template
    assert "server_name origin.toolpp.cn;" in template
    assert "client_max_body_size __MAX_UPLOAD_SIZE_MB__m;" in template
    assert "client_max_body_size 0;" not in template
    assert "client_max_body_size 10m;" not in template
    assert "proxy_pass http://127.0.0.1:9527;" in template
    assert "[::]" not in template
    assert "0.0.0.0:9527" not in template


def test_deployment_environment_is_production_only_and_distinct_from_root_development() -> None:
    development = _env_values(ROOT / ".env.example")
    production = _env_values(PACKAGE / ".env.example")

    assert development["BIND_HOST"] == production["BIND_HOST"] == "127.0.0.1"
    assert development["PORT"] == production["PORT"] == "9527"
    assert development["PRODUCTION_MODE"] == "false"
    assert development["FRONTEND_ORIGIN"] == ""
    assert production["PRODUCTION_MODE"] == "true"
    assert production["FRONTEND_ORIGIN"] == "https://docx.toolpp.cn"
    assert production["ADMIN_CONSOLE_ORIGIN"] == "https://docx.toolpp.cn"
    assert production["MAX_UPLOAD_SIZE_MB"] == "10"


def test_formal_production_docs_name_the_single_tracked_deployment_package() -> None:
    documents = (
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        PACKAGE / "README.md",
        ROOT / "docs" / "API.md",
        ROOT / "docs" / "ARCHITECTURE.md",
        ROOT / "docs" / "DEPLOY.md",
        ROOT / "docs" / "design" / "UBUNTU_DIRECT_ORIGIN_DEPLOYMENT.md",
        ROOT / "docs" / "design" / "UNIFIED_WPS_PUBLIC_GATEWAY.md",
        ROOT / "WPS_SERVER_PRD.md",
        ROOT / "WPS_SERVER_TECHNICAL_DESIGN.md",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in documents)

    assert "docxtool/" in text
    assert "origin.toolpp.cn" in text
    assert "43.130.232.115" in text
    assert "127.0.0.1:9527" in text
    assert "不配置 AAAA" in text
    assert "不开放 `9527`" in text
    assert "MAX_UPLOAD_SIZE_MB" in text
    assert "Caddy" not in text
    assert "linux/install.sh" not in text
    assert "docxtool.service" not in text


def test_publish_script_allows_retired_server_deletions_and_new_package_files() -> None:
    script = (ROOT / "scripts" / "publish_to_github.ps1").read_text(encoding="utf-8")

    assert '"server/"' in script
    assert '"docxtool/"' in script
    assert "Get-ChildItem -LiteralPath (Join-Path $SourceRoot \"docxtool\")" in script
