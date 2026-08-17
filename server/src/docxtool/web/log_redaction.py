"""Web 日志展示前的敏感字段脱敏辅助。

本模块只处理传入的日志文本，不读取日志文件、不访问 HTTP 请求或任务状态。
"""

from __future__ import annotations

import re

SENSITIVE_LOG_FIELD_NAMES = (
    "ADMIN_TOKEN",
    "PROXY_SECRET",
    "Authorization",
    "Proxy-Authorization",
    "Cookie",
    "Set-Cookie",
)


def redact_sensitive_log(text: object, *, field_names: tuple[str, ...] = SENSITIVE_LOG_FIELD_NAMES) -> str:
    """传入日志文本和字段名列表，返回已隐藏认证字段值的日志字符串。"""
    value = str(text or "")
    for name in field_names:
        value = re.sub(
            rf"(?im)^({name}\s*[:=]\s*).+$",
            r"\1[REDACTED]",
            value,
        )
    return value
