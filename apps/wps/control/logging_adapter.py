"""WPS logging bridge that reuses DocxTool's logging contract.

WPS runtime logs and core document logs share the same timestamp/level/logger
format. This module owns only WPS-specific message shaping and never changes
DocxTool's global logging implementation.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from docxtool.document.style_config import (
    LOG_FORMAT,
    configure_logging,
    get_logger,
    make_document_log_path,
    reset_context_log_path,
    set_context_log_path,
)

LOGGER = get_logger()
WPS_LOG_MAX_BYTES = 10 * 1024 * 1024
WPS_LOG_BACKUP_COUNT = 5
_WPS_FILE_HANDLER: Optional[RotatingFileHandler] = None
SAFE_WPS_LOG_FIELDS = frozenset(
    {
        "application_available", "applied_count", "applied_total", "backup_state",
        "batch_index", "binding_status", "block_count", "block_index", "blocks",
        "body_count", "bootstrap_id", "busy", "callbacks_registered", "cause_event",
        "cleared_count", "command", "compatibility_warnings", "config_file", "config_present",
        "confirmed", "confirmed_count", "control_host", "control_port", "control_url_present",
        "current_status",
        "deleted_count", "document_id_short", "document_mode", "document_name", "document_ready_state",
        "docxtool_version", "duration_ms", "end_utf16", "error_code", "error_type",
        "event_sequence", "executable", "failed_count", "file_id", "flushed_count",
        "headings", "heading_count", "host", "host_instance_id_short", "host_paragraph_index", "host_ready",
        "host_runtime_present", "http_status", "interval_ms", "log_file", "method",
        "locator_status", "locator_verified", "operation_id_short", "pane_instance_id", "pane_instance_id_present", "paragraph_count",
        "paragraphs", "path", "pending_present", "plan_id_short", "plugin_storage_available", "processing_strategy",
        "physical_occurrence_index", "physical_paragraph_index", "physical_text_length_utf16",
        "poll_interval_ms", "port", "previous_state", "previous_status", "primary_error_code", "punctuation_safe_enabled",
        "process_count", "queued_count", "raw_length", "raw_present", "readback_present",
        "reason", "recognition_mode", "recommended_action", "request_id", "request_id_match",
        "request_key", "request_status", "response_ok", "return_code", "review", "review_count",
        "ribbon_ui_available", "segment_count", "segment_index", "skipped_count", "slot_occupied", "source_state", "stage",
        "start_utf16", "state", "status", "table_paragraph_count", "temporary_state",
        "token_present", "total_duration_ms", "type_id", "unresolved", "unresolved_count", "numbering_enabled",
        "validated_count", "value_present", "wait_attempts", "warning_code", "warning_count",
        "preview_confirmed_count", "preview_eligible_count", "preview_review_count",
        "conversion_state", "inline_shape_count", "mismatch_count", "section_count",
        "shape_count", "source_format", "target_format", "target_state", "wpsjs_version",
    }
)


def configure_wps_logging(app_root: Path) -> Path:
    """Enable DocxTool-format file logging under the local WPS runtime root."""
    global _WPS_FILE_HANDLER
    log_dir = Path(app_root) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(str(log_dir), to_file=False)
    logger = get_logger()
    log_path = log_dir / "公文排版工具.log"
    if _WPS_FILE_HANDLER is not None:
        logger.removeHandler(_WPS_FILE_HANDLER)
        _WPS_FILE_HANDLER.close()
    handler = RotatingFileHandler(
        log_path,
        maxBytes=WPS_LOG_MAX_BYTES,
        backupCount=WPS_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    _WPS_FILE_HANDLER = handler
    return log_dir


def _safe_value(value: Any) -> str:
    text = str(value)
    return text.replace("\r", " ").replace("\n", " ")[:240]


def sanitize_wps_log_fields(fields: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not fields:
        return {}
    result = {}
    for key, value in fields.items():
        if (
            key not in SAFE_WPS_LOG_FIELDS
            or not (isinstance(value, (str, int, float, bool)) or value is None)
        ):
            continue
        if key == "path" and (
            not isinstance(value, str)
            or not value.startswith("/v1/")
            or "\\" in value
            or ":" in value
        ):
            continue
        result[str(key)] = value
    return result


def _fields_text(fields: Optional[Dict[str, Any]]) -> str:
    safe_fields = sanitize_wps_log_fields(fields)
    if not safe_fields:
        return ""
    parts = [
        f"{key}={_safe_value(value)}" for key, value in sorted(safe_fields.items())
    ]
    return " | " + " ".join(parts)


def log_event(
    level: str,
    component: str,
    event: str,
    message: str,
    fields: Optional[Dict[str, Any]] = None,
) -> None:
    """Write one WPS event through the shared ``docx_tool`` logger."""
    numeric = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "WARN": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }.get(str(level or "INFO").upper(), 20)
    LOGGER.log(
        numeric,
        "[WPS][%s] %s | %s%s",
        _safe_value(component or "app"),
        _safe_value(event or "event"),
        _safe_value(message or ""),
        _fields_text(fields),
    )


def file_identity(path: Path) -> str:
    """Return a short non-reversible identifier for a local path."""
    return hashlib.sha256(str(Path(path).resolve()).encode("utf-8")).hexdigest()[:12]


@contextmanager
def document_log_context(
    source_path: Path,
    log_dir: Path,
    operation_id: str,
    request_id: str = "",
) -> Iterator[str]:
    """Route DocxTool core logs for one WPS operation to a filename-safe log."""
    log_path = make_document_log_path(
        "document",
        log_dir=str(log_dir),
        suffix=f"wps-{operation_id[:8]}",
    )
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    token = set_context_log_path(log_path)
    try:
        log_event(
            "INFO",
            "format",
            "document.log.start",
            "WPS 文档任务日志已建立",
            {
                "operation_id_short": operation_id[:12],
                "request_id": request_id,
                "file_id": file_identity(source_path),
                "log_file": Path(log_path).name,
            },
        )
        yield log_path
    finally:
        reset_context_log_path(token)
