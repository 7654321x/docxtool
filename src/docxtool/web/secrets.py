"""Web secret loading and startup validation helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping


def load_secret(name: str, default: str, environ: Mapping[str, str] | None = None) -> str:
    """传入环境变量名、默认值和可选环境映射，返回去空白后的密钥字符串。"""
    source = os.environ if environ is None else environ
    value = source.get(name, default).strip()
    return value or default


def validate_required_secrets(admin_token: str, proxy_secret: str, weak_secrets: set[str]) -> None:
    """传入管理密钥、代理密钥和弱密钥集合；无返回值，非法时抛出 SystemExit。"""
    admin = admin_token.strip()
    proxy = proxy_secret.strip()
    if not admin or not proxy:
        raise SystemExit("[配置错误] ADMIN_TOKEN 和 PROXY_SECRET 不能为空。")
    if len(admin) < 16 or admin in weak_secrets:
        raise SystemExit("[配置错误] ADMIN_TOKEN 使用了示例/弱密钥，请替换为随机长密钥后再启动。")
    if len(proxy) < 16 or proxy in weak_secrets:
        raise SystemExit("[配置错误] PROXY_SECRET 使用了示例/弱密钥，请替换为随机长密钥后再启动。")
    if admin == proxy:
        raise SystemExit("[配置错误] ADMIN_TOKEN 和 PROXY_SECRET 不能相同。")
