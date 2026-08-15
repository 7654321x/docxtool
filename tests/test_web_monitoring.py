from urllib.parse import urlparse

from docxtool.web import app as server
from docxtool.web.monitoring import (
    clamp_int,
    first_query_value,
    monitor_query_from,
    monitor_url,
    normalize_monitor_query,
    page_count,
    where_sql,
)


def test_monitoring_query_helpers_normalize_and_clamp_values() -> None:
    """监控查询函数应归一化分页字段和可选任务筛选字段。"""
    values = {
        "recent_page": ["2"],
        "recent_size": ["999"],
        "ip_page": ["bad"],
        "ip_size": ["25"],
        "start": ["ignored"],
    }

    assert first_query_value(values, "recent_page", 1) == "2"
    assert clamp_int("999", 50) == 100
    assert normalize_monitor_query(values) == {
        "recent_page": 2,
        "recent_size": 100,
        "ip_page": 1,
        "ip_size": 25,
        "task_q": "",
        "task_status": "",
    }


def test_monitoring_url_and_sql_helpers_are_stable() -> None:
    """监控 URL 和 SQL 辅助函数传入分页数据后，应生成稳定字符串。"""
    assert where_sql(["status=?", "ip=?"]) == " WHERE status=? AND ip=?"
    assert where_sql([]) == ""
    assert page_count(101, 50) == 3
    assert monitor_url({"recent_page": 1, "recent_size": 50}, recent_page=2) == (
        "/monitor?recent_page=2&recent_size=50"
    )


def test_monitoring_module_matches_app_facade() -> None:
    """新监控模块传入 URL 后，应与 web.app 兼容入口返回相同查询。"""
    parsed = urlparse("/monitor?recent_page=2&ip_size=999&start=ignored")

    assert monitor_query_from(parsed) == server._monitor_query_from(parsed)
