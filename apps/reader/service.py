"""Single business facade for the completely local TXT reader."""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any, Mapping, Optional, Union
from uuid import uuid4

from .import_text import TextImportError, decode_text
from .models import Book, Chapter, ImportResult, ReaderContent, ReaderProgress, ReaderSettings
from .parser import normalize_newlines, parse_chapters
from .paths import ReaderPaths, reader_paths
from .storage import ReaderStorage, ReaderStorageError


MAX_IMPORT_BYTES = 64 * 1024 * 1024
DEFAULT_CONTENT_CHARS = 12_000
MAX_CONTENT_CHARS = 24_000
_SETTING_FIELDS = frozenset(
    {
        "last_book_id",
        "font_size",
        "line_height",
        "theme",
        "opacity",
        "auto_scroll_speed",
        "stealth_mode",
    }
)


class ReaderError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ReaderService:
    """Owns reader data without importing WPS, Core, or public-account code."""

    def __init__(self, paths: Optional[ReaderPaths] = None) -> None:
        self.paths = paths or reader_paths()
        self.storage = ReaderStorage(self.paths)
        self.storage.initialize()

    def import_book(self, source_path: Union[str, os.PathLike]) -> ImportResult:
        source = Path(source_path)
        try:
            raw = source.read_bytes()
        except OSError as exc:
            raise ReaderError("READER_IMPORT_FAILED") from exc
        return self.import_bytes(raw, source.name)

    def import_bytes(self, raw: bytes, display_name: str) -> ImportResult:
        if not isinstance(raw, bytes):
            raise ReaderError("READER_IMPORT_FAILED")
        if len(raw) > MAX_IMPORT_BYTES:
            raise ReaderError("READER_FILE_TOO_LARGE")
        try:
            decoded, encoding = decode_text(raw)
        except TextImportError as exc:
            raise ReaderError(exc.code) from exc
        text = normalize_newlines(decoded)
        if not text.strip():
            raise ReaderError("READER_FILE_EMPTY")
        name = Path(display_name).stem.strip()
        if not name:
            raise ReaderError("READER_IMPORT_FAILED")
        book_id = uuid4().hex
        chapters = parse_chapters(text, book_id)
        book = Book(
            id=book_id,
            display_name=name,
            stored_filename=f"{book_id}.txt",
            encoding=encoding,
            size_bytes=len(raw),
            chapter_count=len(chapters),
            imported_at=int(time.time()),
        )
        temporary = self.paths.temp_dir / f"{book_id}.tmp"
        target = self.paths.books_dir / book.stored_filename
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(temporary, target)
            self.storage.add_book(book, chapters, select_as_current=True)
            return ImportResult(book=book, chapter_count=len(chapters))
        except ReaderStorageError as exc:
            target.unlink(missing_ok=True)
            raise ReaderError(exc.code) from exc
        except OSError as exc:
            target.unlink(missing_ok=True)
            raise ReaderError("READER_IMPORT_FAILED") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def list_books(self) -> list[Book]:
        return self.storage.list_books()

    def get_book(self, book_id: str) -> Book:
        book = self.storage.get_book(book_id)
        if book is None:
            raise ReaderError("READER_BOOK_NOT_FOUND")
        return book

    def select_book(self, book_id: str) -> Book:
        book = self.get_book(book_id)
        self.save_settings({"last_book_id": book.id})
        return book

    def list_chapters(self, book_id: str) -> list[Chapter]:
        self.get_book(book_id)
        return self.storage.list_chapters(book_id)

    def delete_book(self, book_id: str) -> Optional[Book]:
        book = self.get_book(book_id)
        settings = self.get_settings()
        target = self.paths.books_dir / book.stored_filename
        pending_delete = self.paths.temp_dir / (book.stored_filename + ".delete")
        try:
            os.replace(target, pending_delete)
        except FileNotFoundError as exc:
            raise ReaderError("READER_CONTENT_NOT_FOUND") from exc
        except OSError as exc:
            raise ReaderError("READER_STORAGE_ERROR") from exc
        try:
            self.storage.delete_book(book.id, settings.last_book_id)
        except ReaderStorageError as exc:
            try:
                os.replace(pending_delete, target)
            except OSError:
                pass
            raise ReaderError(exc.code) from exc
        try:
            pending_delete.unlink()
        except OSError as exc:
            raise ReaderError("READER_STORAGE_ERROR") from exc
        return self.get_book(settings.last_book_id) if settings.last_book_id != book.id else self._current_book()

    def _current_book(self) -> Optional[Book]:
        current_book_id = self.get_settings().last_book_id
        return self.storage.get_book(current_book_id) if current_book_id else None

    def get_chapter(self, book_id: str, chapter_index: int):
        self.get_book(book_id)
        chapter = self.storage.get_chapter(book_id, chapter_index)
        if chapter is None:
            raise ReaderError("READER_CONTENT_NOT_FOUND")
        return chapter

    def get_content(
        self,
        book_id: str,
        chapter_index: int,
        *,
        start_offset: Optional[int] = None,
        limit: int = DEFAULT_CONTENT_CHARS,
    ) -> ReaderContent:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_CONTENT_CHARS:
            raise ReaderError("READER_CONTENT_INVALID")
        book = self.get_book(book_id)
        chapter = self.get_chapter(book_id, chapter_index)
        start = chapter.start_offset if start_offset is None else start_offset
        if isinstance(start, bool) or not isinstance(start, int) or not chapter.start_offset <= start < chapter.end_offset:
            raise ReaderError("READER_CONTENT_INVALID")
        try:
            text = (self.paths.books_dir / book.stored_filename).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ReaderError("READER_CONTENT_NOT_FOUND") from exc
        end = min(start + limit, chapter.end_offset)
        return ReaderContent(
            book_id=book.id,
            chapter_index=chapter.chapter_index,
            chapter_title=chapter.title,
            chapter_start_offset=chapter.start_offset,
            start_offset=start,
            end_offset=end,
            chapter_end_offset=chapter.end_offset,
            text=text[start:end],
        )

    def load_progress(self, book_id: str) -> ReaderProgress:
        book = self.get_book(book_id)
        current = self.storage.load_progress(book.id)
        if current is not None:
            return current
        chapter = self.get_chapter(book.id, 0)
        return ReaderProgress(book.id, chapter.chapter_index, chapter.start_offset, 0.0, 0)

    def save_progress(
        self,
        book_id: str,
        chapter_index: int,
        text_offset: int,
        scroll_ratio: float,
    ) -> ReaderProgress:
        chapter = self.get_chapter(book_id, chapter_index)
        if isinstance(text_offset, bool) or not isinstance(text_offset, int):
            raise ReaderError("READER_PROGRESS_INVALID")
        if not chapter.start_offset <= text_offset <= chapter.end_offset:
            raise ReaderError("READER_PROGRESS_INVALID")
        if isinstance(scroll_ratio, bool) or not isinstance(scroll_ratio, (int, float)):
            raise ReaderError("READER_PROGRESS_INVALID")
        ratio = float(scroll_ratio)
        if not 0.0 <= ratio <= 1.0:
            raise ReaderError("READER_PROGRESS_INVALID")
        progress = ReaderProgress(
            book_id=book_id,
            chapter_index=chapter_index,
            text_offset=text_offset,
            scroll_ratio=ratio,
            updated_at=int(time.time()),
        )
        try:
            self.storage.save_progress(progress)
        except ReaderStorageError as exc:
            raise ReaderError(exc.code) from exc
        return progress

    def get_settings(self) -> ReaderSettings:
        values = {field: self.storage.get_setting(field) for field in _SETTING_FIELDS}
        return ReaderSettings(**{key: value for key, value in values.items() if value is not None})

    def save_settings(self, values: Mapping[str, Any]) -> ReaderSettings:
        if not isinstance(values, Mapping) or not set(values).issubset(_SETTING_FIELDS):
            raise ReaderError("READER_SETTINGS_INVALID")
        current = self.get_settings()
        merged = {field: getattr(current, field) for field in _SETTING_FIELDS}
        merged.update(values)
        self._validate_settings(merged)
        try:
            for key, value in values.items():
                self.storage.set_setting(key, value)
        except ReaderStorageError as exc:
            raise ReaderError(exc.code) from exc
        return ReaderSettings(**merged)

    def state(self) -> dict[str, Any]:
        settings = self.get_settings()
        current_book = self._current_book()
        return {
            "books": self.list_books(),
            "current_book": current_book,
            "progress": self.load_progress(current_book.id) if current_book else None,
            "settings": settings,
        }

    @staticmethod
    def _validate_settings(values: Mapping[str, Any]) -> None:
        last_book_id = values["last_book_id"]
        if last_book_id is not None and (not isinstance(last_book_id, str) or not last_book_id):
            raise ReaderError("READER_SETTINGS_INVALID")
        if isinstance(values["font_size"], bool) or not isinstance(values["font_size"], int) or not 12 <= values["font_size"] <= 28:
            raise ReaderError("READER_SETTINGS_INVALID")
        if isinstance(values["line_height"], bool) or not isinstance(values["line_height"], (int, float)) or not 1.4 <= float(values["line_height"]) <= 2.0:
            raise ReaderError("READER_SETTINGS_INVALID")
        if values["theme"] not in {"light", "soft_gray", "eye_care"}:
            raise ReaderError("READER_SETTINGS_INVALID")
        if isinstance(values["opacity"], bool) or not isinstance(values["opacity"], (int, float)) or not 0.55 <= float(values["opacity"]) <= 1.0:
            raise ReaderError("READER_SETTINGS_INVALID")
        if isinstance(values["auto_scroll_speed"], bool) or not isinstance(values["auto_scroll_speed"], (int, float)) or not 0.5 <= float(values["auto_scroll_speed"]) <= 2.0:
            raise ReaderError("READER_SETTINGS_INVALID")
        if not isinstance(values["stealth_mode"], bool):
            raise ReaderError("READER_SETTINGS_INVALID")
