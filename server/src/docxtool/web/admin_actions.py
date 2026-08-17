"""Parameter helpers for administrator monitor actions."""

from __future__ import annotations

from typing import Mapping
from urllib.parse import parse_qs

POST_ONLY_ACTION_PATHS = frozenset({"/ban", "/unban", "/limit", "/cleanup"})


def query_ip_from_parsed_url(parsed) -> str:
    """传入已解析 URL，返回监控详情页中的 ip/addr 查询参数。"""
    values = parse_qs(parsed.query)
    return (values.get("ip") or values.get("addr") or [""])[0].strip()


def is_post_only_action_path(path: str) -> bool:
    """传入请求路径，返回是否为只能通过 POST 调用的管理员动作。"""
    return str(path or "") in POST_ONLY_ACTION_PATHS


def ip_from_action_params(params: Mapping[str, object] | None) -> str:
    """传入管理动作参数字典，返回 ip 或 addr 字段中的 IP 字符串。"""
    return str((params or {}).get("ip") or (params or {}).get("addr") or "").strip()


def ban_reason_from_params(params: Mapping[str, object] | None, *, default: str = "monitor", limit: int = 120) -> str:
    """传入管理动作参数，返回长度受限的封禁原因字符串。"""
    return str((params or {}).get("reason") or default)[: max(0, int(limit))]


def upload_limit_values_from_params(
    params: Mapping[str, object] | None,
    *,
    default_window_seconds: int,
    default_count: int,
) -> tuple[bool, int, int]:
    """传入限流表单参数和默认值，返回 enabled、窗口秒数和次数上限。"""
    values = params or {}
    enabled = str(values.get("enabled") or "0") == "1"
    try:
        window_seconds = int(values.get("window_seconds") or default_window_seconds)
    except (TypeError, ValueError):
        window_seconds = default_window_seconds
    try:
        count = int(values.get("count") or default_count)
    except (TypeError, ValueError):
        count = default_count
    return enabled, window_seconds, count
