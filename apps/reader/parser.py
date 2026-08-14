"""Deterministic chapter detection for locally imported TXT files."""

from __future__ import annotations

import re
from typing import List

from .models import Chapter


_CHINESE_NUMBER = "一二三四五六七八九十百千万零〇两"
_CHAPTER_HEADING = re.compile(
    rf"^[ \t]*(?P<title>(?:第[{_CHINESE_NUMBER}0-9]{{1,12}}[章节回][^\r\n]{{0,100}}|chapter[ \t]+[0-9]+[^\r\n]{{0,100}}))[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_chapters(text: str, book_id: str) -> List[Chapter]:
    """Return source-order chapter slices, or one neutral full-text block."""
    normalized = normalize_newlines(text)
    matches = list(_CHAPTER_HEADING.finditer(normalized))
    if not matches:
        return [Chapter(book_id, 0, "全文", 0, len(normalized))]
    chapters: List[Chapter] = []
    for index, match in enumerate(matches):
        end_offset = (
            matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        )
        chapters.append(
            Chapter(
                book_id=book_id,
                chapter_index=index,
                title=match.group("title").strip(),
                start_offset=match.start(),
                end_offset=end_offset,
            )
        )
    return chapters
