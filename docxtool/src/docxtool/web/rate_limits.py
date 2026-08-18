"""Rate limit, IP ban, and upload quota helpers for the web service."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Callable, MutableMapping, Sequence

from docxtool.web.client_ip import is_ip


def allow(ip: str, *, rate_limit: MutableMapping[str, float], rate_lock, rate_window: int, now: float | None = None) -> bool:
    """传入 IP、限流桶、锁和窗口秒数，返回本次普通上传频率检查是否允许。"""
    current = time.time() if now is None else float(now)
    with rate_lock:
        last = rate_limit.get(ip, 0)
        if current - last < rate_window:
            return False
        rate_limit[ip] = current
        return True


def auth_rate_allow(
    scope: str,
    key: str,
    window: int,
    limit: int,
    *,
    auth_rate_limit: OrderedDict[str, list[float]],
    rate_lock,
    now: float | None = None,
    max_buckets: int = 4096,
) -> tuple[bool, int]:
    """传入限流作用域、键、窗口和次数上限，返回是否允许及重试等待秒数。"""
    current = time.time() if now is None else float(now)
    bucket_key = f"{scope}:{key}"
    with rate_lock:
        values = [stamp for stamp in auth_rate_limit.get(bucket_key, []) if current - stamp < window]
        if len(values) >= limit:
            return False, max(1, int(window - (current - values[0])))
        values.append(current)
        auth_rate_limit[bucket_key] = values
        auth_rate_limit.move_to_end(bucket_key)
        while len(auth_rate_limit) > max_buckets:
            auth_rate_limit.popitem(last=False)
    return True, 0


def settings_get(key: str, default: str = "", *, connect: Callable[[], Any], sql_lock) -> str:
    """传入设置键、默认值和数据库连接器，返回 settings 表中的字符串值。"""
    with sql_lock:
        conn = connect()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close()
    return _row_value(row, "value", 0, default)


def settings_set(key: str, value: str, *, connect: Callable[[], Any], sql_lock) -> None:
    """传入设置键值和数据库连接器，写入或更新 settings 表，无返回值。"""
    with sql_lock:
        conn = connect()
        conn.execute(
            """INSERT INTO settings(key,value) VALUES(?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, str(value)),
        )
        conn.commit()
        conn.close()


def limit_settings(
    *,
    connect: Callable[[], Any],
    sql_lock,
    default_window_seconds: int,
    default_count: int,
) -> dict:
    """传入数据库连接器和默认上传限制，返回归一化后的上传频率限制配置。"""
    enabled = settings_get("upload_limit_enabled", "0", connect=connect, sql_lock=sql_lock) == "1"
    try:
        window_seconds = int(settings_get("upload_limit_window_seconds", str(default_window_seconds), connect=connect, sql_lock=sql_lock))
    except ValueError:
        window_seconds = default_window_seconds
    try:
        count = int(settings_get("upload_limit_count", str(default_count), connect=connect, sql_lock=sql_lock))
    except ValueError:
        count = default_count
    return {
        "enabled": enabled,
        "window_seconds": max(1, window_seconds),
        "count": max(1, count),
    }


def save_limit_settings(
    enabled: bool,
    window_seconds: int,
    count: int,
    *,
    connect: Callable[[], Any],
    sql_lock,
) -> None:
    """传入上传限制开关、窗口和次数，持久化到 settings 表，无返回值。"""
    settings_set("upload_limit_enabled", "1" if enabled else "0", connect=connect, sql_lock=sql_lock)
    settings_set("upload_limit_window_seconds", str(max(1, int(window_seconds))), connect=connect, sql_lock=sql_lock)
    settings_set("upload_limit_count", str(max(1, int(count))), connect=connect, sql_lock=sql_lock)


def is_ip_banned(ip: str, *, connect: Callable[[], Any], sql_lock) -> bool:
    """传入 IP 和数据库连接器，返回该 IP 是否已在 banned_ips 表中。"""
    if not ip:
        return False
    with sql_lock:
        conn = connect()
        row = conn.execute("SELECT 1 FROM banned_ips WHERE ip=?", (ip,)).fetchone()
        conn.close()
    return row is not None


def ban_ip(ip: str, reason: str = "", *, connect: Callable[[], Any], sql_lock) -> None:
    """传入 IP、原因和数据库连接器，写入封禁记录；非法 IP 抛出 ValueError。"""
    if not is_ip(ip):
        raise ValueError("invalid ip")
    with sql_lock:
        conn = connect()
        conn.execute(
            """INSERT INTO banned_ips(ip, reason, created_at)
               VALUES(?,?,datetime('now','localtime'))
               ON CONFLICT(ip) DO UPDATE SET
               reason=excluded.reason, created_at=excluded.created_at""",
            (ip, reason or "manual"),
        )
        conn.commit()
        conn.close()


def unban_ip(ip: str, *, connect: Callable[[], Any], sql_lock) -> None:
    """传入 IP 和数据库连接器，从 banned_ips 表删除封禁记录，无返回值。"""
    with sql_lock:
        conn = connect()
        conn.execute("DELETE FROM banned_ips WHERE ip=?", (ip,))
        conn.commit()
        conn.close()


def banned_ips(*, connect: Callable[[], Any], sql_lock) -> list[dict]:
    """传入数据库连接器，返回按创建时间倒序排列的封禁 IP 字典列表。"""
    with sql_lock:
        conn = connect()
        rows = conn.execute("SELECT * FROM banned_ips ORDER BY created_at DESC").fetchall()
        conn.close()
    return [dict(row) for row in rows]


def ip_activity(ip: str, limit: int = 100, *, connect: Callable[[], Any], sql_lock) -> list[dict]:
    """传入 IP、数量上限和数据库连接器，返回该 IP 最近任务记录列表。"""
    with sql_lock:
        conn = connect()
        rows = conn.execute(
            """SELECT * FROM tasks WHERE ip=?
               ORDER BY created_at DESC, done_at DESC
               LIMIT ?""",
            (ip, limit),
        ).fetchall()
        conn.close()
    return [dict(row) for row in rows]


def ip_upload_count(ip: str, window_seconds: int = 0, *, connect: Callable[[], Any], sql_lock) -> int:
    """传入 IP、时间窗口和数据库连接器，返回窗口内上传任务数量。"""
    with sql_lock:
        conn = connect()
        if window_seconds and window_seconds > 0:
            row = conn.execute(
                """SELECT COUNT(*) as c FROM tasks
                   WHERE ip=? AND created_at>=datetime('now','localtime', ?)""",
                (ip, f"-{int(window_seconds)} seconds"),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE ip=?", (ip,)).fetchone()
        conn.close()
    return int(_row_value(row, "c", 0, 0) or 0)


def upload_limit_exceeded(
    ip: str,
    *,
    connect: Callable[[], Any],
    sql_lock,
    default_window_seconds: int,
    default_count: int,
) -> bool:
    """传入 IP、数据库连接器和默认限制，返回该 IP 是否超过上传频率限制。"""
    settings = limit_settings(
        connect=connect,
        sql_lock=sql_lock,
        default_window_seconds=default_window_seconds,
        default_count=default_count,
    )
    if not settings["enabled"]:
        return False
    return ip_upload_count(ip, settings["window_seconds"], connect=connect, sql_lock=sql_lock) >= settings["count"]


def _row_value(row: Any, key: str, index: int, default: Any = None) -> Any:
    """传入 sqlite row 或序列，按键或下标取值；缺失时返回默认值。"""
    if row is None:
        return default
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        pass
    if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
        try:
            return row[index]
        except IndexError:
            return default
    return default
