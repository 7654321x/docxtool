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


def configure_wps_logging(app_root: Path) -> Path:
    """Enable DocxTool-format file logging under ``apps/wps/logs``."""
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


def _fields_text(fields: Optional[Dict[str, Any]]) -> str:
    if not fields:
        return ""
    parts = [f"{key}={_safe_value(value)}" for key, value in sorted(fields.items())]
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
                "operation_id": operation_id[:8],
                "file_id": file_identity(source_path),
                "log_file": Path(log_path).name,
            },
        )
        yield log_path
    finally:
        reset_context_log_path(token)
