"""Independent local TXT reader domain for the DocxTool WPS peripheral."""

from .models import Book, Chapter, ImportResult, ReaderContent, ReaderProgress, ReaderSettings
from .paths import ReaderPaths, reader_paths
from .service import ReaderError, ReaderService

__all__ = [
    "Book",
    "Chapter",
    "ImportResult",
    "ReaderContent",
    "ReaderError",
    "ReaderPaths",
    "ReaderProgress",
    "ReaderService",
    "ReaderSettings",
    "reader_paths",
]
