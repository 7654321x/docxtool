"""In-memory task cache pruning helpers."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import MutableMapping


ACTIVE_STATUSES = {"queued", "processing"}


def prune_task_cache(tasks: MutableMapping, max_tasks: int, max_cached_tasks: int) -> int:
    """传入任务有序映射和容量配置，原地裁剪缓存并返回删除的任务数量。"""
    cache_limit = max(1, min(max_tasks, max_cached_tasks))
    original_size = len(tasks)
    if original_size <= cache_limit:
        return 0
    keep = OrderedDict()
    recent = list(tasks.items())
    active = [(key, value) for key, value in recent if value.get("status") in ACTIVE_STATUSES]
    done = [(key, value) for key, value in recent if value.get("status") not in ACTIVE_STATUSES]
    ordered = active + done
    for key, value in ordered[-cache_limit:]:
        keep[key] = value
    tasks.clear()
    tasks.update(keep)
    return original_size - len(tasks)
