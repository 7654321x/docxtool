from docxtool.web import app as server
from docxtool.web.client_ip import (
    client_ip,
    compare_secret,
    is_ip,
    split_ip_header,
    trusted_proxy_source,
)


def test_client_ip_prefers_cf_connecting_ipv6_over_proxy_ipv4():
    headers = {
        "CF-Connecting-IP": "2400:1234::5678",
        "X-Forwarded-For": "2400:1234::5678, 104.16.1.1",
        "X-Real-IP": "104.16.1.1",
    }

    resolved = client_ip(
        headers,
        ("127.0.0.1", 12345),
        trust_proxy_headers=True,
        trusted_proxy_ips={"127.0.0.1", "::1"},
    )

    assert resolved == "2400:1234::5678"
    assert server._client_ip(headers, ("127.0.0.1", 12345)) == resolved


def test_client_ip_uses_leftmost_x_forwarded_for_when_cf_header_missing():
    headers = {"X-Forwarded-For": "2400:1234::100, 104.18.0.1"}

    assert client_ip(
        headers,
        ("127.0.0.1", 12345),
        trust_proxy_headers=True,
        trusted_proxy_ips={"127.0.0.1"},
    ) == "2400:1234::100"


def test_client_ip_ignores_forwarded_headers_from_untrusted_socket():
    headers = {"CF-Connecting-IP": "203.0.113.8", "X-Forwarded-For": "198.51.100.9"}

    assert client_ip(
        headers,
        ("203.0.113.77", 12345),
        trust_proxy_headers=True,
        trusted_proxy_ips={"127.0.0.1"},
    ) == "203.0.113.77"


def test_client_ip_helpers_validate_headers_and_secrets():
    assert trusted_proxy_source(
        ("::1", 12345),
        trust_proxy_headers=True,
        trusted_proxy_ips={"::1"},
    )
    assert not trusted_proxy_source(
        ("::1", 12345),
        trust_proxy_headers=False,
        trusted_proxy_ips={"::1"},
    )
    assert split_ip_header(" 198.51.100.9, , 203.0.113.8 ") == ["198.51.100.9", "203.0.113.8"]
    assert is_ip("240e:398:41bb:c470:392d:4351:2b3f:b7c")
    assert compare_secret("same-secret", "same-secret")
    assert not compare_secret("same-secret", "other-secret")


def test_client_ip_uses_x_real_ip_when_higher_priority_headers_are_invalid():
    headers = {
        "CF-Connecting-IP": "not-an-ip",
        "X-Forwarded-For": "also-not-an-ip",
        "X-Real-IP": "240e:398:41bb:c470:392d:4351:2b3f:b7c",
    }

    resolved = client_ip(
        headers,
        ("::1", 12345),
        trust_proxy_headers=True,
        trusted_proxy_ips={"::1"},
    )

    assert resolved == "240e:398:41bb:c470:392d:4351:2b3f:b7c"
    assert server._client_ip(headers, ("::1", 12345)) == resolved
