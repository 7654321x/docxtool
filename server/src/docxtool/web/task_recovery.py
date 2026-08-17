"""Startup recovery for tasks left in non-terminal states."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock


INFLIGHT_STATUSES = ("queued", "processing")
INTERRUPTED_ERROR_MESSAGE = "服务重启后任务中断"


def recover_inflight_tasks_on_startup(
    *,
    connect: Callable,
    sql_lock: Lock,
    now_func: Callable[[], str],
) -> int:
    """传入连接工厂、线程锁和当前时间函数，将启动前未完成任务标记为中断并返回数量。"""
    now = now_func()
    with sql_lock:
        conn = connect()
        try:
            rows = conn.execute(
                "SELECT id, status FROM tasks WHERE status IN ('queued', 'processing')"
            ).fetchall()
            if rows:
                conn.execute(
                    """UPDATE tasks
                       SET status='interrupted', error=?, done_at=?
                       WHERE status IN ('queued', 'processing')""",
                    (INTERRUPTED_ERROR_MESSAGE, now),
                )
                conn.commit()
        finally:
            conn.close()
    return len(rows)
