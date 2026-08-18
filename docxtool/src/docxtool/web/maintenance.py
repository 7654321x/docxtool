"""Web 后台维护线程辅助。

当前产品策略要求用户原件、生成文件、日志和任务记录永久保留，因此维护线程只保留
兼容的定时唤醒入口，不执行任何删除动作。
"""

from __future__ import annotations

import time
from typing import Callable


def cleaner_loop(interval_minutes: int, *, sleep: Callable[[float], None] = time.sleep) -> None:
    """传入维护间隔分钟数和 sleep 函数，持续唤醒兼容维护线程且不删除数据。"""
    while True:
        sleep(max(60, interval_minutes * 60))
        # Permanent retention is enforced elsewhere; this loop intentionally
        # performs no cleanup after waking.
