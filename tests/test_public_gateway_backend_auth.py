from __future__ import annotations

from docxtool.web import app as web_app
from docxtool.web.handler import Handler
from docxtool.web.route_authorization import gateway_request_authorized


def _compare_secret(value: str, secret: str) -> bool:
    return value == secret


def test_gateway_allows_business_routes_without_secret_only_in_development() -> None:
    assert gateway_request_authorized(
        {},
        "/wps-api/v1/auth/login",
        production_mode=False,
        proxy_secret="gateway-secret",
        compare_secret=_compare_secret,
    )


def test_gateway_allows_only_health_and_ready_directly_in_production() -> None:
    for path in ("/health", "/ready"):
        assert gateway_request_authorized(
            {},
            path,
            production_mode=True,
            proxy_secret="gateway-secret",
            compare_secret=_compare_secret,
        )
    assert not gateway_request_authorized(
        {},
        "/version",
        production_mode=True,
        proxy_secret="gateway-secret",
        compare_secret=_compare_secret,
    )


def test_gateway_rejects_missing_or_wrong_secret_for_production_business_routes() -> None:
    for headers in ({}, {"X-Proxy-Secret": "wrong-secret"}):
        for path in ("/wps-api/v1/auth/login", "/api/auth/me"):
            assert not gateway_request_authorized(
                headers,
                path,
                production_mode=True,
                proxy_secret="gateway-secret",
                compare_secret=_compare_secret,
            )


def test_gateway_allows_correct_secret_for_production_business_routes() -> None:
    assert gateway_request_authorized(
        {"X-Proxy-Secret": "gateway-secret"},
        "/wps-api/v1/auth/login",
        production_mode=True,
        proxy_secret="gateway-secret",
        compare_secret=_compare_secret,
    )


def test_handler_stops_before_dispatch_when_production_gateway_secret_is_missing(monkeypatch) -> None:
    instance = object.__new__(Handler)
    instance.path = "/wps-api/v1/auth/login"
    instance.headers = {}
    errors: list[tuple[str, str, int]] = []
    dispatched: list[str] = []
    instance._json_error = lambda code, message, status: errors.append((code, message, status))
    monkeypatch.setattr(web_app, "PRODUCTION_MODE", True)
    monkeypatch.setattr(web_app, "PROXY_SECRET", "gateway-secret")
    monkeypatch.setattr(web_app, "_dispatch_get", lambda _handler, _parsed, path: dispatched.append(path))

    Handler.do_GET(instance)

    assert dispatched == []
    assert errors == [("PUBLIC_GATEWAY_REQUIRED", "需要通过公共网关访问", 403)]


def test_handler_dispatches_business_route_when_production_gateway_secret_matches(monkeypatch) -> None:
    instance = object.__new__(Handler)
    instance.path = "/wps-api/v1/auth/login"
    instance.headers = {"X-Proxy-Secret": "gateway-secret"}
    instance._json_error = lambda *_args, **_kwargs: None
    dispatched: list[str] = []
    monkeypatch.setattr(web_app, "PRODUCTION_MODE", True)
    monkeypatch.setattr(web_app, "PROXY_SECRET", "gateway-secret")
    monkeypatch.setattr(web_app, "_dispatch_get", lambda _handler, _parsed, path: dispatched.append(path))

    Handler.do_GET(instance)

    assert dispatched == ["/wps-api/v1/auth/login"]
