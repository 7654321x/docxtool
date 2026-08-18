"""Shared DocxTool logging implementation.

该模块只负责 logger、handler 和文档上下文日志，不依赖格式配置或文档
识别/渲染模块，避免日志适配器反向加载排版配置。
"""

from __future__ import annotations

import contextvars
import logging
import os as _os
import re
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional


LOGGER_NAME = "docx_tool"
LOG_FORMAT = "%(asctime)s [%(levelname)-5s] %(name)s | %(message)s"
LOG_TO_FILE = True
_LOG_DIR: Optional[str] = None
_FILE_HANDLER: Optional[logging.Handler] = None
_CONTEXT_FILE_HANDLER: Optional[logging.Handler] = None
_CURRENT_LOG_PATH: Optional[str] = None
_CONTEXT_LOG_PATH = contextvars.ContextVar("docx_tool_context_log_path", default="")
_MAX_LOG_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 5


def _sanitize_log_stem(filepath: str) -> str:
    """Return a Windows-safe log filename stem while preserving readable Chinese."""
    stem = _os.path.splitext(_os.path.basename(str(filepath or "")))[0].strip()
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" ._")
    return (stem or "document")[:80]


def _build_document_log_path(
    filepath: str,
    log_dir: str = None,
    timestamp: str = None,
    suffix: str = "",
) -> str:
    root = log_dir or _LOG_DIR or _os.path.join(_os.getcwd(), "logs")
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = _sanitize_log_stem(filepath)
    safe_suffix = _sanitize_log_stem(suffix) if suffix else ""
    suffix_part = f"_{safe_suffix}" if safe_suffix else ""
    return _os.path.join(root, f"{ts}_{stem}{suffix_part}.log")


def make_document_log_path(
    filepath: str,
    log_dir: str = None,
    suffix: str = "",
) -> str:
    """Build a per-document log path without changing active handlers."""
    return _build_document_log_path(filepath, log_dir=log_dir, suffix=suffix)


class _ContextFileHandler(logging.Handler):
    """Write records to the log path stored in the current execution context."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.setFormatter(logging.Formatter(LOG_FORMAT))

    def emit(self, record):
        log_path = _CONTEXT_LOG_PATH.get("")
        if not log_path:
            return
        try:
            msg = self.format(record)
            _os.makedirs(_os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as file:
                file.write(msg + "\n")
        except Exception:
            self.handleError(record)


class _BelowWarningFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.WARNING


def _ensure_console_handler(target: logging.Logger) -> None:
    if any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in target.handlers
    ):
        return
    target.setLevel(logging.DEBUG)
    formatter = logging.Formatter(LOG_FORMAT)
    normal_handler = logging.StreamHandler(sys.stdout)
    normal_handler.setLevel(logging.DEBUG)
    normal_handler.addFilter(_BelowWarningFilter())
    normal_handler.setFormatter(formatter)
    target.addHandler(normal_handler)
    problem_handler = logging.StreamHandler(sys.stderr)
    problem_handler.setLevel(logging.WARNING)
    problem_handler.setFormatter(formatter)
    target.addHandler(problem_handler)


def _ensure_context_file_handler(target: logging.Logger) -> None:
    global _CONTEXT_FILE_HANDLER
    if _CONTEXT_FILE_HANDLER is not None:
        return
    _CONTEXT_FILE_HANDLER = _ContextFileHandler()
    target.addHandler(_CONTEXT_FILE_HANDLER)


def _set_file_handler(log_path: str) -> str:
    global _FILE_HANDLER, _CURRENT_LOG_PATH
    target = logging.getLogger(LOGGER_NAME)
    _ensure_console_handler(target)
    if _FILE_HANDLER is not None:
        target.removeHandler(_FILE_HANDLER)
        try:
            _FILE_HANDLER.close()
        except Exception:
            pass
    _os.makedirs(_os.path.dirname(log_path), exist_ok=True)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=_MAX_LOG_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    target.addHandler(handler)
    _FILE_HANDLER = handler
    _CURRENT_LOG_PATH = log_path
    return log_path


def configure_logging(log_dir: str, to_file: bool = True) -> None:
    """设置日志输出目录和文件开关（Web 服务启动时调用一次）。"""
    global LOG_TO_FILE, _LOG_DIR
    LOG_TO_FILE = to_file
    _LOG_DIR = log_dir


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    """获取统一 logger：控制台全级 + 文件 DEBUG（如果开关开启）。"""
    global _FILE_HANDLER
    target = logging.getLogger(name)
    _ensure_console_handler(target)
    _ensure_context_file_handler(target)
    if LOG_TO_FILE and _LOG_DIR and _FILE_HANDLER is None:
        try:
            log_path = _os.path.join(_LOG_DIR, "公文排版工具.log")
            _set_file_handler(log_path)
            target.info(f"日志文件: {log_path}")
        except Exception as exc:
            target.warning(f"无法创建日志文件: {exc}")
    elif not LOG_TO_FILE and _FILE_HANDLER is not None:
        target.removeHandler(_FILE_HANDLER)
        _FILE_HANDLER = None
    return target


def start_document_log(filepath: str, suffix: str = "") -> str:
    """Switch file logging to a per-document log and return the log path."""
    if not LOG_TO_FILE:
        return ""
    log_path = _build_document_log_path(filepath, suffix=suffix)
    try:
        _set_file_handler(log_path)
        logging.getLogger(LOGGER_NAME).info(f"[日志] 文档日志: {log_path}")
        return log_path
    except Exception as exc:
        logging.getLogger(LOGGER_NAME).warning(f"[日志] 文档日志创建失败: {exc}")
        return ""


def set_context_log_path(log_path: str):
    """Route logs emitted in this execution context to log_path."""
    return _CONTEXT_LOG_PATH.set(log_path or "")


def reset_context_log_path(token) -> None:
    """Restore the previous context log path."""
    _CONTEXT_LOG_PATH.reset(token)


def close_file_log() -> None:
    """Close the active file log handler. Mainly useful for tests and shutdown."""
    global _FILE_HANDLER, _CURRENT_LOG_PATH
    if _FILE_HANDLER is None:
        return
    target = logging.getLogger(LOGGER_NAME)
    target.removeHandler(_FILE_HANDLER)
    try:
        _FILE_HANDLER.close()
    finally:
        _FILE_HANDLER = None
        _CURRENT_LOG_PATH = None


logger = get_logger()


__all__ = [
    "LOG_FORMAT",
    "LOGGER_NAME",
    "close_file_log",
    "configure_logging",
    "get_logger",
    "logger",
    "make_document_log_path",
    "reset_context_log_path",
    "set_context_log_path",
    "start_document_log",
]
