from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path

import pytest

from docxtool.web.task_queue import enqueue_task, input_file_size


def test_input_file_size_returns_zero_for_missing_file(tmp_path: Path) -> None:
    """文件大小辅助应在路径不存在时返回 0。"""
    assert input_file_size(str(tmp_path / "missing.docx")) == 0


def test_enqueue_task_persists_record_then_memory_queue(tmp_path: Path) -> None:
    """任务入队辅助应先写 queued 记录，再写内存队列和任务缓存。"""
    input_path = tmp_path / "upload.docx"
    input_path.write_bytes(b"1234")
    task_queue: OrderedDict[str, tuple] = OrderedDict()
    queue_cond = threading.Condition()
    tasks: OrderedDict[str, dict] = OrderedDict()
    tasks_lock = threading.Lock()
    calls: list[tuple[str, object]] = []

    def record_task_queued(task_id: str, _ip: str, _ua: str, _name: str, file_size: int, **kwargs) -> None:
        """传入 queued 任务字段，记录调用顺序并返回 None。"""
        calls.append(("record", (task_id, file_size, kwargs["preset_id"], kwargs["owner_id"])))

    def task_queue_info(task_id: str) -> dict:
        """传入任务 ID，记录队列已经可见并返回队列位置。"""
        calls.append(("queue_visible", list(task_queue.keys())))
        return {"queue_position": 1, "task_id": task_id}

    info = enqueue_task(
        "task-1",
        str(input_path),
        "upload.docx",
        "127.0.0.1",
        "ua",
        format_config={"styles": [1]},
        request_meta={"preset_id": "p1", "preset_name": "默认", "processing_mode": "smart"},
        compatibility_warnings=[{"code": "compat"}],
        owner_id="owner-1",
        task_queue=task_queue,
        queue_cond=queue_cond,
        tasks=tasks,
        tasks_lock=tasks_lock,
        max_queue=2,
        active_count=lambda: 0,
        record_task_queued=record_task_queued,
        task_queue_info=task_queue_info,
        task_processing_options=lambda _config, meta: f"mode={meta['processing_mode']}",
        prune_task_cache=lambda: calls.append(("prune", "")),
        now_func=lambda: 123.0,
    )

    assert info == {"queue_position": 1, "task_id": "task-1"}
    assert calls == [
        ("record", ("task-1", 4, "p1", "owner-1")),
        ("queue_visible", ["task-1"]),
        ("prune", ""),
    ]
    assert task_queue["task-1"] == (
        str(input_path),
        "upload.docx",
        "127.0.0.1",
        "ua",
        {"styles": [1]},
        {"preset_id": "p1", "preset_name": "默认", "processing_mode": "smart"},
    )
    assert tasks["task-1"]["status"] == "queued"
    assert tasks["task-1"]["queued_at"] == 123.0
    assert tasks["task-1"]["compatibility_warnings"] == [{"code": "compat"}]


def test_enqueue_task_full_does_not_persist_record() -> None:
    """队列容量已满时，入队辅助应抛出 OverflowError 且不写 queued 记录。"""
    task_queue: OrderedDict[str, tuple] = OrderedDict([("existing", ("a",))])
    queue_cond = threading.Condition()
    tasks: OrderedDict[str, dict] = OrderedDict()
    calls: list[str] = []

    with pytest.raises(OverflowError):
        enqueue_task(
            "task-2",
            "",
            "upload.docx",
            "127.0.0.1",
            "ua",
            task_queue=task_queue,
            queue_cond=queue_cond,
            tasks=tasks,
            tasks_lock=threading.Lock(),
            max_queue=1,
            active_count=lambda: 0,
            record_task_queued=lambda *_args, **_kwargs: calls.append("record"),
            task_queue_info=lambda _task_id: {},
            task_processing_options=lambda _config, _meta: "{}",
            prune_task_cache=lambda: calls.append("prune"),
        )

    assert calls == []
    assert list(task_queue.keys()) == ["existing"]
    assert tasks == {}
