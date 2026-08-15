from docxtool.web import app as server
from docxtool.web.client_ip import (
    client_ip,
    compare_secret,
    is_ip,
    is_ipv4,
    split_ip_header,
    trusted_proxy_source,
)


def test_client_ip_prefers_ipv4_from_trusted_proxy_headers():
    headers = {
        "CF-Connecting-IP": "240e:398:41bb:c470:392d:4351:2b3f:b7c",
        "X-Forwarded-For": "240e:398:41bb:c470:392d:4351:2b3f:b7c, 203.0.113.8",
        "X-Real-IP": "198.51.100.9",
    }

    resolved = client_ip(
        headers,
        ("127.0.0.1", 12345),
        trust_proxy_headers=True,
        trusted_proxy_ips={"127.0.0.1", "::1"},
    )

    assert resolved == "203.0.113.8"
    assert server._client_ip(headers, ("127.0.0.1", 12345)) == resolved


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
    assert is_ipv4("203.0.113.8")
    assert not is_ipv4("240e:398:41bb:c470:392d:4351:2b3f:b7c")
    assert is_ip("240e:398:41bb:c470:392d:4351:2b3f:b7c")
    assert compare_secret("same-secret", "same-secret")
    assert not compare_secret("same-secret", "other-secret")


def test_client_ip_falls_back_to_ipv6_when_no_ipv4_exists():
    """唯一 IPv6 来源（无 IPv4）时回退到合法 IPv6 地址。"""
    headers = {"CF-Connecting-IP": "240e:398:41bb:c470:392d:4351:2b3f:b7c"}

    resolved = client_ip(
        headers,
        ("::1", 12345),
        trust_proxy_headers=True,
        trusted_proxy_ips={"::1"},
    )

    assert resolved == "240e:398:41bb:c470:392d:4351:2b3f:b7c"
    assert server._client_ip(headers, ("::1", 12345)) == resolved
