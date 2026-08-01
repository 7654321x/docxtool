from __future__ import annotations

from docxtool.web.file_api_auth import file_api_authorized


def _compare_secret(value: str, secret: str) -> bool:
    """传入候选值和密钥，返回测试用的精确比较结果。"""
    return value == secret


def test_file_api_authorized_accepts_matching_proxy_secret() -> None:
    authorized = file_api_authorized(
        {"X-Proxy-Secret": "proxy-secret"},
        ("203.0.113.8", 1234),
        proxy_secret="proxy-secret",
        production_mode=True,
        compare_secret=_compare_secret,
    )

    assert authorized is True


def test_file_api_authorized_rejects_missing_or_wrong_secret() -> None:
    assert file_api_authorized({}, None, proxy_secret="proxy-secret", production_mode=True, compare_secret=_compare_secret) is False
    assert (
        file_api_authorized(
            {"X-Proxy-Secret": "wrong"},
            ("127.0.0.1", 9527),
            proxy_secret="proxy-secret",
            production_mode=True,
            compare_secret=_compare_secret,
        )
        is False
    )


def test_file_api_authorized_allows_loopback_only_outside_production() -> None:
    assert (
        file_api_authorized(
            {},
            ("127.0.0.1", 9527),
            proxy_secret="proxy-secret",
            production_mode=False,
            compare_secret=_compare_secret,
        )
        is True
    )
    assert (
        file_api_authorized(
            {},
            ("::1", 9527),
            proxy_secret="proxy-secret",
            production_mode=False,
            compare_secret=_compare_secret,
        )
        is True
    )
    assert (
        file_api_authorized(
            {},
            ("127.0.0.1", 9527),
            proxy_secret="proxy-secret",
            production_mode=True,
            compare_secret=_compare_secret,
        )
        is False
    )


def test_file_api_authorized_does_not_trust_spoofed_host_header() -> None:
    authorized = file_api_authorized(
        {"Host": "localhost:9527"},
        ("203.0.113.8", 1234),
        proxy_secret="proxy-secret",
        production_mode=False,
        compare_secret=_compare_secret,
    )

    assert authorized is False


def test_file_api_authorized_rejects_missing_or_invalid_client_address() -> None:
    assert file_api_authorized({}, None, proxy_secret="proxy-secret", production_mode=False, compare_secret=_compare_secret) is False
    assert (
        file_api_authorized(
            {},
            ("not-an-ip", 9527),
            proxy_secret="proxy-secret",
            production_mode=False,
            compare_secret=_compare_secret,
        )
        is False
    )
