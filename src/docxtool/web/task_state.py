"""Task state helpers for the compatible web entrypoint."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Callable, Mapping, MutableMapping


SENSITIVE_PUBLIC_TASK_KEYS = (
    "output",
    "output_path",
    "output_dir",
    "download_name",
    "error",
    "error_message",
    "internal_error_detail",
    "log_path",
    "client_ip",
    "ip",
    "ua",
)


def active_count(tasks: Mapping[str, Mapping[str, Any]], tasks_lock) -> int:
    """传入任务映射和任务锁，返回当前处于 processing 状态的任务数量。"""
    with tasks_lock:
        return sum(1 for task in tasks.values() if task.get("status") == "processing")


def queued_count(task_queue: Mapping[str, Any], queue_cond) -> int:
    """传入队列映射和队列条件锁，返回等待中的任务数量。"""
    with queue_cond:
        return len(task_queue)


def task_load(tasks: Mapping[str, Mapping[str, Any]], tasks_lock, task_queue: Mapping[str, Any], queue_cond) -> int:
    """传入任务和队列容器，返回 processing 与 queued 的合计负载。"""
    return active_count(tasks, tasks_lock) + queued_count(task_queue, queue_cond)


def task_queue_info(task_id: str, task_queue: Mapping[str, Any], queue_cond) -> dict:
    """传入任务 ID 和队列容器，返回该任务的队列位置、前方数量和提示语。"""
    with queue_cond:
        ids = list(task_queue.keys())
    if task_id not in ids:
        return {"queue_position": 0, "queue_ahead": 0, "message": ""}
    idx = ids.index(task_id)
    return {
        "queue_position": idx + 1,
        "queue_ahead": idx,
        "message": f"排队中，前方还有 {idx} 个任务",
    }


def public_task_state(
    task_id: str,
    owner_id: str = "",
    *,
    tasks: Mapping[str, Mapping[str, Any]],
    tasks_lock,
    task_queue: Mapping[str, Any],
    queue_cond,
    load_task: Callable[[str, str], Mapping[str, Any] | None],
) -> dict:
    """传入任务 ID、所有者、内存任务和数据库加载器，返回脱敏后的公开任务状态。"""
    with tasks_lock:
        task = dict(tasks.get(task_id, {}))
    if task and owner_id and task.get("owner_id", "") != owner_id:
        task = {}
    if not task:
        loaded = load_task(task_id, owner_id)
        if not loaded:
            return {}
        task = dict(loaded)
    for key in SENSITIVE_PUBLIC_TASK_KEYS:
        task.pop(key, None)
    status = task.get("status", "")
    if status == "queued":
        task.update(task_queue_info(task_id, task_queue, queue_cond))
    elif status == "processing":
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "正在排版"})
    elif status == "done":
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "排版完成"})
    elif status in ("error", "timeout", "failed"):
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "排版失败"})
    elif status == "interrupted":
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "任务已中断"})
    elif status == "expired":
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "任务已过期"})
    return task


def public_recognition_summary(doc_data: Any) -> dict:
    """传入含 recognition_diagnostics 的文档对象，返回不含正文的识别审核摘要。"""
    diagnostics = getattr(doc_data, "recognition_diagnostics", {}) or {}
    paragraphs = [item for item in diagnostics.get("paragraphs", []) if isinstance(item, dict)]
    type_counts = Counter(str(item.get("final_type", "") or "unknown") for item in paragraphs)
    level_counts = Counter(str(item.get("review_level", "confirmed") or "confirmed") for item in paragraphs)
    review_items = []
    for item in paragraphs:
        review_level = str(item.get("review_level", "review" if item.get("needs_review") else "confirmed"))
        if review_level not in {"review", "critical_review"}:
            continue
        review_items.append({
            "paragraph_index": int(item.get("paragraph_index", -1)),
            "legacy_type": str(item.get("legacy_type", "")),
            "recognized_type": str(item.get("recognized_type", "")),
            "final_type": str(item.get("final_type", "")),
            "confidence": float(item.get("review_confidence", item.get("recognition_confidence", 0.0)) or 0.0),
            "review_level": review_level,
            "candidate_margin": item.get("candidate_margin"),
            "reason_codes": [str(value) for value in item.get("review_reasons", [])],
            "evidence_summary": [str(value) for value in item.get("evidence_summary", [])],
        })
    context = diagnostics.get("document_context", {})
    if not isinstance(context, dict):
        context = {}
    public_context = {
        "front_matter_count": len(context.get("front_matter_positions", []) or []),
        "body_start": context.get("body_start"),
        "body_start_reason": str(context.get("body_start_reason", "") or ""),
        "heading_families": [
            {
                "level": int(item.get("level", 0) or 0),
                "count": int(item.get("count", 0) or 0),
                "supported_count": int(item.get("supported_count", 0) or 0),
            }
            for item in context.get("heading_families", [])
            if isinstance(item, dict)
        ],
    }
    return {
        "recognition_mode": str(diagnostics.get("recognition_mode", "authoritative")),
        "result_applied": bool(diagnostics.get("result_applied", True)),
        "paragraph_count": len(paragraphs),
        "needs_review_count": len(review_items),
        "critical_review_count": level_counts.get("critical_review", 0),
        "review_count": level_counts.get("review", 0),
        "confirmed_count": level_counts.get("confirmed", 0),
        "info_count": level_counts.get("info", 0),
        "type_counts": dict(sorted(type_counts.items())),
        "review_items": review_items,
        "document_context": public_context,
    }


def task_processing_options(format_config: Mapping[str, Any] | None = None, request_meta: Mapping[str, Any] | None = None) -> str:
    """传入格式配置和请求元数据，返回可写入任务表的紧凑 JSON 处理选项。"""
    payload: MutableMapping[str, Any] = {
        "request_meta": dict(request_meta or {}),
        "features": {},
    }
    if isinstance(format_config, Mapping):
        payload["features"] = {
            "format_config_present": True,
            "style_count": len(format_config.get("styles", []) or []),
        }
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return ""
