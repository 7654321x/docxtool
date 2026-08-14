"""SQLite metadata storage for the independent local reader domain."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Optional

from .models import Book, Chapter, ReaderProgress
from .paths import ReaderPaths


class ReaderStorageError(RuntimeError):
    code = "READER_STORAGE_ERROR"


class ReaderStorage:
    def __init__(self, paths: ReaderPaths) -> None:
        self.paths = paths

    def initialize(self) -> None:
        self.paths.ensure_directories()
        try:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS books (
                        id TEXT PRIMARY KEY,
                        display_name TEXT NOT NULL,
                        stored_filename TEXT NOT NULL UNIQUE,
                        encoding TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        chapter_count INTEGER NOT NULL,
                        imported_at INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS chapters (
                        book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                        chapter_index INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        start_offset INTEGER NOT NULL,
                        end_offset INTEGER NOT NULL,
                        PRIMARY KEY (book_id, chapter_index)
                    );
                    CREATE TABLE IF NOT EXISTS progress (
                        book_id TEXT PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
                        chapter_index INTEGER NOT NULL,
                        text_offset INTEGER NOT NULL,
                        scroll_ratio REAL NOT NULL,
                        updated_at INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    """
                )
                if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
                    conn.execute("PRAGMA user_version=1")
        except sqlite3.Error as exc:
            raise ReaderStorageError() from exc

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.paths.database_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def add_book(
        self,
        book: Book,
        chapters: Iterable[Chapter],
        *,
        select_as_current: bool = False,
    ) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO books
                    (id,display_name,stored_filename,encoding,size_bytes,chapter_count,imported_at)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        book.id,
                        book.display_name,
                        book.stored_filename,
                        book.encoding,
                        book.size_bytes,
                        book.chapter_count,
                        book.imported_at,
                    ),
                )
                conn.executemany(
                    """
                    INSERT INTO chapters (book_id,chapter_index,title,start_offset,end_offset)
                    VALUES (?,?,?,?,?)
                    """,
                    [
                        (
                            chapter.book_id,
                            chapter.chapter_index,
                            chapter.title,
                            chapter.start_offset,
                            chapter.end_offset,
                        )
                        for chapter in chapters
                    ],
                )
                if select_as_current:
                    conn.execute(
                        """
                        INSERT INTO settings (key,value) VALUES (?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value
                        """,
                        ("last_book_id", json.dumps(book.id, ensure_ascii=False)),
                    )
        except sqlite3.Error as exc:
            raise ReaderStorageError() from exc

    def list_books(self) -> list[Book]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM books ORDER BY imported_at DESC, id DESC"
                ).fetchall()
        except sqlite3.Error as exc:
            raise ReaderStorageError() from exc
        return [_book_from_row(row) for row in rows]

    def get_book(self, book_id: str) -> Optional[Book]:
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        except sqlite3.Error as exc:
            raise ReaderStorageError() from exc
        return _book_from_row(row) if row is not None else None

    def list_chapters(self, book_id: str) -> list[Chapter]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM chapters WHERE book_id=? ORDER BY chapter_index",
                    (book_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise ReaderStorageError() from exc
        return [_chapter_from_row(row) for row in rows]

    def get_chapter(self, book_id: str, chapter_index: int) -> Optional[Chapter]:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM chapters WHERE book_id=? AND chapter_index=?",
                    (book_id, chapter_index),
                ).fetchone()
        except sqlite3.Error as exc:
            raise ReaderStorageError() from exc
        return _chapter_from_row(row) if row is not None else None

    def delete_book(self, book_id: str, current_book_id: Optional[str]) -> None:
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM books WHERE id=?", (book_id,))
                if current_book_id != book_id:
                    return
                next_row = conn.execute(
                    "SELECT id FROM books ORDER BY imported_at DESC, id DESC LIMIT 1"
                ).fetchone()
                next_book_id = str(next_row["id"]) if next_row is not None else None
                conn.execute(
                    """
                    INSERT INTO settings (key,value) VALUES (?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    ("last_book_id", json.dumps(next_book_id, ensure_ascii=False)),
                )
        except sqlite3.Error as exc:
            raise ReaderStorageError() from exc

    def load_progress(self, book_id: str) -> Optional[ReaderProgress]:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM progress WHERE book_id=?", (book_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise ReaderStorageError() from exc
        return _progress_from_row(row) if row is not None else None

    def save_progress(self, progress: ReaderProgress) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO progress (book_id,chapter_index,text_offset,scroll_ratio,updated_at)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(book_id) DO UPDATE SET
                    chapter_index=excluded.chapter_index,
                    text_offset=excluded.text_offset,
                    scroll_ratio=excluded.scroll_ratio,
                    updated_at=excluded.updated_at
                    """,
                    (
                        progress.book_id,
                        progress.chapter_index,
                        progress.text_offset,
                        progress.scroll_ratio,
                        progress.updated_at,
                    ),
                )
        except sqlite3.Error as exc:
            raise ReaderStorageError() from exc

    def get_setting(self, key: str) -> Any:
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        except sqlite3.Error as exc:
            raise ReaderStorageError() from exc
        return json.loads(row["value"]) if row is not None else None

    def set_setting(self, key: str, value: Any) -> None:
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO settings (key,value) VALUES (?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (key, encoded),
                )
        except (TypeError, ValueError, sqlite3.Error) as exc:
            raise ReaderStorageError() from exc


def _book_from_row(row: sqlite3.Row) -> Book:
    return Book(
        id=str(row["id"]),
        display_name=str(row["display_name"]),
        stored_filename=str(row["stored_filename"]),
        encoding=str(row["encoding"]),
        size_bytes=int(row["size_bytes"]),
        chapter_count=int(row["chapter_count"]),
        imported_at=int(row["imported_at"]),
    )


def _chapter_from_row(row: sqlite3.Row) -> Chapter:
    return Chapter(
        book_id=str(row["book_id"]),
        chapter_index=int(row["chapter_index"]),
        title=str(row["title"]),
        start_offset=int(row["start_offset"]),
        end_offset=int(row["end_offset"]),
    )


def _progress_from_row(row: sqlite3.Row) -> ReaderProgress:
    return ReaderProgress(
        book_id=str(row["book_id"]),
        chapter_index=int(row["chapter_index"]),
        text_offset=int(row["text_offset"]),
        scroll_ratio=float(row["scroll_ratio"]),
        updated_at=int(row["updated_at"]),
    )
