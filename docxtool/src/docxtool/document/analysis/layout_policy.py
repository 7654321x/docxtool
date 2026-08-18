"""Layout modification policy inferred from final structure and physical facts."""

from __future__ import annotations

from enum import Enum
import re


class LayoutPolicy(str, Enum):
    NORMALIZE = "normalize"
    PRESERVE_LAYOUT = "preserve_layout"
    PRESERVE_OBJECT = "preserve_object"


_COLUMN_SEPARATOR_RE = re.compile(r"(?:\t+| {2,}|\u3000+|\u00a0+)")
_OBJECT_TYPES = frozenset({"__table__", "__image__", "__object_caption__", "__letterhead__"})


def _column_count(text: str) -> int:
    parts = [part.strip() for part in _COLUMN_SEPARATOR_RE.split(text or "")]
    if len(parts) < 2 or any(not part or len(part) > 24 for part in parts):
        return 0
    if sum(mark in text for mark in "。！？；;.!?") > 1:
        return 0
    return len(parts)


def assign_pre_normalization_layout_hints(raw_blocks: list[tuple]) -> None:
    """Mark repeated manual columns after an attachment mark and title."""
    paragraph_blocks = [block for block in raw_blocks if block[0] == "paragraph"]
    for index, block in enumerate(paragraph_blocks):
        marker_text = block[2].source_physical_text.strip()
        if (
            not block[2].page_break_before
            or not re.fullmatch(
                r"附件\s*[0-9一二三四五六七八九十百千]*",
                marker_text,
            )
        ):
            continue
        rows = paragraph_blocks[index + 2 :]
        candidate_group: list[tuple] = []
        expected_columns = 0
        for row in rows:
            text = row[2].source_physical_text
            if re.fullmatch(r"附件\s*[0-9一二三四五六七八九十百千]*", text.strip()):
                break
            columns = _column_count(text)
            if not columns:
                break
            if expected_columns and columns != expected_columns:
                break
            expected_columns = columns
            candidate_group.append(row)
        if len(candidate_group) < 2:
            continue
        for row in candidate_group:
            row[2].layout_preservation_hint = True
            row[2].layout_preservation_evidence = (
                "attachment-content",
                "repeated-manual-columns",
            )


def assign_layout_policies(document_data, structure) -> None:
    """Assign the one final policy consumed by normalization output and Engine."""
    attachment_sources = {
        element.source_index
        for attachment in structure.attachments
        for element in attachment.span.elements
        if element.source_index is not None
    }
    for index, paragraph in enumerate(document_data.paragraphs):
        if paragraph.type_id in _OBJECT_TYPES:
            policy = LayoutPolicy.PRESERVE_OBJECT
        elif (
            index in attachment_sources
            and getattr(paragraph.features, "layout_preservation_hint", False)
        ):
            policy = LayoutPolicy.PRESERVE_LAYOUT
        else:
            policy = LayoutPolicy.NORMALIZE
        paragraph.meta["layout_policy"] = policy.value


def validate_layout_preservation(document_data) -> None:
    """Fail when protected text or its physical source order was changed."""
    source_indexes: list[int] = []
    for paragraph in document_data.paragraphs:
        if paragraph.meta.get("layout_policy") != LayoutPolicy.PRESERVE_LAYOUT.value:
            continue
        if paragraph.text != paragraph.original_text:
            raise ValueError("preserve-layout paragraph text changed before rendering")
        source_index = paragraph.features.source_physical_paragraph_index
        if source_index is not None:
            source_indexes.append(source_index)
    if source_indexes != sorted(source_indexes):
        raise ValueError("preserve-layout paragraph source order changed")
