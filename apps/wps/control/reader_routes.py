"""Thin local HTTP adapter for the independent TXT reader domain."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import unquote

from apps.reader import ReaderError, ReaderService

from .logging_adapter import log_event


READER_GET_ROUTES = frozenset({"/v1/reader/state", "/v1/reader/content"})
READER_POST_ROUTES = frozenset(
    {
        "/v1/reader/import",
        "/v1/reader/select",
        "/v1/reader/delete",
        "/v1/reader/progress",
        "/v1/reader/settings",
    }
)
READER_IMPORT_MAX_BYTES = 64 * 1024 * 1024


def dispatch_reader_get(
    service: ReaderService,
    path: str,
    query: Mapping[str, str],
) -> dict[str, Any]:
    if path == "/v1/reader/state":
        state = service.state()
        return {
            "books": [_book_value(book) for book in state["books"]],
            "current_book": (
                _book_value(state["current_book"])
                if state["current_book"] is not None
                else None
            ),
            "progress": (
                asdict(state["progress"])
                if state["progress"] is not None
                else None
            ),
            "chapters": (
                [asdict(chapter) for chapter in service.list_chapters(state["current_book"].id)]
                if state["current_book"] is not None
                else []
            ),
            "settings": asdict(state["settings"]),
        }
    if path == "/v1/reader/content":
        content = service.get_content(
            _required_text(query, "book_id", "READER_BOOK_NOT_FOUND"),
            _required_int(query, "chapter_index", "READER_CONTENT_INVALID"),
            start_offset=_optional_int(query, "start_offset", "READER_CONTENT_INVALID"),
            limit=_optional_int(query, "limit", "READER_CONTENT_INVALID") or 12_000,
        )
        return asdict(content)
    raise ReaderError("WPS_CONTROL_ROUTE_NOT_FOUND")


def dispatch_reader_post(
    service: ReaderService,
    path: str,
    body: Mapping[str, Any],
    *,
    raw_import: Optional[bytes] = None,
    import_filename: str = "",
    request_id: str = "",
) -> dict[str, Any]:
    if path == "/v1/reader/import":
        if raw_import is None:
            raise ReaderError("READER_IMPORT_FAILED")
        _log("INFO", "reader.import.start", "开始导入本地 TXT", request_id)
        try:
            result = service.import_bytes(raw_import, _import_display_name(import_filename))
        except ReaderError as exc:
            _log(
                "ERROR",
                "reader.import.failed",
                "本地 TXT 导入失败",
                request_id,
                error_code=exc.code,
            )
            raise
        _log(
            "INFO",
            "reader.import.completed",
            "本地 TXT 导入完成",
            request_id,
            book_id_short=result.book.id[:12],
            size_bytes=result.book.size_bytes,
            encoding=result.book.encoding,
            chapter_count=result.chapter_count,
        )
        return {"book": _book_value(result.book), "chapter_count": result.chapter_count}
    if path == "/v1/reader/select":
        book = service.select_book(_required_body_text(body, "book_id", "READER_BOOK_NOT_FOUND"))
        _log("INFO", "reader.book.selected", "已切换本地书籍", request_id, book_id_short=book.id[:12])
        return {"book": _book_value(book), "progress": asdict(service.load_progress(book.id))}
    if path == "/v1/reader/delete":
        book_id = _required_body_text(body, "book_id", "READER_BOOK_NOT_FOUND")
        next_book = service.delete_book(book_id)
        _log("INFO", "reader.book.deleted", "已删除本地托管书籍", request_id, book_id_short=book_id[:12])
        return {"current_book": _book_value(next_book) if next_book is not None else None}
    if path == "/v1/reader/progress":
        progress = service.save_progress(
            _required_body_text(body, "book_id", "READER_PROGRESS_INVALID"),
            _required_body_int(body, "chapter_index", "READER_PROGRESS_INVALID"),
            _required_body_int(body, "text_offset", "READER_PROGRESS_INVALID"),
            _required_body_number(body, "scroll_ratio", "READER_PROGRESS_INVALID"),
        )
        _log("INFO", "reader.progress.saved", "阅读进度已保存", request_id, book_id_short=progress.book_id[:12])
        return {"progress": asdict(progress)}
    if path == "/v1/reader/settings":
        values = body.get("settings")
        if not isinstance(values, dict):
            raise ReaderError("READER_SETTINGS_INVALID")
        settings = service.save_settings(values)
        _log("INFO", "reader.settings.saved", "阅读设置已保存", request_id)
        return {"settings": asdict(settings)}
    raise ReaderError("WPS_CONTROL_ROUTE_NOT_FOUND")


def _book_value(book) -> dict[str, Any]:
    # ``stored_filename`` is internal storage state and never leaves loopback.
    return {
        "id": book.id,
        "display_name": book.display_name,
        "encoding": book.encoding,
        "size_bytes": book.size_bytes,
        "chapter_count": book.chapter_count,
        "imported_at": book.imported_at,
    }


def _import_display_name(value: str) -> str:
    name = unquote(value or "")
    if (
        not name
        or len(name) > 240
        or name != Path(name).name
        or "/" in name
        or "\\" in name
    ):
        raise ReaderError("READER_IMPORT_FAILED")
    return name


def _required_text(query: Mapping[str, str], key: str, code: str) -> str:
    value = query.get(key)
    if not isinstance(value, str) or not value:
        raise ReaderError(code)
    return value


def _required_int(query: Mapping[str, str], key: str, code: str) -> int:
    return _parse_int(_required_text(query, key, code), code)


def _optional_int(
    query: Mapping[str, str], key: str, code: str
) -> Optional[int]:
    value = query.get(key)
    return None if value is None else _parse_int(value, code)


def _required_body_text(body: Mapping[str, Any], key: str, code: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise ReaderError(code)
    return value


def _required_body_int(body: Mapping[str, Any], key: str, code: str) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReaderError(code)
    return value


def _required_body_number(body: Mapping[str, Any], key: str, code: str) -> float:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReaderError(code)
    return float(value)


def _parse_int(value: str, code: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ReaderError(code) from exc


def _log(level: str, event: str, message: str, request_id: str, **fields: Any) -> None:
    log_event(level, "reader", event, message, {"request_id": request_id, **fields})
