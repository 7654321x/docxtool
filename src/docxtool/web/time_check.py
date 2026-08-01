"""Startup time-check helpers for the web service."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen

BEIJING_TZ = timezone(timedelta(hours=8))
NETWORK_TIME_URLS = (
    "https://www.baidu.com/",
    "https://www.cloudflare.com/",
)


def now_local() -> str:
    """无需传入数据，返回本机本地时间的 24 小时制字符串。"""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def parse_http_date_to_beijing(date_header: str) -> datetime:
    """传入 HTTP Date 头，返回转换到北京时间时区的 datetime。"""
    dt = parsedate_to_datetime(date_header)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING_TZ)


def fetch_beijing_network_time(
    timeout: int = 3,
    urls: Sequence[str] = NETWORK_TIME_URLS,
) -> datetime:
    """传入超时秒数和候选 URL，返回从 HTTP Date 解析出的北京时间。"""
    last_error = None
    for url in urls:
        try:
            req = Request(
                url,
                method="HEAD",
                headers={"User-Agent": "docx-tool-time-check/1.0"},
            )
            with urlopen(req, timeout=timeout) as resp:
                date_header = resp.headers.get("Date")
            if date_header:
                return parse_http_date_to_beijing(date_header)
            last_error = RuntimeError(f"{url} missing Date header")
        except Exception as exc:
            last_error = exc
    raise RuntimeError(str(last_error) if last_error else "no network time source")


def startup_time_check_lines(
    *,
    now_func: Callable[[], str] = now_local,
    fetch_func: Callable[[], datetime] = fetch_beijing_network_time,
) -> list[str]:
    """传入本地时间和网络时间回调，返回启动日志的时间校验提示行。"""
    system_time = now_func()
    try:
        beijing_time = fetch_func()
    except Exception as exc:
        return [f"时间校验: 未能获取北京网络时间，继续启动。原因: {exc}"]

    beijing_text = beijing_time.strftime("%Y-%m-%d %H:%M:%S")
    if system_time[:16] == beijing_text[:16]:
        return [f"时间校验: 通过，系统时间与北京网络时间相同（{system_time[:16]}）"]
    return [
        "时间校验: 系统时间与北京网络时间不一致，建议检查服务器时区/NTP。",
        f"系统时间为：{system_time[:16]}",
        f"北京时间为：{beijing_text[:16]}",
        "可执行: sudo timedatectl set-timezone Asia/Shanghai",
        "可执行: sudo timedatectl set-ntp true",
    ]
