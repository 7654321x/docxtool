from __future__ import annotations

from urllib.parse import urlparse

from docxtool.web.request_params import parse_body_params, parse_query_params, request_params


def test_parse_query_params_returns_last_value_and_keeps_blank() -> None:
    """URL query 解析应保留空值，并在重复字段中返回最后一个值。"""
    assert parse_query_params("a=old&a=new&empty=") == {"a": "new", "empty": ""}


def test_parse_body_params_accepts_json_and_form_bodies() -> None:
    """请求体解析应同时支持 JSON 对象和 URL 编码表单。"""
    assert parse_body_params(b'{"a": 1, "b": "text"}', "application/json") == {"a": 1, "b": "text"}
    assert parse_body_params(b"a=old&a=new", "application/x-www-form-urlencoded") == {"a": "new"}


def test_parse_body_params_returns_empty_for_invalid_body() -> None:
    """非法 JSON 或非法 UTF-8 表单请求体应返回空字典，保持旧 Handler 容错行为。"""
    assert parse_body_params(b"[1,2,3]", "application/json") == {}
    assert parse_body_params(b"\xff\xfe", "application/x-www-form-urlencoded") == {}


def test_request_params_merges_body_over_query_for_mutation_methods() -> None:
    """POST/PUT/DELETE 请求应将 body 参数覆盖同名 query 参数后返回。"""
    parsed = urlparse("/path?a=query")
    params = request_params(
        parsed,
        "POST",
        {"Content-Length": "6", "Content-Type": "application/x-www-form-urlencoded"},
        lambda length: b"a=body"[:length],
    )

    assert params == {"a": "body"}


def test_request_params_does_not_read_body_for_get_or_invalid_length() -> None:
    """GET 或无效 Content-Length 时只返回 query 参数，不读取请求体。"""
    parsed = urlparse("/path?a=query")

    assert request_params(parsed, "GET", {"Content-Length": "6"}, lambda _length: b"a=body") == {"a": "query"}
    assert request_params(parsed, "POST", {"Content-Length": "bad"}, lambda _length: b"a=body") == {"a": "query"}
