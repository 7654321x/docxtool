"""文件 API 请求授权判断辅助。

本模块只根据调用方传入的请求头、客户端地址和代理密钥判断是否允许访问文件 API。
"""

from __future__ import annotations

import ipaddress
from typing import Callable, Mapping


def file_api_authorized(
    headers: Mapping[str, str] | None,
    client_address: tuple[object, ...] | None,
    *,
    proxy_secret: str,
    production_mode: bool,
    compare_secret: Callable[[str, str], bool],
) -> bool:
    """传入请求头、客户端地址和密钥配置，返回文件 API 是否授权。"""
    header_token = headers.get("X-Proxy-Secret", "") if headers else ""
    if compare_secret(header_token, proxy_secret):
        return True
    if production_mode:
        return False
    return _is_loopback_client(client_address)


def _is_loopback_client(client_address: tuple[object, ...] | None) -> bool:
    """传入 socket client_address 元组，返回对端 IP 是否为本机回环地址。"""
    if not client_address:
        return False
    try:
        return ipaddress.ip_address(str(client_address[0])).is_loopback
    except ValueError:
        return False
