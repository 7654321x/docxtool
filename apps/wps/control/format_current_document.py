"""Thin WPS adapter for the existing DocxTool document pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Dict, Optional

from docxtool.document.engine import export_doc
from docxtool.document.importer import DocxImporter
from docxtool.document.models import FormatScope
from docxtool.document.configuration.models import PageSettings
from docxtool.sdk.binding import bind_physical_paragraphs
from docxtool.document.configuration.validation import load_rules_and_settings
from docxtool.security import validate_docx_integrity

from .logging_adapter import document_log_context, log_event


WPS_STYLE_PROFILE = "wps_docxtool"


def _apply_official_page_grid(settings: PageSettings) -> tuple[int, int, bool]:
    """Apply the hidden WPS document-grid values from the package defaults.

    The WPS settings window intentionally does not expose characters-per-line
    or lines-per-page. Older local profiles can still contain stale values,
    so accepting those values would make the same official document render
    with a different grid. The default-format JSON remains the canonical
    source for the official 28-character/22-line grid.
    """
    default_settings = PageSettings.from_config()
    previous = (settings.chars_per_line, settings.lines_per_page)
    settings.chars_per_line = default_settings.chars_per_line
    settings.lines_per_page = default_settings.lines_per_page
    return previous[0], previous[1], previous != (
        settings.chars_per_line,
        settings.lines_per_page,
    )


@dataclass(frozen=True)
class FormatResult:
    output_path: Path
    log_path: Path
    document_mode: str
    paragraph_count: int
    heading_count: int
    body_count: int
    export_stats: Dict[str, Any]


def format_current_document(
    source_path: str,
    output_path: str,
    *,
    operation_id: str,
    log_dir: Path,
    format_config: Optional[dict] = None,
    request_id: str = "",
    host_snapshot: Optional[dict] = None,
    selected_host_paragraph_indexes: Optional[list[int]] = None,
) -> FormatResult:
    """Format one saved DOCX through DocxTool's authoritative production chain."""
    source = Path(source_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve()
    if source.suffix.lower() != ".docx" or not source.is_file():
        log_event(
            "ERROR", "format", "input.source.invalid", "正式排版源文件无效",
            {"request_id": request_id, "error_code": "INVALID_DOCX_INPUT"},
        )
        raise ValueError("INVALID_DOCX_INPUT")
    if target.suffix.lower() != ".docx":
        log_event(
            "ERROR", "format", "input.output.invalid", "正式排版输出文件类型无效",
            {"request_id": request_id, "error_code": "INVALID_DOCX_OUTPUT"},
        )
        raise ValueError("INVALID_DOCX_OUTPUT")
    if source == target:
        log_event(
            "ERROR", "format", "input.path_collision", "正式排版输出不能覆盖正在打开的源文件",
            {"request_id": request_id, "error_code": "WPS_FORMAT_OUTPUT_MUST_BE_TEMPORARY"},
        )
        raise ValueError("WPS_FORMAT_OUTPUT_MUST_BE_TEMPORARY")

    with document_log_context(source, log_dir, operation_id, request_id) as log_path:
        log_event(
            "INFO",
            "format",
            "pipeline.start",
            "开始调用 DocxTool 正式排版主链",
            {"operation_id_short": operation_id[:12], "request_id": request_id, "recognition_mode": "authoritative"},
        )
        local_scope = selected_host_paragraph_indexes is not None
        scope_resolver = None
        if local_scope:
            if not isinstance(host_snapshot, dict):
                raise ValueError("WPS_FORMAT_SCOPE_SNAPSHOT_REQUIRED")
            selected_host_indexes = frozenset(selected_host_paragraph_indexes)
            if not selected_host_indexes or any(
                isinstance(index, bool) or not isinstance(index, int) or index < 0
                for index in selected_host_indexes
            ):
                raise ValueError("WPS_FORMAT_SCOPE_INVALID")
            host_text = {
                int(item["host_paragraph_index"]): str(item.get("raw_text", ""))
                for item in host_snapshot.get("paragraphs", [])
                if isinstance(item, dict)
                and isinstance(item.get("host_paragraph_index"), int)
                and item.get("story_type") == "main"
                and item.get("is_in_table") is not True
            }

            def resolve_scope(source_paragraphs):
                binding = bind_physical_paragraphs(source_paragraphs, host_snapshot)
                source_indexes = {
                    item.source_physical_paragraph_index
                    for item in binding
                    if item.host_paragraph_index in selected_host_indexes
                    and item.status in {"matched_unique", "matched_review"}
                }
                mapped_host_indexes = {
                    item.host_paragraph_index
                    for item in binding
                    if item.host_paragraph_index is not None
                    and item.status in {"matched_unique", "matched_review"}
                }
                unresolved = {
                    index
                    for index in selected_host_indexes - mapped_host_indexes
                    if host_text.get(index, "").strip()
                }
                if unresolved or not source_indexes:
                    raise ValueError("WPS_FORMAT_SCOPE_BIND_FAILED")
                log_event(
                    "INFO",
                    "format",
                    "scope.bind.completed",
                    "排版前页码范围已固定为源文档段落",
                    {
                        "operation_id_short": operation_id[:12],
                        "request_id": request_id,
                        "selected_count": len(source_indexes),
                        "scope_mode": "pre_format_pages",
                    },
                )
                return FormatScope("pre_format_pages", frozenset(source_indexes))

            scope_resolver = resolve_scope

        stage_started = time.monotonic()
        log_event("INFO", "format", "config.load.start", "开始加载正式排版配置", {"operation_id_short": operation_id[:12], "request_id": request_id})
        try:
            rules, settings, features = load_rules_and_settings(format_config)
        except Exception as exc:
            log_event("ERROR", "format", "config.load.failed", "正式排版配置加载失败", {"operation_id_short": operation_id[:12], "request_id": request_id, "stage": "config_load", "error_type": type(exc).__name__, "error_code": "WPS_FORMAT_CONFIG_FAILED", "duration_ms": int((time.monotonic() - stage_started) * 1000)})
            raise RuntimeError("WPS_FORMAT_CONFIG_FAILED") from exc
        previous_chars, previous_lines, grid_changed = _apply_official_page_grid(settings)
        if grid_changed:
            log_event(
                "INFO",
                "format",
                "config.page_grid.standardized",
                "WPS 正式排版已统一使用公文文档网格",
                {
                    "operation_id_short": operation_id[:12],
                    "request_id": request_id,
                    "source_chars_per_line": previous_chars,
                    "source_lines_per_page": previous_lines,
                    "chars_per_line": settings.chars_per_line,
                    "lines_per_page": settings.lines_per_page,
                    "source": "default-format.json",
                },
            )
        # WPS one-click formatting always rebuilds recognized heading
        # numbering as editable text. This removes source automatic heading
        # numbering while leaving native body lists under Core's existing
        # preservation rule.
        features["numbering"]["enabled"] = True
        if format_config is None:
            features["punctuation"]["enabled"] = True
        processing = features.setdefault("processing", {})
        if not isinstance(processing, dict):
            log_event(
                "ERROR", "format", "config.processing.invalid", "正式排版 processing 配置无效",
                {
                    "operation_id_short": operation_id[:12],
                    "request_id": request_id,
                    "stage": "config_load",
                    "error_code": "INVALID_PROCESSING_OPTIONS",
                },
            )
            raise ValueError("INVALID_PROCESSING_OPTIONS")
        processing.setdefault("strategy", "structural")
        log_event(
            "INFO",
            "format",
            "config.load.completed",
            "正式排版配置加载完成",
            {
                "operation_id_short": operation_id[:12],
                "request_id": request_id,
                "duration_ms": int((time.monotonic() - stage_started) * 1000),
                "processing_strategy": processing["strategy"],
                "style_profile": WPS_STYLE_PROFILE,
                "numbering_enabled": bool(features["numbering"]["enabled"]),
                "punctuation_safe_enabled": bool(
                    features["punctuation"]["enabled"]
                ),
            },
        )

        stage_started = time.monotonic()
        log_event("INFO", "format", "import.start", "开始导入并识别当前 DOCX", {"operation_id_short": operation_id[:12], "request_id": request_id, "stage": "import"})
        try:
            document = DocxImporter().load(
                str(source),
                rules,
                features=features,
                strict_preservation=True,
                recognition_mode="authoritative",
                format_scope_resolver=scope_resolver,
            )
        except Exception as exc:
            if str(exc) in {
                "WPS_FORMAT_SCOPE_BIND_FAILED",
                "WPS_FORMAT_SCOPE_INVALID",
                "WPS_FORMAT_SCOPE_SNAPSHOT_REQUIRED",
            }:
                log_event(
                    "ERROR",
                    "format",
                    "scope.bind.failed",
                    "无法将指定页码绑定到源文档段落",
                    {
                        "operation_id_short": operation_id[:12],
                        "request_id": request_id,
                        "stage": "scope_bind",
                        "error_code": str(exc),
                    },
                )
                raise
            log_event("ERROR", "format", "import.failed", "DOCX 导入识别失败", {"operation_id_short": operation_id[:12], "request_id": request_id, "stage": "import", "error_type": type(exc).__name__, "error_code": "WPS_FORMAT_IMPORT_FAILED", "duration_ms": int((time.monotonic() - stage_started) * 1000)})
            raise RuntimeError("WPS_FORMAT_IMPORT_FAILED") from exc
        log_event("INFO", "format", "import.completed", "DOCX 导入识别完成", {"operation_id_short": operation_id[:12], "request_id": request_id, "stage": "import", "document_mode": document.doc_mode or "UNKNOWN", "paragraph_count": len(document.paragraphs), "duration_ms": int((time.monotonic() - stage_started) * 1000)})

        stage_started = time.monotonic()
        log_event("INFO", "format", "engine.export.start", "开始执行 DocxTool Engine 导出", {"operation_id_short": operation_id[:12], "request_id": request_id, "stage": "engine_export"})
        try:
            export_stats = export_doc(
                document,
                rules,
                settings,
                str(target),
                numbered_bold_enabled=bool(features.get("numbered_bold_enabled", True)),
                page_number_enabled=bool(features.get("page_number_enabled", True)),
                numbering_options=features.get("numbering"),
                page_number_options=features.get("page_number"),
                signature_block_options=features.get("signature_block"),
                table_format_options=features.get("table_format"),
                cleanup_options=features.get("cleanup"),
                letterhead_options=features.get("letterhead"),
                style_profile=WPS_STYLE_PROFILE,
            ) or {}
        except Exception as exc:
            log_event("ERROR", "format", "engine.export.failed", "DocxTool Engine 导出失败", {"operation_id_short": operation_id[:12], "request_id": request_id, "stage": "engine_export", "error_type": type(exc).__name__, "error_code": "WPS_FORMAT_EXPORT_FAILED", "duration_ms": int((time.monotonic() - stage_started) * 1000)})
            raise RuntimeError("WPS_FORMAT_EXPORT_FAILED") from exc
        log_event("INFO", "format", "engine.export.completed", "DocxTool Engine 导出完成", {"operation_id_short": operation_id[:12], "request_id": request_id, "stage": "engine_export", "warning_count": len(export_stats.get("compatibility_warnings", [])), "duration_ms": int((time.monotonic() - stage_started) * 1000)})

        stage_started = time.monotonic()
        log_event("INFO", "format", "integrity.validate.start", "开始验证输出 DOCX 完整性", {"operation_id_short": operation_id[:12], "request_id": request_id, "stage": "integrity_validation"})
        try:
            validate_docx_integrity(str(target))
        except Exception as exc:
            log_event("ERROR", "format", "integrity.validate.failed", "输出 DOCX 完整性验证失败", {"operation_id_short": operation_id[:12], "request_id": request_id, "stage": "integrity_validation", "error_type": type(exc).__name__, "error_code": "WPS_FORMAT_INTEGRITY_FAILED", "duration_ms": int((time.monotonic() - stage_started) * 1000)})
            raise RuntimeError("WPS_FORMAT_INTEGRITY_FAILED") from exc
        log_event("INFO", "format", "integrity.validate.completed", "输出 DOCX 完整性验证完成", {"operation_id_short": operation_id[:12], "request_id": request_id, "stage": "integrity_validation", "duration_ms": int((time.monotonic() - stage_started) * 1000)})

        headings = sum(1 for item in document.paragraphs if item.type_id.startswith("heading"))
        body = sum(1 for item in document.paragraphs if item.type_id == "body")
        log_event(
            "INFO",
            "format",
            "pipeline.completed",
            "DocxTool 正式排版主链执行完成",
            {
                "operation_id_short": operation_id[:12],
                "request_id": request_id,
                "document_mode": document.doc_mode or "UNKNOWN",
                "paragraphs": len(document.paragraphs),
                "headings": headings,
                "body_count": body,
            },
        )
        return FormatResult(
            output_path=target,
            log_path=Path(log_path),
            document_mode=document.doc_mode or "UNKNOWN",
            paragraph_count=len(document.paragraphs),
            heading_count=headings,
            body_count=body,
            export_stats=dict(export_stats),
        )
