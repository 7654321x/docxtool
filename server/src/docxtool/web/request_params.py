"""Request parameter parsing helpers for Web handlers."""

from __future__ import annotations

from typing import Callable, Mapping
from urllib.parse import parse_qs

from docxtool.web.request_utils import parse_json_body


def parse_query_params(query: str) -> dict:
    """传入 URL query 字符串，返回每个参数最后一个值组成的字典。"""
    return {key: (values[-1] if isinstance(values, list) and values else values) for key, values in parse_qs(query, keep_blank_values=True).items()}


def parse_body_params(body: bytes, content_type: str) -> dict:
    """传入请求体 bytes 和 Content-Type，返回 JSON 或表单参数字典。"""
    if not body:
        return {}
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    try:
        if normalized_type == "application/json":
            return parse_json_body(body)
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        return {key: (values[-1] if isinstance(values, list) and values else values) for key, values in parsed.items()}
    except Exception:
        return {}


def request_params(
    parsed,
    method: str,
    headers: Mapping[str, str] | None,
    read_body: Callable[[int], bytes],
) -> dict:
    """传入 URL、HTTP 方法、请求头和读取函数，返回合并后的请求参数。"""
    params = parse_query_params(parsed.query)
    if str(method or "").upper() not in {"POST", "PUT", "DELETE"}:
        return params
    try:
        length = int((headers or {}).get("Content-Length", 0) or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return params
    body_params = parse_body_params(read_body(length), (headers or {}).get("Content-Type", ""))
    params.update(body_params)
    return params
