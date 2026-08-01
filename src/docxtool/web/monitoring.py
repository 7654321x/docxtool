"""Pure monitor-page query, pagination, and URL helpers."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode

DEFAULT_MONITOR_PAGE_SIZE = 50
MAX_MONITOR_PAGE_SIZE = 100


def first_query_value(values: dict, key: str, default: object = "") -> object:
    """传入查询参数字典和键名，返回该键第一个值或默认值。"""
    raw = values.get(key, default) if values else default
    if isinstance(raw, list):
        return raw[0] if raw else default
    return raw


def clamp_int(
    value: object,
    default: int,
    min_value: int = 1,
    max_value: int = MAX_MONITOR_PAGE_SIZE,
) -> int:
    """传入任意值和整数边界，返回限制在范围内的整数。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(min_value, min(max_value, n))


def normalize_monitor_query(values: dict | None = None) -> dict[str, int]:
    """传入 parse_qs 风格字典，返回监控页分页查询配置。"""
    values = values or {}
    return {
        "recent_page": clamp_int(first_query_value(values, "recent_page", 1), 1),
        "recent_size": clamp_int(
            first_query_value(values, "recent_size", DEFAULT_MONITOR_PAGE_SIZE),
            DEFAULT_MONITOR_PAGE_SIZE,
        ),
        "ip_page": clamp_int(first_query_value(values, "ip_page", 1), 1),
        "ip_size": clamp_int(
            first_query_value(values, "ip_size", DEFAULT_MONITOR_PAGE_SIZE),
            DEFAULT_MONITOR_PAGE_SIZE,
        ),
    }


def monitor_query_from(parsed) -> dict[str, int]:
    """传入 urlparse 结果，返回忽略非分页过滤条件后的监控查询。"""
    return normalize_monitor_query(parse_qs(parsed.query))


def where_sql(clauses) -> str:
    """传入 SQL 条件片段列表，返回可拼接的 WHERE 子句。"""
    return " WHERE " + " AND ".join(clauses) if clauses else ""


def page_count(total: int, size: int) -> int:
    """传入总数和每页数量，返回至少为 1 的页数。"""
    return max(1, (int(total) + int(size) - 1) // int(size))


def monitor_url(query: dict, **overrides) -> str:
    """传入当前查询和覆盖项，返回监控页分页链接。"""
    q = dict(query or {})
    q.update(overrides)
    values = {}
    for key in ("recent_page", "recent_size", "ip_page", "ip_size"):
        value = q.get(key, "")
        if value != "":
            values[key] = value
    return "/monitor?" + urlencode(values) if values else "/monitor"
