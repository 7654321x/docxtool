"""Small, dependency-free data models for the local TXT reader."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Book:
    id: str
    display_name: str
    stored_filename: str
    encoding: str
    size_bytes: int
    chapter_count: int
    imported_at: int


@dataclass(frozen=True)
class Chapter:
    book_id: str
    chapter_index: int
    title: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class ReaderProgress:
    book_id: str
    chapter_index: int
    text_offset: int
    scroll_ratio: float
    updated_at: int


@dataclass(frozen=True)
class ReaderSettings:
    last_book_id: Optional[str] = None
    font_size: int = 16
    line_height: float = 1.6
    theme: str = "light"
    opacity: float = 1.0
    auto_scroll_speed: float = 1.0
    stealth_mode: bool = False


@dataclass(frozen=True)
class ImportResult:
    book: Book
    chapter_count: int


@dataclass(frozen=True)
class ReaderContent:
    book_id: str
    chapter_index: int
    chapter_title: str
    chapter_start_offset: int
    start_offset: int
    end_offset: int
    chapter_end_offset: int
    text: str
