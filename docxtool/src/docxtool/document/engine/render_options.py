"""Feature option parsing helpers for the DOCX renderer."""

from __future__ import annotations


def feature_options(options: dict | None) -> dict:
    """归一功能配置；传入可选 dict，返回 dict 或空 dict。"""
    return options if isinstance(options, dict) else {}


def feature_enabled(options: dict | None, default: bool = False) -> bool:
    """判断功能是否启用；传入配置和默认值，返回布尔结果。"""
    opts = feature_options(options)
    value = opts.get("enabled", default)
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on", "启用", "是"}:
        return True
    if raw in {"0", "false", "no", "off", "禁用", "否"}:
        return False
    return bool(default)
