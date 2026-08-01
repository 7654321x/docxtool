"""Client IP and trusted proxy helpers for the Web compatibility service."""

from __future__ import annotations

import hmac
import ipaddress


def is_ip(value: str) -> bool:
    """Return whether the input string is a valid IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    return True


def is_ipv4(value: str) -> bool:
    """Return whether the input string is a valid IPv4 address."""
    try:
        return isinstance(ipaddress.ip_address(str(value or "").strip()), ipaddress.IPv4Address)
    except ValueError:
        return False


def split_ip_header(value: str) -> list[str]:
    """Split a comma-separated proxy IP header into trimmed non-empty candidates."""
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def trusted_proxy_source(client_address, *, trust_proxy_headers: bool, trusted_proxy_ips) -> bool:
    """Check whether a socket client address is allowed to supply proxy headers."""
    if not trust_proxy_headers:
        return False
    if not client_address:
        return False
    ip = str(client_address[0] or "").strip()
    if not ip:
        return False
    return ip in set(trusted_proxy_ips or ())


def compare_secret(value: str, secret: str) -> bool:
    """Compare a provided secret with the configured secret using constant-time comparison."""
    return bool(value) and bool(secret) and hmac.compare_digest(value, secret)


def client_ip(headers, client_address, *, trust_proxy_headers: bool, trusted_proxy_ips) -> str:
    """Resolve the real client IP from trusted proxy headers and socket address."""
    socket_ip = client_address[0] if client_address else ""
    if not trusted_proxy_source(
        client_address,
        trust_proxy_headers=trust_proxy_headers,
        trusted_proxy_ips=trusted_proxy_ips,
    ):
        return socket_ip

    candidates = []
    for name in ("X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP"):
        candidates.extend(split_ip_header(headers.get(name, "") if headers else ""))
    if socket_ip:
        candidates.append(socket_ip)
    for ip in candidates:
        if is_ipv4(ip):
            return ip
    for ip in candidates:
        if is_ip(ip):
            return ip
    return socket_ip
