from __future__ import annotations

from collections import OrderedDict

from docxtool.web.task_cache import prune_task_cache


def _tasks(*pairs):
    """传入任务 ID 和状态元组，返回测试用有序任务映射。"""
    return OrderedDict((task_id, {"status": status}) for task_id, status in pairs)


def test_prune_task_cache_keeps_cache_when_under_limit() -> None:
    tasks = _tasks(("a", "done"), ("b", "processing"))

    removed = prune_task_cache(tasks, max_tasks=10, max_cached_tasks=10)

    assert removed == 0
    assert list(tasks) == ["a", "b"]


def test_prune_task_cache_uses_minimum_of_runtime_limits() -> None:
    tasks = _tasks(("a", "done"), ("b", "done"), ("c", "done"), ("d", "done"))

    removed = prune_task_cache(tasks, max_tasks=3, max_cached_tasks=2)

    assert removed == 2
    assert list(tasks) == ["c", "d"]


def test_prune_task_cache_preserves_existing_grouped_order_policy() -> None:
    tasks = _tasks(
        ("old-processing", "processing"),
        ("old-done", "done"),
        ("new-queued", "queued"),
        ("new-done", "done"),
        ("new-processing", "processing"),
    )

    removed = prune_task_cache(tasks, max_tasks=3, max_cached_tasks=3)

    assert removed == 2
    assert list(tasks) == ["new-processing", "old-done", "new-done"]


def test_prune_task_cache_never_uses_less_than_one_slot() -> None:
    tasks = _tasks(("a", "done"), ("b", "done"))

    removed = prune_task_cache(tasks, max_tasks=0, max_cached_tasks=0)

    assert removed == 1
    assert list(tasks) == ["b"]
