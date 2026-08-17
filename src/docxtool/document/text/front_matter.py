"""Shared structural shapes for document-front metadata."""

from __future__ import annotations

import re


_HEADER_DATE_VALUE = (
    r"(?:(?:19|20)\d{2}|[零〇○一二两三四五六七八九]{4})年"
    r"(?:[0-9一二两三四五六七八九十〇○×X]{1,3})月"
    r"(?:[0-9一二两三四五六七八九十〇○×X]{1,3})(?:日|号)"
)
_PARENTHESIZED_HEADER_DATE_RE = re.compile(
    rf"^[（(]{_HEADER_DATE_VALUE}[）)]$"
)
_MEETING_TITLE_DESCRIPTOR_RE = re.compile(
    r"^在[\u4e00-\u9fffA-Za-z0-9（）()、，,.·\-]{3,70}"
    r"(?:会议|大会|全会|座谈会|论坛|仪式|活动)(?:上|期间|时)$"
)
_HEADER_SENTENCE_TERMINATORS = frozenset("。！？；;：:")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def is_parenthesized_header_date_line(text: str) -> bool:
    """Return whether *text* is a complete parenthesized front-matter date."""
    return bool(_PARENTHESIZED_HEADER_DATE_RE.fullmatch(_compact(text)))


def is_meeting_title_descriptor(text: str) -> bool:
    """Return whether *text* is a short document-head meeting context line."""
    return bool(_MEETING_TITLE_DESCRIPTOR_RE.fullmatch(_compact(text)))


def is_short_non_prose_title_line(text: str) -> bool:
    """Return whether *text* can safely precede a document-head date line."""
    value = _compact(text)
    return bool(
        value
        and len(value) <= 60
        and not is_parenthesized_header_date_line(value)
        and not any(mark in value for mark in _HEADER_SENTENCE_TERMINATORS)
        and not re.match(r"^[一二三四五六七八九十]+、", value)
    )


def is_front_title_date_meeting_profile(parts: list[str]) -> bool:
    """Return whether soft-broken lines prove a title/date/meeting-meta profile.

    This only establishes logical structural boundaries. Recognition and
    rendering decide the final type and format later in the pipeline.
    """
    lines = [str(part or "").strip() for part in parts if str(part or "").strip()]
    if len(lines) < 3:
        return False
    date_positions = [
        index for index, line in enumerate(lines) if is_parenthesized_header_date_line(line)
    ]
    if len(date_positions) != 1:
        return False
    date_index = date_positions[0]
    if date_index == 0 or date_index == len(lines) - 1:
        return False
    return bool(
        all(is_short_non_prose_title_line(line) for line in lines[:date_index])
        and all(is_meeting_title_descriptor(line) for line in lines[date_index + 1 :])
    )
