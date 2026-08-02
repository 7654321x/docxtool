from __future__ import annotations

import subprocess
import sys

from docxtool.web import app
from docxtool.web import handler


def test_runtime_state_objects_are_shared_with_app_facade() -> None:
    state = app._RUNTIME_STATE
    assert app.RATE_LIMIT is state.rate_limit
    assert app.RATE_LOCK is state.rate_lock
    assert app.AUTH_RATE_LIMIT is state.auth_rate_limit
    assert app.TASKS is state.tasks
    assert app.TASKS_LOCK is state.tasks_lock
    assert app.TASK_QUEUE is state.task_queue
    assert app.QUEUE_COND is state.queue_condition
    assert app.WORKER_STATE is state.worker_state
    assert app.WORKERS_LOCK is state.workers_lock
    assert app.WORKER_THREADS is state.worker_threads


def test_handler_is_reexported_from_app_facade() -> None:
    assert app.Handler is handler.Handler


def test_app_reload_rebuilds_one_runtime_state_and_keeps_facades() -> None:
    code = """
import importlib
from docxtool.web import app
old_tasks = app.TASKS
reloaded = importlib.reload(app)
assert reloaded.TASKS is reloaded._RUNTIME_STATE.tasks
assert reloaded.TASKS is not old_tasks
assert reloaded.Handler.__name__ == 'Handler'
assert callable(reloaded._sql)
assert callable(reloaded.main)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
