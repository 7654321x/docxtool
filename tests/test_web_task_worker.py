from __future__ import annotations

from docxtool.web.task_worker import run_task_with_execution_boundary, start_worker_threads


def _runner_factory(name: str, calls: list[str]):
    """传入路径名和调用记录列表，返回可断言执行路径的任务 runner。"""

    def _runner(task_id, input_path, orig_name, ip, ua, format_config, request_meta):
        """接收任务参数并返回带路径名的测试结果。"""
        calls.append(name)
        assert task_id == "task-1"
        assert input_path == "input.docx"
        assert orig_name == "upload.docx"
        assert ip == "127.0.0.1"
        assert ua == "pytest"
        assert format_config == {"mode": "smart"}
        assert request_meta == {"owner": "anon"}
        return {"ok": True, "path": name}

    return _runner


def test_run_task_with_execution_boundary_uses_direct_runner_for_main_thread() -> None:
    calls: list[str] = []
    recorded: list[tuple[str, dict]] = []

    def _record(task_id, input_path, orig_name, ip, ua, result):
        """记录任务结果，供测试确认执行后统一收口。"""
        recorded.append((task_id, result))

    result = run_task_with_execution_boundary(
        "task-1",
        "input.docx",
        "upload.docx",
        "127.0.0.1",
        "pytest",
        {"mode": "smart"},
        {"owner": "anon"},
        is_main_thread=True,
        direct_runner=_runner_factory("direct", calls),
        subprocess_runner=_runner_factory("subprocess", calls),
        record_result=_record,
    )

    assert result == {"ok": True, "path": "direct"}
    assert calls == ["direct"]
    assert recorded == [("task-1", result)]


def test_run_task_with_execution_boundary_uses_subprocess_runner_for_worker_thread() -> None:
    calls: list[str] = []
    recorded: list[tuple[str, dict]] = []

    def _record(task_id, input_path, orig_name, ip, ua, result):
        """记录任务结果，供测试确认子进程路径也进入统一收口。"""
        recorded.append((task_id, result))

    result = run_task_with_execution_boundary(
        "task-1",
        "input.docx",
        "upload.docx",
        "127.0.0.1",
        "pytest",
        {"mode": "smart"},
        {"owner": "anon"},
        is_main_thread=False,
        direct_runner=_runner_factory("direct", calls),
        subprocess_runner=_runner_factory("subprocess", calls),
        record_result=_record,
    )

    assert result == {"ok": True, "path": "subprocess"}
    assert calls == ["subprocess"]
    assert recorded == [("task-1", result)]


def test_start_worker_threads_names_daemon_threads_and_starts_them() -> None:
    created: list[_FakeThread] = []

    def _thread_factory(*, target, name, daemon):
        """接收线程参数并返回可观察 start 调用的假线程。"""
        thread = _FakeThread(target=target, name=name, daemon=daemon)
        created.append(thread)
        return thread

    threads = start_worker_threads(2, lambda: None, thread_factory=_thread_factory)

    assert threads == created
    assert [thread.name for thread in threads] == ["docx-worker-1", "docx-worker-2"]
    assert [thread.daemon for thread in threads] == [True, True]
    assert [thread.started for thread in threads] == [True, True]


class _FakeThread:
    """保存线程构造参数和启动状态，避免单元测试创建真实后台线程。"""

    def __init__(self, *, target, name: str, daemon: bool) -> None:
        self.target = target
        self.name = name
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        """标记线程已启动，供断言使用。"""
        self.started = True
