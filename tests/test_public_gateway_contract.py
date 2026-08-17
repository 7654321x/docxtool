"""Static contracts for the single public gateway and backend origin boundary."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WPS_ROOT = ROOT / "apps" / "wps"
WORKER_PATH = ROOT / "resources" / "frontend" / "pages" / "_worker.js"


def test_wps_runtime_only_uses_the_public_api_base_configuration() -> None:
    """The WPS production client must not learn an Origin host or server IP."""
    runtime_files = (
        WPS_ROOT / "public_api.py",
        WPS_ROOT / "account_runtime.py",
        WPS_ROOT / "login_window.py",
        WPS_ROOT / "main.py",
        WPS_ROOT / "DocxToolWps.spec",
        WPS_ROOT / "scripts" / "build-exe.ps1",
    )
    runtime_text = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)

    assert "public_api_base_url" in runtime_text
    assert "self.public_api_base_url + API_PREFIX + path" in runtime_text
    for forbidden in (
        "origin.toolpp.cn",
        "43.130.232.115",
        "nip.io",
        "trycloudflare.com",
        "cloudflared",
        "server_origin",
        "WPS_SERVER_ORIGIN",
    ):
        assert forbidden not in runtime_text


def test_wps_client_config_has_one_public_api_field() -> None:
    """Source and packaged configuration cannot retain the legacy URL key."""
    config = json.loads((WPS_ROOT / "client-config.json").read_text(encoding="utf-8"))

    assert set(config) == {"public_api_base_url"}
    assert isinstance(config["public_api_base_url"], str)
    assert config["public_api_base_url"]


def test_pages_worker_uses_only_the_configured_https_origin() -> None:
    """The worker owns one backend URL setting and never embeds infrastructure IPs."""
    worker = WORKER_PATH.read_text(encoding="utf-8")

    assert "env.BACKEND_BASE_URL" in worker
    assert "env.PROXY_SECRET" in worker
    assert "origin.toolpp.cn" not in worker
    assert "43.130.232.115" not in worker
    assert "cloudflared" not in worker
    assert 'headers.set("X-Proxy-Secret", proxySecret)' in worker
    assert "isWpsPublicApiPath(url.pathname)" in worker
