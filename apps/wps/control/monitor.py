"""Single-thread command monitor for WPS business requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from queue import Queue
import threading
import time
from typing import Any, Callable, Dict, Optional

from .logging_adapter import log_event


class CommandMonitorError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class _CommandTask:
    path: str
    body: Dict[str, Any]
    request_id: str
    completed: threading.Event = field(default_factory=threading.Event)
    result: Optional[Dict[str, Any]] = None
    error: Optional[Exception] = None


_STOP = object()


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", "")
    if isinstance(code, str) and code:
        return code
    text = str(error).strip()
    if text and text.upper() == text and len(text) <= 100:
        return text
    return "WPS_MONITOR_UNEXPECTED_ERROR"


class CommandMonitor:
    """Execute WPS business requests sequentially on one dedicated thread."""

    def __init__(
        self,
        dispatch: Callable[[str, Dict[str, Any], str], Dict[str, Any]],
    ) -> None:
        self._dispatch = dispatch
        self._queue: "Queue[object]" = Queue(maxsize=1)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._occupied = False
        self._fatal_error: Optional[BaseException] = None

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(
                self._running
                and self._thread is not None
                and self._thread.is_alive()
                and self._fatal_error is None
            )

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._occupied

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._fatal_error = None
            self._thread = threading.Thread(
                target=self._run,
                name="docxtool-wps-command-monitor",
                daemon=True,
            )
            thread = self._thread
        log_event(
            "INFO", "monitor", "monitor.thread.start", "开始启动 WPS 命令监控线程"
        )
        thread.start()

    def submit(
        self,
        path: str,
        body: Dict[str, Any],
        request_id: str = "",
    ) -> Dict[str, Any]:
        log_event(
            "INFO",
            "monitor",
            "monitor.command.received",
            "监控线程收到 WPS 业务命令",
            {"request_id": request_id, "path": path},
        )
        with self._lock:
            thread = self._thread
            if (
                not self._running
                or thread is None
                or not thread.is_alive()
                or self._fatal_error is not None
            ):
                log_event(
                    "ERROR",
                    "monitor",
                    "monitor.command.unavailable",
                    "WPS 命令监控线程未运行",
                    {
                        "request_id": request_id,
                        "path": path,
                        "error_code": "WPS_MONITOR_NOT_RUNNING",
                    },
                )
                raise CommandMonitorError("WPS_MONITOR_NOT_RUNNING")
            if self._occupied:
                log_event(
                    "WARNING",
                    "monitor",
                    "monitor.command.busy",
                    "WPS 命令监控线程正在执行其他命令",
                    {
                        "request_id": request_id,
                        "path": path,
                        "error_code": "WPS_COMMAND_BUSY",
                    },
                )
                raise CommandMonitorError("WPS_COMMAND_BUSY")
            self._occupied = True

        task = _CommandTask(path=path, body=body, request_id=request_id)
        self._queue.put(task)
        log_event(
            "INFO",
            "monitor",
            "monitor.command.queued",
            "WPS 业务命令已进入监控线程",
            {"request_id": request_id, "path": path},
        )
        task.completed.wait()
        if task.error is not None:
            raise task.error
        if task.result is None:
            raise CommandMonitorError("WPS_MONITOR_RESULT_MISSING")
        return task.result

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            thread = self._thread
        log_event(
            "INFO", "monitor", "monitor.thread.stop", "开始停止 WPS 命令监控线程"
        )
        self._queue.put(_STOP)
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                log_event(
                    "ERROR",
                    "monitor",
                    "monitor.thread.stop_timeout",
                    "WPS 命令监控线程停止超时",
                    {"error_code": "WPS_MONITOR_STOP_TIMEOUT"},
                )
                raise CommandMonitorError("WPS_MONITOR_STOP_TIMEOUT")
        log_event(
            "INFO", "monitor", "monitor.thread.stopped", "WPS 命令监控线程已停止"
        )

    def _run(self) -> None:
        log_event(
            "INFO", "monitor", "monitor.thread.started", "WPS 命令监控线程已启动"
        )
        item: object = None
        try:
            while True:
                item = self._queue.get()
                if item is _STOP:
                    return
                if not isinstance(item, _CommandTask):
                    raise AssertionError("WPS_MONITOR_QUEUE_ITEM_INVALID")
                self._execute(item)
        except BaseException as exc:
            with self._lock:
                self._fatal_error = exc
                self._running = False
                self._occupied = False
            if isinstance(item, _CommandTask) and not item.completed.is_set():
                item.error = CommandMonitorError("WPS_MONITOR_THREAD_CRASHED")
                item.completed.set()
            log_event(
                "ERROR",
                "monitor",
                "monitor.thread.crashed",
                "WPS 命令监控线程异常退出",
                {
                    "error_code": "WPS_MONITOR_THREAD_CRASHED",
                    "error_type": type(exc).__name__,
                },
            )

    def _execute(self, task: _CommandTask) -> None:
        started_at = time.monotonic()
        handled = False
        log_event(
            "INFO",
            "monitor",
            "monitor.command.started",
            "WPS 业务命令开始执行",
            {"request_id": task.request_id, "path": task.path},
        )
        try:
            task.result = self._dispatch(task.path, task.body, task.request_id)
        except Exception as exc:
            task.error = exc
            handled = True
            log_event(
                "ERROR",
                "monitor",
                "monitor.command.failed",
                "WPS 业务命令执行失败",
                {
                    "request_id": task.request_id,
                    "path": task.path,
                    "cause_event": _error_code(exc),
                    "error_code": _error_code(exc),
                    "error_type": type(exc).__name__,
                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                },
            )
        else:
            handled = True
            log_event(
                "INFO",
                "monitor",
                "monitor.command.completed",
                "WPS 业务命令执行完成",
                {
                    "request_id": task.request_id,
                    "path": task.path,
                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                },
            )
        finally:
            if handled:
                with self._lock:
                    self._occupied = False
                task.completed.set()
