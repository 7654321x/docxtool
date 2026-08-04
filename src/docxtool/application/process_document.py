"""上传 DOCX 任务的应用层处理编排。

本模块连接 Web 任务和文档处理主链路，但不实现具体识别规则、规范化规则或渲染规则。
调用方通过依赖注入传入 Importer、Renderer、完整性校验和 Web 脱敏/路径辅助，方便保持
旧入口兼容并单独测试任务结果形状。
"""

from __future__ import annotations

import os
import inspect
import time
from typing import Any, Callable, Mapping, Sequence


def _call_exporter_compat(
    exporter: Callable[..., Any],
    positional_args: Sequence[Any],
    full_kwargs: Mapping[str, Any],
) -> Any:
    """Call one exporter once after adapting only inspectable legacy kwargs."""
    try:
        signature = inspect.signature(exporter)
    except (TypeError, ValueError):
        return exporter(*positional_args, **dict(full_kwargs))

    parameters = signature.parameters
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        kwargs = dict(full_kwargs)
    else:
        kwargs = {
            name: value
            for name, value in full_kwargs.items()
            if name in parameters
            and parameters[name].kind
            in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
        }
    signature.bind(*positional_args, **kwargs)
    return exporter(*positional_args, **kwargs)


def _count_heading_paragraphs(doc_data) -> int:
    """传入文档数据对象，返回 type_id 以 heading 开头的段落数量。"""
    return sum(1 for pd in doc_data.paragraphs if pd.type_id.startswith("heading"))


def _count_body_paragraphs(doc_data) -> int:
    """传入文档数据对象，返回最终类型为 body 的段落数量。"""
    return sum(1 for pd in doc_data.paragraphs if pd.type_id == "body")


def _task_error_result(
    *,
    log_filename: str,
    log_path: str,
    duration_s: float,
    error_message: str,
) -> dict:
    """传入日志信息、耗时和脱敏错误，返回 Web 任务失败结果字典。"""
    return {
        "status": "error",
        "log_filename": log_filename,
        "log_path": log_path,
        "output_dir": "",
        "output_filename": "",
        "output_path": "",
        "duration_s": duration_s,
        "duration_ms": 0,
        "doc_mode": "",
        "paragraphs": 0,
        "headings": 0,
        "body": 0,
        "error": "",
        "error_code": "TASK_PROCESSING_ERROR",
        "error_message": error_message,
        "recognition_summary": {},
    }


def process_uploaded_docx_task(
    task_id: str,
    input_path: str,
    orig_name: str,
    ip: str,
    ua: str,
    format_config: dict | None,
    request_meta: dict | None,
    *,
    log_dir: str,
    output_root_dir: str,
    importer_factory: Callable[[], object],
    export_doc_func: Callable[..., dict | None],
    load_rules_and_settings: Callable[[dict | None], tuple],
    style_rule_cls,
    page_settings_cls,
    core_feature_defaults: Callable[[], dict],
    make_document_log_path: Callable[..., str],
    set_context_log_path: Callable[[str], object],
    reset_context_log_path: Callable[[object], None],
    task_output_dir: Callable[[str], str],
    task_output_path: Callable[[str], str],
    ensure_path_within: Callable[[str, str], str],
    safe_file_identifier: Callable[[str], str],
    safe_download_filename: Callable[[str], str],
    sanitize_error: Callable[[object], str],
    public_recognition_summary: Callable[[object], dict],
    validate_docx_integrity: Callable[[str], None],
    integrity_error_cls: type[Exception],
    logger,
    now: Callable[[], float] = time.time,
    localtime: Callable[..., object] = time.strftime,
) -> dict:
    """传入上传任务、路径和文档处理依赖，执行导入/识别/导出并返回可序列化任务结果。"""
    t0 = now()
    request_meta = request_meta or {}
    file_id = safe_file_identifier(orig_name)
    log_path = make_document_log_path("document", log_dir=log_dir, suffix=task_id[:8])
    log_filename = os.path.basename(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{localtime('%Y-%m-%d %H:%M:%S')} [INFO ] docx_tool | [Task] {task_id[:8]} log created file_id={file_id}\n")
    token = set_context_log_path(log_path)
    try:
        rules, settings, features = load_rules_and_settings(format_config)
        rules = rules or [style_rule_cls.default_for_row(i) for i in range(10)]
        settings = settings or page_settings_cls()
        features = features or {}
        features.setdefault("numbered_bold_enabled", True)
        features.setdefault("punctuation_enabled", True)
        features.setdefault("page_number_enabled", True)
        processing_options = features.setdefault("processing", {})
        if not isinstance(processing_options, dict):
            processing_options = {}
            features["processing"] = processing_options
        processing_options.setdefault(
            "strategy",
            str(request_meta.get("processing_strategy", "") or "structural"),
        )
        recognition_options = features.setdefault("recognition", {})
        if not isinstance(recognition_options, dict):
            recognition_options = {}
            features["recognition"] = recognition_options
        recognition_options.setdefault("mode", "authoritative")
        for key, value in core_feature_defaults().items():
            features.setdefault(key, value)
        body_rule = rules[5] if len(rules) > 5 else style_rule_cls.default_for_row(5)
        letterhead_summary = features.get("letterhead", {})
        letterhead_agencies = letterhead_summary.get("agencies", [])
        logger.info(
            f"[Task] {task_id[:8]} start file_id={file_id} log={log_filename} "
            f"preset={request_meta.get('preset_name','')} mode={processing_options.get('strategy', 'structural')} "
            f"frontend_config={bool(format_config)} body={body_rule.font}/{body_rule.font_size_label} "
            f"margins=top{settings.margin_top_cm} bottom{settings.margin_bottom_cm} "
            f"left{settings.margin_left_cm} right{settings.margin_right_cm} "
            f"line_spacing={settings.line_spacing_value} numbered_bold_enabled={features['numbered_bold_enabled']} "
            f"letterhead_enabled={bool(letterhead_summary.get('enabled', False))} "
            f"letterhead_mode={letterhead_summary.get('issuance_mode', 'single')} "
            f"letterhead_agencies={len(letterhead_agencies) if isinstance(letterhead_agencies, list) else 0} "
            f"letterhead_scope={letterhead_summary.get('joint_mark_scope', 'all_agencies')}"
        )
        importer = importer_factory()
        doc_data = importer.load(
            input_path,
            rules,
            features=features,
            recognition_mode=str(recognition_options.get("mode", "authoritative")),
        )
        output_dir = ensure_path_within(output_root_dir, task_output_dir(task_id))
        os.makedirs(output_dir, exist_ok=True)
        output_path = ensure_path_within(output_dir, task_output_path(task_id))
        download_name = safe_download_filename(orig_name)
        export_stats = _call_exporter_compat(
            export_doc_func,
            (doc_data, rules, settings, output_path),
            {
                "numbered_bold_enabled": features["numbered_bold_enabled"],
                "page_number_enabled": features["page_number_enabled"],
                "numbering_options": features.get("numbering"),
                "page_number_options": features.get("page_number"),
                "signature_block_options": features.get("signature_block"),
                "table_format_options": features.get("table_format"),
                "cleanup_options": features.get("cleanup"),
                "letterhead_options": features.get("letterhead"),
            },
        )
        export_stats = export_stats or {}
        try:
            validate_docx_integrity(output_path)
        except integrity_error_cls as exc:
            logger.error(
                f"[Task] {task_id[:8]} generated DOCX integrity check failed "
                f"code={exc.code} detail={exc.message}"
            )
            duration = round(now() - t0, 2)
            return {
                "status": "error",
                "log_filename": log_filename,
                "log_path": log_path,
                "output_dir": output_dir,
                "output_filename": "",
                "output_path": "",
                "duration_s": duration,
                "duration_ms": int(duration * 1000),
                "doc_mode": doc_data.doc_mode or "UNKNOWN",
                "paragraphs": len(doc_data.paragraphs),
                "headings": _count_heading_paragraphs(doc_data),
                "body": _count_body_paragraphs(doc_data),
                "error": "",
                "error_code": "OUTPUT_DOCX_INVALID",
                "error_message": sanitize_error(f"{exc.code}: {exc.message}"),
                "recognition_summary": public_recognition_summary(doc_data),
            }
        duration = round(now() - t0, 2)
        return {
            "status": "done",
            "log_filename": log_filename,
            "log_path": log_path,
            "output_dir": output_dir,
            "output_filename": download_name,
            "output_path": output_path,
            "duration_s": duration,
            "duration_ms": int(duration * 1000),
            "doc_mode": doc_data.doc_mode or "UNKNOWN",
            "paragraphs": len(doc_data.paragraphs),
            "headings": _count_heading_paragraphs(doc_data),
            "body": _count_body_paragraphs(doc_data),
            "error": "",
            "error_code": "",
            "error_message": "",
            "recognition_summary": public_recognition_summary(doc_data),
            "compatibility_warnings": list(export_stats.get("compatibility_warnings", []) or []),
        }
    except Exception as exc:
        logger.error("[Task] %s internal failure type=%s", task_id[:8], type(exc).__name__)
        return _task_error_result(
            log_filename=log_filename,
            log_path=log_path,
            duration_s=round(now() - t0, 2),
            error_message=sanitize_error(exc),
        )
    finally:
        reset_context_log_path(token)
