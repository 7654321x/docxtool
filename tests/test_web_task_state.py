from __future__ import annotations

import json
import threading
from collections import OrderedDict
from types import SimpleNamespace

from docxtool.web.task_state import (
    active_count,
    public_recognition_summary,
    public_task_state,
    queued_count,
    task_load,
    task_processing_options,
    task_queue_info,
)


def test_task_counts_and_queue_info() -> None:
    lock = threading.Lock()
    queue_cond = threading.Condition()
    tasks = {
        "a": {"status": "processing"},
        "b": {"status": "queued"},
        "c": {"status": "done"},
    }
    queue = OrderedDict((task_id, {}) for task_id in ("b", "d"))

    assert active_count(tasks, lock) == 1
    assert queued_count(queue, queue_cond) == 2
    assert task_load(tasks, lock, queue, queue_cond) == 3
    assert task_queue_info("d", queue, queue_cond) == {
        "queue_position": 2,
        "queue_ahead": 1,
        "message": "排队中，前方还有 1 个任务",
    }
    assert task_queue_info("missing", queue, queue_cond)["queue_position"] == 0


def test_public_task_state_redacts_sensitive_fields_and_uses_queue_message() -> None:
    lock = threading.Lock()
    queue_cond = threading.Condition()
    tasks = {
        "task-a": {
            "id": "task-a",
            "owner_id": "owner-a",
            "status": "queued",
            "output_path": r"D:\private\out.docx",
            "error": "private text",
            "client_ip": "127.0.0.1",
        }
    }
    queue = OrderedDict([("task-a", {})])

    state = public_task_state(
        "task-a",
        "owner-a",
        tasks=tasks,
        tasks_lock=lock,
        task_queue=queue,
        queue_cond=queue_cond,
        load_task=lambda _task_id, _owner_id: {},
    )

    assert state["status"] == "queued"
    assert state["queue_position"] == 1
    assert "output_path" not in state
    assert "error" not in state
    assert "client_ip" not in state


def test_public_task_state_falls_back_to_loader_when_memory_owner_mismatch() -> None:
    lock = threading.Lock()
    queue_cond = threading.Condition()
    tasks = {"task-a": {"id": "task-a", "owner_id": "owner-a", "status": "done"}}
    queue = OrderedDict()
    calls = []

    def load_task(task_id: str, owner_id: str) -> dict:
        calls.append((task_id, owner_id))
        return {"id": task_id, "owner_id": owner_id, "status": "processing", "ua": "secret-agent"}

    state = public_task_state(
        "task-a",
        "owner-b",
        tasks=tasks,
        tasks_lock=lock,
        task_queue=queue,
        queue_cond=queue_cond,
        load_task=load_task,
    )

    assert calls == [("task-a", "owner-b")]
    assert state["owner_id"] == "owner-b"
    assert state["message"] == "正在排版"
    assert "ua" not in state


def test_public_recognition_summary_contains_review_counts_without_text() -> None:
    diagnostics = {
        "recognition_mode": "authoritative",
        "result_applied": True,
        "paragraphs": [
            {
                "paragraph_index": 1,
                "final_type": "body",
                "review_level": "confirmed",
                "recognized_text": "sensitive paragraph text",
            },
            {
                "paragraph_index": 2,
                "legacy_type": "body",
                "recognized_type": "heading1",
                "final_type": "heading1",
                "review_level": "review",
                "review_confidence": 0.61,
                "review_reasons": ["SMALL_MARGIN"],
                "evidence_summary": ["numbering"],
            },
        ],
        "document_context": {
            "front_matter_positions": [0],
            "body_start": 1,
            "body_start_reason": "numbered_heading",
            "heading_families": [{"level": 1, "count": 2, "supported_count": 2}],
        },
    }

    summary = public_recognition_summary(SimpleNamespace(recognition_diagnostics=diagnostics))
    encoded = json.dumps(summary, ensure_ascii=False)

    assert summary["paragraph_count"] == 2
    assert summary["review_count"] == 1
    assert summary["type_counts"] == {"body": 1, "heading1": 1}
    assert summary["document_context"]["front_matter_count"] == 1
    assert "sensitive paragraph text" not in encoded


def test_task_processing_options_reports_feature_shape() -> None:
    payload = task_processing_options({"styles": [{"id": "title"}, {"id": "body"}]}, {"mode": "smart"})

    assert json.loads(payload) == {
        "request_meta": {"mode": "smart"},
        "features": {"format_config_present": True, "style_count": 2},
    }
