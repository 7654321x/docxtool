from datetime import datetime, timezone

from docxtool.web import app as server
from docxtool.web.time_check import (
    parse_http_date_to_beijing,
    startup_time_check_lines,
)


def test_time_check_parses_http_date_to_beijing() -> None:
    """时间校验模块传入 HTTP Date 后，应返回北京时间 datetime。"""
    dt = parse_http_date_to_beijing("Tue, 02 Jun 2026 05:24:33 GMT")

    assert dt.strftime("%Y-%m-%d %H:%M:%S") == "2026-06-02 13:24:33"
    assert dt == server._parse_http_date_to_beijing("Tue, 02 Jun 2026 05:24:33 GMT")


def test_startup_time_check_reports_match_and_mismatch() -> None:
    """启动时间校验传入本地和网络时间回调后，应返回对应提示行。"""
    same = startup_time_check_lines(
        now_func=lambda: "2026-06-02 13:24:05",
        fetch_func=lambda: datetime(2026, 6, 2, 13, 24, 33, tzinfo=timezone.utc),
    )
    different = startup_time_check_lines(
        now_func=lambda: "2026-06-02 01:24:05",
        fetch_func=lambda: datetime(2026, 6, 2, 13, 24, 33, tzinfo=timezone.utc),
    )

    assert "通过" in same[0]
    assert "系统时间与北京网络时间不一致" in different[0]
    assert "系统时间为：2026-06-02 01:24" in different[1]


def test_startup_time_check_reports_fetch_failure() -> None:
    """启动时间校验传入失败网络回调后，应返回不中断启动的提示。"""
    lines = startup_time_check_lines(
        now_func=lambda: "2026-06-02 13:24:05",
        fetch_func=lambda: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    assert "未能获取北京网络时间" in lines[0]
    assert "network down" in lines[0]
