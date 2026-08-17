from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_FILES = (
    "route_authorization.py",
    "compatibility.py",
    "handler.py",
    "handler_lifecycle.py",
    "client_ip.py",
    "app.py",
)


def test_server_gateway_sources_match_root_sources() -> None:
    root_web = ROOT / "src" / "docxtool" / "web"
    server_web = ROOT / "server" / "src" / "docxtool" / "web"

    for filename in WEB_FILES:
        assert (server_web / filename).read_text(encoding="utf-8") == (root_web / filename).read_text(encoding="utf-8")
