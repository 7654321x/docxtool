from __future__ import annotations

import threading
from collections import OrderedDict
from queue import Empty

from docxtool.web.task_worker import (
    ensure_worker_threads_started,
    mark_memory_task_processing,
    process_next_queued_task,
    run_task_process_entry,
    run_task_in_subprocess,
    run_task_with_execution_boundary,
    start_worker_threads,
    wait_for_next_task,
)


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


def test_ensure_worker_threads_started_only_starts_once() -> None:
    worker_threads: list[str] = []
    workers_lock = threading.RLock()
    worker_state = {"started": False}
    start_calls: list[tuple[int, object]] = []

    def _worker_target() -> None:
        """无参数无返回值的 fake worker 入口，用于断言启动函数收到的目标函数。"""

    worker_target = _worker_target

    def _start_threads(max_workers: int, target):
        """接收 worker 数量和目标函数，返回模拟线程列表并记录启动调用。"""
        start_calls.append((max_workers, target))
        return ["thread-1", "thread-2"]

    first = ensure_worker_threads_started(
        worker_threads,
        workers_lock,
        worker_state,
        max_workers=2,
        worker_target=worker_target,
        start_threads=_start_threads,
    )
    second = ensure_worker_threads_started(
        worker_threads,
        workers_lock,
        worker_state,
        max_workers=2,
        worker_target=worker_target,
        start_threads=_start_threads,
    )

    assert first is True
    assert second is False
    assert worker_threads == ["thread-1", "thread-2"]
    assert worker_state == {"started": True}
    assert start_calls == [(2, worker_target)]


def test_wait_for_next_task_pops_oldest_payload() -> None:
    task_queue = OrderedDict(
        [
            ("task-1", ("input-1.docx", "one.docx", "ip1", "ua1", None, None)),
            ("task-2", ("input-2.docx", "two.docx", "ip2", "ua2", {"mode": "smart"}, {})),
        ]
    )
    condition = threading.Condition()

    task_id, payload = wait_for_next_task(task_queue, condition)

    assert task_id == "task-1"
    assert payload == ("input-1.docx", "one.docx", "ip1", "ua1", None, None)
    assert list(task_queue) == ["task-2"]


def test_mark_memory_task_processing_updates_queue_fields() -> None:
    tasks = {"task-1": {"status": "queued", "queue_position": 3, "keep": "value"}}
    lock = threading.RLock()

    updated = mark_memory_task_processing("task-1", tasks, lock, started_at=123.5)

    assert updated == {
        "status": "processing",
        "started_at": 123.5,
        "queue_ahead": 0,
        "queue_position": 0,
        "keep": "value",
    }
    assert tasks["task-1"] == updated


def test_process_next_queued_task_marks_and_processes_one_task() -> None:
    task_queue = OrderedDict(
        [("task-1", ("input.docx", "upload.docx", "127.0.0.1", "pytest", {"mode": "smart"}, {"owner": "u"}))]
    )
    condition = threading.Condition()
    tasks = {"task-1": {"status": "queued"}}
    tasks_lock = threading.RLock()
    marked: list[str] = []
    processed: list[tuple] = []

    def _mark_task_processing(task_id: str) -> None:
        """接收任务 ID，记录数据库处理中状态回调已被调用。"""
        marked.append(task_id)

    def _process_task(task_id, input_path, orig_name, ip, ua, format_config, request_meta):
        """接收任务参数，记录 worker 已把 payload 原样交给处理函数。"""
        processed.append((task_id, input_path, orig_name, ip, ua, format_config, request_meta))

    handled = process_next_queued_task(
        task_queue,
        condition,
        tasks,
        tasks_lock,
        mark_task_processing=_mark_task_processing,
        process_task=_process_task,
        now=lambda: 456.0,
    )

    assert handled == "task-1"
    assert marked == ["task-1"]
    assert processed == [
        ("task-1", "input.docx", "upload.docx", "127.0.0.1", "pytest", {"mode": "smart"}, {"owner": "u"})
    ]
    assert tasks["task-1"]["status"] == "processing"
    assert tasks["task-1"]["started_at"] == 456.0
    assert not task_queue


def test_run_task_in_subprocess_returns_child_result() -> None:
    ctx = _FakeProcessContext(queue_value={"status": "done", "output_path": "out.docx"})
    cleaned: list[str] = []

    result = run_task_in_subprocess(
        "task-1",
        "input.docx",
        "upload.docx",
        "127.0.0.1",
        "pytest",
        {"mode": "smart"},
        {},
        process_timeout=60,
        context_factory=lambda method: ctx.with_method(method),
        process_target=lambda *_args: None,
        cleanup_output_path=cleaned.append,
        task_output_dir=lambda task_id: f"out/{task_id}",
    )

    assert result == {"status": "done", "output_path": "out.docx"}
    assert ctx.method == "spawn"
    assert ctx.process.started is True
    assert ctx.process.joins == [60]
    assert cleaned == []


def test_run_task_in_subprocess_times_out_and_cleans_output() -> None:
    ctx = _FakeProcessContext(queue_value=None, alive_sequence=[True, True, False], exitcode=None)
    cleaned: list[str] = []

    result = run_task_in_subprocess(
        "task-2",
        "input.docx",
        "upload.docx",
        "127.0.0.1",
        "pytest",
        None,
        None,
        process_timeout=7,
        context_factory=lambda method: ctx.with_method(method),
        process_target=lambda *_args: None,
        cleanup_output_path=cleaned.append,
        task_output_dir=lambda task_id: f"out/{task_id}",
    )

    assert result["status"] == "timeout"
    assert result["error_code"] == "TASK_TIMEOUT"
    assert result["duration_s"] == 7
    assert ctx.process.terminated is True
    assert ctx.process.killed is True
    assert cleaned == ["out/task-2"]


def test_run_task_in_subprocess_reports_missing_child_result() -> None:
    ctx = _FakeProcessContext(queue_exception=Empty, exitcode=9)
    cleaned: list[str] = []

    result = run_task_in_subprocess(
        "task-3",
        "input.docx",
        "upload.docx",
        "127.0.0.1",
        "pytest",
        None,
        None,
        process_timeout=60,
        context_factory=lambda method: ctx.with_method(method),
        process_target=lambda *_args: None,
        cleanup_output_path=cleaned.append,
        task_output_dir=lambda task_id: f"out/{task_id}",
    )

    assert result["status"] == "error"
    assert result["error_code"] == "TASK_PROCESSING_ERROR"
    assert result["error_message"] == "子进程未返回结果，退出码=9"
    assert cleaned == ["out/task-3"]


def test_run_task_process_entry_writes_success_result() -> None:
    queue = _FakePutQueue()

    def _process_body(task_id, input_path, orig_name, ip, ua, format_config, request_meta):
        """接收完整任务参数，返回模拟 DOCX 处理成功结果。"""
        assert (task_id, input_path, orig_name, ip, ua) == (
            "task-1",
            "input.docx",
            "upload.docx",
            "127.0.0.1",
            "pytest",
        )
        assert format_config == {"mode": "smart"}
        assert request_meta == {"owner": "u"}
        return {"status": "done", "output_path": "out.docx"}

    result = run_task_process_entry(
        queue,
        "task-1",
        "input.docx",
        "upload.docx",
        "127.0.0.1",
        "pytest",
        {"mode": "smart"},
        {"owner": "u"},
        process_task_body=_process_body,
        sanitize_error=str,
    )

    assert result == {"status": "done", "output_path": "out.docx"}
    assert queue.items == [result]


def test_run_task_process_entry_returns_sanitized_error_on_exception() -> None:
    queue = _FakePutQueue()

    def _process_body(*_args):
        """模拟 DOCX 处理函数抛出异常。"""
        raise RuntimeError("secret path C:/private/file.docx")

    result = run_task_process_entry(
        queue,
        "task-2",
        "input.docx",
        "upload.docx",
        "127.0.0.1",
        "pytest",
        None,
        None,
        process_task_body=_process_body,
        sanitize_error=lambda value: "sanitized",
    )

    assert result["status"] == "error"
    assert result["error_code"] == "TASK_PROCESSING_ERROR"
    assert result["error_message"] == "sanitized"
    assert result["recognition_summary"] == {}
    assert queue.items == [result]


def test_run_task_process_entry_ignores_queue_put_failure() -> None:
    queue = _FakePutQueue(raise_on_put=True)

    result = run_task_process_entry(
        queue,
        "task-3",
        "input.docx",
        "upload.docx",
        "127.0.0.1",
        "pytest",
        None,
        None,
        process_task_body=lambda *_args: {"status": "done"},
        sanitize_error=str,
    )

    assert result == {"status": "done"}
    assert queue.items == []


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


class _FakeProcessContext:
    """模拟 multiprocessing context，记录 spawn 方法、队列和进程构造参数。"""

    def __init__(
        self,
        *,
        queue_value=None,
        queue_exception=None,
        alive_sequence: list[bool] | None = None,
        exitcode: int | None = 0,
    ) -> None:
        self.method = ""
        self.queue = _FakeResultQueue(value=queue_value, exception=queue_exception)
        self.process = _FakeProcess(alive_sequence=alive_sequence or [False], exitcode=exitcode)

    def with_method(self, method: str):
        """接收启动方法名称，保存后返回自身作为 fake context。"""
        self.method = method
        return self

    def Queue(self):
        """返回 fake 结果队列，模拟子进程向父进程传回结果。"""
        return self.queue

    def Process(self, *, target, args, daemon):
        """接收进程构造参数，返回可观察生命周期调用的 fake process。"""
        self.process.target = target
        self.process.args = args
        self.process.daemon = daemon
        return self.process


class _FakeResultQueue:
    """模拟 multiprocessing Queue，只实现本测试需要的 get 行为。"""

    def __init__(self, *, value=None, exception=None) -> None:
        self.value = value
        self.exception = exception
        self.timeouts: list[int] = []

    def get(self, timeout: int):
        """接收超时时间，返回预置值或抛出预置异常。"""
        self.timeouts.append(timeout)
        if self.exception is not None:
            raise self.exception()
        return self.value


class _FakeProcess:
    """模拟子进程生命周期，记录 start/join/terminate/kill 调用。"""

    def __init__(self, *, alive_sequence: list[bool], exitcode: int | None) -> None:
        self.alive_sequence = list(alive_sequence)
        self.exitcode = exitcode
        self.started = False
        self.terminated = False
        self.killed = False
        self.joins: list[int] = []
        self.target = None
        self.args = ()
        self.daemon = False

    def start(self) -> None:
        """标记子进程已启动。"""
        self.started = True

    def join(self, timeout: int) -> None:
        """记录父进程等待子进程的超时时间。"""
        self.joins.append(timeout)

    def is_alive(self) -> bool:
        """按预置序列返回存活状态，用于模拟超时和终止过程。"""
        if self.alive_sequence:
            return self.alive_sequence.pop(0)
        return False

    def terminate(self) -> None:
        """标记 terminate 已调用。"""
        self.terminated = True

    def kill(self) -> None:
        """标记 kill 已调用。"""
        self.killed = True


class _FakePutQueue:
    """模拟子进程结果队列，记录 put 数据或按需抛出写入异常。"""

    def __init__(self, *, raise_on_put: bool = False) -> None:
        self.raise_on_put = raise_on_put
        self.items: list[dict] = []

    def put(self, value: dict) -> None:
        """接收结果字典，记录写入值；配置为失败时抛出异常。"""
        if self.raise_on_put:
            raise RuntimeError("queue closed")
        self.items.append(value)
