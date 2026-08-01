from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path

from docxtool.web.task_result import record_task_result


class FakeLogger:
    """测试 logger：记录 info/warning/exception 调用，便于断言。"""

    def __init__(self) -> None:
        """无需传入数据，初始化空日志列表。"""
        self.info_calls = []
        self.warning_calls = []
        self.exception_calls = []

    def info(self, *args) -> None:
        """传入日志参数，记录 info 调用并返回 None。"""
        self.info_calls.append(args)

    def warning(self, *args) -> None:
        """传入日志参数，记录 warning 调用并返回 None。"""
        self.warning_calls.append(args)

    def exception(self, *args) -> None:
        """传入日志参数，记录 exception 调用并返回 None。"""
        self.exception_calls.append(args)


def _base_dependencies(tasks: OrderedDict):
    """传入内存任务映射，返回 record_task_result 测试依赖字典。"""
    calls = {"log": [], "cleanup": [], "prune": 0}
    logger = FakeLogger()

    def log_task_result(*args, **kwargs) -> None:
        """传入统计参数，记录一次 SQL 写入调用。"""
        calls["log"].append((args, kwargs))

    def cleanup_output_path(path: str) -> None:
        """传入输出目录路径，记录一次失败清理调用。"""
        calls["cleanup"].append(path)

    def task_output_dir(task_id: str) -> str:
        """传入任务 ID，返回测试输出目录。"""
        return f"outputs/{task_id}"

    def prune_task_cache() -> None:
        """无需传入数据，记录一次缓存裁剪调用。"""
        calls["prune"] += 1

    return {
        "tasks": tasks,
        "tasks_lock": threading.Lock(),
        "log_task_result": log_task_result,
        "cleanup_output_path": cleanup_output_path,
        "task_output_dir": task_output_dir,
        "prune_task_cache": prune_task_cache,
        "safe_file_identifier": lambda value: f"id:{value}",
        "logger": logger,
        "process_timeout": 60,
        "_calls": calls,
        "_logger": logger,
    }


def test_record_task_result_updates_done_task_and_statistics(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    input_path.write_bytes(b"12345")
    tasks = OrderedDict(
        {
            "task-a": {
                "status": "processing",
                "processing_options": "{}",
                "preset_id": "preset-a",
                "compatibility_warnings": ["old"],
            }
        }
    )
    deps = _base_dependencies(tasks)

    record_task_result(
        "task-a",
        str(input_path),
        "input.docx",
        "203.0.113.7",
        "ua",
        {
            "status": "done",
            "duration_ms": 2500,
            "duration_s": 2.5,
            "doc_mode": "NORMAL",
            "paragraphs": 8,
            "headings": 2,
            "body": 6,
            "log_filename": "task.log",
            "log_path": "logs/task.log",
            "output_dir": "outputs/task-a",
            "output_filename": "input_out.docx",
            "output_path": "outputs/task-a/input_out.docx",
            "compatibility_warnings": ["old", "new"],
            "recognition_summary": {"review": 0},
        },
        **{key: value for key, value in deps.items() if not key.startswith("_")},
    )

    task = tasks["task-a"]
    args, kwargs = deps["_calls"]["log"][0]
    assert args[:11] == (
        "task-a",
        "203.0.113.7",
        "ua",
        "input.docx",
        5,
        "NORMAL",
        8,
        2,
        6,
        2500,
        "done",
    )
    assert kwargs["processing_options"] == "{}"
    assert kwargs["preset_id"] == "preset-a"
    assert deps["_calls"]["cleanup"] == []
    assert deps["_calls"]["prune"] == 1
    assert task["status"] == "done"
    assert task["output"] == "outputs/task-a/input_out.docx"
    assert task["compatibility_warnings"] == ["old", "new"]
    assert task["error"] == ""
    assert deps["_logger"].info_calls


def test_record_task_result_cleans_output_and_records_error_for_failed_task(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    input_path.write_bytes(b"abc")
    tasks = OrderedDict({"task-b": {"status": "processing"}})
    deps = _base_dependencies(tasks)

    record_task_result(
        "task-b",
        str(input_path),
        "broken.docx",
        "203.0.113.8",
        "ua",
        {
            "status": "error",
            "duration_ms": 100,
            "error": "failed",
            "error_code": "TASK_FAILED",
            "error_message": "failed",
        },
        **{key: value for key, value in deps.items() if not key.startswith("_")},
    )

    task = tasks["task-b"]
    args, kwargs = deps["_calls"]["log"][0]
    assert args[10] == "error"
    assert kwargs["error_code"] == "TASK_FAILED"
    assert deps["_calls"]["cleanup"] == ["outputs/task-b"]
    assert task["status"] == "error"
    assert task["error_code"] == "TASK_FAILED"
    assert task["output_path"] == ""
    assert deps["_logger"].warning_calls


def test_record_task_result_keeps_memory_update_when_statistics_raise(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    input_path.write_bytes(b"abc")
    tasks = OrderedDict({"task-c": {"status": "processing"}})
    deps = _base_dependencies(tasks)

    def failing_log_task_result(*_args, **_kwargs) -> None:
        """传入统计参数，模拟数据库写入失败。"""
        raise RuntimeError("db down")

    deps["log_task_result"] = failing_log_task_result

    record_task_result(
        "task-c",
        str(input_path),
        "input.docx",
        "203.0.113.9",
        "ua",
        {"status": "done", "duration_ms": 100, "output_path": "out.docx"},
        **{key: value for key, value in deps.items() if not key.startswith("_")},
    )

    assert tasks["task-c"]["status"] == "done"
    assert tasks["task-c"]["output"] == "out.docx"
    assert deps["_logger"].exception_calls
