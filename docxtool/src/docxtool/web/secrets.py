"""Web secret loading and startup validation helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping


DEFAULT_ADMIN_TOKEN = "7654321xxx"
DEFAULT_PROXY_SECRET = "docxtool-proxy-20260601-9ec0d6e2443a4f5f9784f0f04bb62917"
WEAK_SECRETS = frozenset(
    {
        "",
        "123456",
        "admin",
        "change-me-admin-token",
        "change-me-proxy-secret",
        "change-me-in-production",
        DEFAULT_ADMIN_TOKEN,
        DEFAULT_PROXY_SECRET,
    }
)


def load_secret(name: str, default: str, environ: Mapping[str, str] | None = None) -> str:
    """传入环境变量名、默认值和可选环境映射，返回去空白后的密钥字符串。"""
    source = os.environ if environ is None else environ
    value = source.get(name, default).strip()
    return value or default


def validate_required_secrets(
    admin_token: str,
    proxy_secret: str,
    weak_secrets: frozenset[str] = WEAK_SECRETS,
) -> None:
    """校验两个密钥；非法时抛出 SystemExit，弱值规则由本模块唯一维护。"""
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


def validate_environment_secrets(environ: Mapping[str, str]) -> None:
    """从环境映射读取生产密钥并按本模块唯一规则校验。"""
    validate_required_secrets(
        load_secret("ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN, environ),
        load_secret("PROXY_SECRET", DEFAULT_PROXY_SECRET, environ),
    )
