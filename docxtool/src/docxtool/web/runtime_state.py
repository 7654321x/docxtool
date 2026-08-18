"""Factories for one Web app import's process-local shared state."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class RuntimeState:
    rate_limit: dict
    rate_lock: threading.Lock
    auth_rate_limit: OrderedDict
    tasks: OrderedDict
    tasks_lock: threading.Lock
    task_queue: OrderedDict
    queue_condition: threading.Condition
    worker_state: dict
    workers_lock: threading.Lock
    worker_threads: list


def create_sql_lock() -> threading.Lock:
    return threading.Lock()


def create_runtime_state() -> RuntimeState:
    return RuntimeState(
        rate_limit={},
        rate_lock=threading.Lock(),
        auth_rate_limit=OrderedDict(),
        tasks=OrderedDict(),
        tasks_lock=threading.Lock(),
        task_queue=OrderedDict(),
        queue_condition=threading.Condition(),
        worker_state={"started": False},
        workers_lock=threading.Lock(),
        worker_threads=[],
    )
