from __future__ import annotations

from docxtool.web.anonymous_identity import (
    anonymous_template_origin_allowed,
    anonymous_user_cookie_clear_header,
    anonymous_user_cookie_header,
    anonymous_user_from_headers,
    create_anonymous_user,
    parse_anonymous_user,
)


MAX_AGE = 60
PROXY_SECRET = "proxy-secret"
DEFAULT_SECRET = "default-secret"
COOKIE_NAME = "docxtool_anon_user"


def test_anonymous_user_token_round_trip_and_tamper_rejection() -> None:
    identity = create_anonymous_user(
        1000,
        max_age=MAX_AGE,
        proxy_secret=PROXY_SECRET,
        default_proxy_secret=DEFAULT_SECRET,
        owner_id="usr_" + "a" * 32,
    )

    parsed = parse_anonymous_user(
        identity["token"],
        1001,
        max_age=MAX_AGE,
        proxy_secret=PROXY_SECRET,
        default_proxy_secret=DEFAULT_SECRET,
    )
    tampered = parse_anonymous_user(
        identity["token"][:-1] + "x",
        1001,
        max_age=MAX_AGE,
        proxy_secret=PROXY_SECRET,
        default_proxy_secret=DEFAULT_SECRET,
    )

    assert parsed["owner_id"] == "usr_" + "a" * 32
    assert tampered == {}


def test_anonymous_user_token_rejects_expired_or_future_values() -> None:
    identity = create_anonymous_user(
        1000,
        max_age=MAX_AGE,
        proxy_secret=PROXY_SECRET,
        default_proxy_secret=DEFAULT_SECRET,
        owner_id="usr_" + "b" * 32,
    )

    assert parse_anonymous_user(identity["token"], 1000 + MAX_AGE + 1, max_age=MAX_AGE, proxy_secret=PROXY_SECRET, default_proxy_secret=DEFAULT_SECRET) == {}
    assert parse_anonymous_user(identity["token"], 600, max_age=MAX_AGE, proxy_secret=PROXY_SECRET, default_proxy_secret=DEFAULT_SECRET) == {}


def test_anonymous_cookie_headers_include_security_attributes() -> None:
    set_cookie = anonymous_user_cookie_header("token", cookie_name=COOKIE_NAME, max_age=MAX_AGE, secure=True)
    clear_cookie = anonymous_user_cookie_clear_header(cookie_name=COOKIE_NAME, secure=False)

    assert set_cookie.startswith(f"{COOKIE_NAME}=token")
    assert "HttpOnly" in set_cookie
    assert "SameSite=Lax" in set_cookie
    assert "Max-Age=60" in set_cookie
    assert "Secure" in set_cookie
    assert clear_cookie.startswith(f"{COOKIE_NAME}=")
    assert "Max-Age=0" in clear_cookie
    assert "Secure" not in clear_cookie


def test_anonymous_user_from_headers_reuses_valid_cookie() -> None:
    identity = create_anonymous_user(
        1000,
        max_age=MAX_AGE,
        proxy_secret=PROXY_SECRET,
        default_proxy_secret=DEFAULT_SECRET,
        owner_id="usr_" + "c" * 32,
    )

    parsed, cookie = anonymous_user_from_headers(
        {"Cookie": f"{COOKIE_NAME}={identity['token']}"},
        "",
        cookie_name=COOKIE_NAME,
        max_age=MAX_AGE,
        proxy_secret=PROXY_SECRET,
        default_proxy_secret=DEFAULT_SECRET,
        now=lambda: 1001,
        secure=False,
    )

    assert parsed["owner_id"] == "usr_" + "c" * 32
    assert cookie == ""


def test_anonymous_user_from_headers_creates_new_identity_when_missing() -> None:
    identity, cookie = anonymous_user_from_headers(
        {},
        "",
        cookie_name=COOKIE_NAME,
        max_age=MAX_AGE,
        proxy_secret=PROXY_SECRET,
        default_proxy_secret=DEFAULT_SECRET,
        now=lambda: 1000,
        secure=False,
    )

    assert identity["owner_id"].startswith("usr_")
    assert cookie.startswith(f"{COOKIE_NAME}={identity['token']}")


def test_anonymous_template_origin_allowed_uses_config_or_local_host() -> None:
    assert anonymous_template_origin_allowed(
        {"Origin": "https://example.test"},
        frontend_origin="https://example.test",
        is_local_origin_host=lambda _host: False,
    )
    assert not anonymous_template_origin_allowed(
        {"Origin": "https://evil.test"},
        frontend_origin="https://example.test",
        is_local_origin_host=lambda _host: False,
    )
    assert anonymous_template_origin_allowed(
        {"Origin": "http://127.0.0.1:9527", "Host": "127.0.0.1:9527"},
        frontend_origin="",
        is_local_origin_host=lambda _host: False,
    )
    assert anonymous_template_origin_allowed(
        {"Origin": "http://localhost:3000"},
        frontend_origin="",
        is_local_origin_host=lambda host: host == "localhost",
    )
