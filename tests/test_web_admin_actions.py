from __future__ import annotations

from urllib.parse import urlparse

from docxtool.web.admin_actions import (
    ban_reason_from_params,
    ip_from_action_params,
    is_post_only_action_path,
    query_ip_from_parsed_url,
    upload_limit_values_from_params,
)


def test_query_ip_from_parsed_url_accepts_ip_or_addr() -> None:
    """传入解析后的 URL 时，应优先读取 ip 参数，并兼容 addr 参数。"""
    assert query_ip_from_parsed_url(urlparse("/monitor/ip?ip=203.0.113.8&addr=198.51.100.2")) == "203.0.113.8"
    assert query_ip_from_parsed_url(urlparse("/monitor/ip?addr=198.51.100.2")) == "198.51.100.2"
    assert query_ip_from_parsed_url(urlparse("/monitor/ip")) == ""


def test_ip_from_action_params_accepts_ip_or_addr() -> None:
    """传入管理动作参数时，应优先读取 ip 字段，并兼容 addr 字段。"""
    assert ip_from_action_params({"ip": " 203.0.113.8 ", "addr": "198.51.100.2"}) == "203.0.113.8"
    assert ip_from_action_params({"addr": " 198.51.100.2 "}) == "198.51.100.2"
    assert ip_from_action_params({}) == ""


def test_is_post_only_action_path_matches_admin_mutations() -> None:
    """管理员动作路径中，封禁、解封、限流和清理入口只能通过 POST 调用。"""
    for path in ("/ban", "/unban", "/limit", "/cleanup"):
        assert is_post_only_action_path(path)
    assert not is_post_only_action_path("/monitor")


def test_ban_reason_from_params_uses_default_and_limit() -> None:
    """封禁原因应支持默认值并按配置长度截断。"""
    assert ban_reason_from_params({}) == "monitor"
    assert ban_reason_from_params({"reason": "abcdef"}, limit=3) == "abc"


def test_upload_limit_values_from_params_parses_or_falls_back() -> None:
    """上传限制参数应解析启用状态、窗口和次数，并在非法值时回退默认值。"""
    assert upload_limit_values_from_params(
        {"enabled": "1", "window_seconds": "1800", "count": "5"},
        default_window_seconds=3600,
        default_count=10,
    ) == (True, 1800, 5)
    assert upload_limit_values_from_params(
        {"enabled": "0", "window_seconds": "bad", "count": object()},
        default_window_seconds=3600,
        default_count=10,
    ) == (False, 3600, 10)
