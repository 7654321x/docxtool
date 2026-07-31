"""Reversible, host-neutral text coordinates for one physical paragraph.

The importer can split a Word paragraph into multiple logical blocks.  This
module keeps those blocks anchored to spans of the original paragraph text;
it deliberately does not use editor-specific range coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata
from typing import Optional, Tuple


def utf16_length(value: str) -> int:
    """Return a string length in UTF-16 code units."""
    return len((value or "").encode("utf-16-le")) // 2


def _canonical_piece(value: str) -> str:
    """Normalize only host-display differences with a stable source mapping."""
    if value == "\r\n" or value in {"\r", "\n"}:
        return "\n"
    if value in {"\u00a0", "\u3000"}:
        return " "
    return unicodedata.normalize("NFKC", value)


@dataclass(frozen=True)
class SourceTape:
    """Raw paragraph text plus a boundary-safe canonical representation.

    ``raw_*`` offsets are UTF-16 offsets in ``raw_text``.  ``canonical_*``
    offsets are UTF-16 offsets in ``canonical_text``.  They are never WPS or
    Word API range offsets.  A raw span created by the importer always starts
    and ends at a mapped boundary, allowing its canonical span to be recovered
    without a text search.
    """

    raw_text: str
    canonical_text: str
    raw_boundary_to_canonical_utf16: Tuple[int, ...]
    canonical_boundary_to_raw_index: Tuple[int, ...]

    @classmethod
    def from_text(cls, raw_text: str) -> "SourceTape":
        raw = raw_text or ""
        pieces = []
        raw_boundaries = [0] * (len(raw) + 1)
        canonical_boundaries = [0]
        canonical_utf16 = 0
        raw_index = 0
        raw_boundaries[0] = 0

        while raw_index < len(raw):
            start = raw_index
            value = raw[raw_index]
            raw_index += 1
            if value == "\r" and raw_index < len(raw) and raw[raw_index] == "\n":
                value += raw[raw_index]
                raw_index += 1
            piece = _canonical_piece(value)
            raw_boundaries[start] = canonical_utf16
            # A CRLF interior is not a legal fragment boundary, but mapping it
            # to the preceding canonical boundary keeps the conversion total.
            for boundary in range(start + 1, raw_index):
                raw_boundaries[boundary] = canonical_utf16
            for character in piece:
                pieces.append(character)
                canonical_utf16 += utf16_length(character)
                canonical_boundaries.append(raw_index)
            raw_boundaries[raw_index] = canonical_utf16

        return cls(
            raw_text=raw,
            canonical_text="".join(pieces),
            raw_boundary_to_canonical_utf16=tuple(raw_boundaries),
            canonical_boundary_to_raw_index=tuple(canonical_boundaries),
        )

    def raw_offset_utf16(self, raw_index: int) -> Optional[int]:
        if not 0 <= raw_index <= len(self.raw_text):
            return None
        return utf16_length(self.raw_text[:raw_index])

    def canonical_offset_for_raw_index(self, raw_index: int) -> Optional[int]:
        if not 0 <= raw_index <= len(self.raw_text):
            return None
        return self.raw_boundary_to_canonical_utf16[raw_index]

    def canonical_range_for_raw_span(self, start: int, end: int) -> Optional[Tuple[int, int]]:
        if not 0 <= start < end <= len(self.raw_text):
            return None
        return (
            self.raw_boundary_to_canonical_utf16[start],
            self.raw_boundary_to_canonical_utf16[end],
        )

    def raw_index_for_canonical_utf16(self, offset: int) -> Optional[int]:
        if offset < 0:
            return None
        current = 0
        if offset == 0:
            return 0
        for index, character in enumerate(self.canonical_text, start=1):
            current += utf16_length(character)
            if current == offset:
                return self.canonical_boundary_to_raw_index[index]
            if current > offset:
                return None
        return len(self.raw_text) if current == offset else None

    def raw_span_for_canonical_range(self, start: int, end: int) -> Optional[Tuple[int, int]]:
        if start >= end:
            return None
        raw_start = self.raw_index_for_canonical_utf16(start)
        raw_end = self.raw_index_for_canonical_utf16(end)
        if raw_start is None or raw_end is None or raw_start >= raw_end:
            return None
        return raw_start, raw_end

    def raw_slice_utf16(self, start: int, end: int) -> Optional[str]:
        if start < 0 or end <= start:
            return None
        encoded = self.raw_text.encode("utf-16-le")
        if end * 2 > len(encoded):
            return None
        try:
            return encoded[start * 2:end * 2].decode("utf-16-le")
        except UnicodeDecodeError:
            return None


def canonicalize_text(value: str) -> str:
    """Return the shared canonical text used for host binding comparisons."""
    return SourceTape.from_text(value).canonical_text
