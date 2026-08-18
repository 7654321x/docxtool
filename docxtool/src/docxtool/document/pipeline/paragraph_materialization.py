"""Mechanical conversion of importer stream items into paragraph models."""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Optional, Tuple

from docxtool.document.models import ParagraphData


def next_text_and_features(flat_lines: Iterable[tuple], index: int) -> Tuple[str, Any]:
    """Return the next text item and its features without changing stream order."""

    items = flat_lines if isinstance(flat_lines, list) else list(flat_lines)
    for next_item in items[index + 1 :]:
        if next_item[0] == "text":
            return next_item[1], next_item[2]
    return "", None


def materialize_non_text_item(item: tuple) -> Optional[ParagraphData]:
    """Convert one protected/table/image stream item using the legacy mapping."""

    if item[0] == "table":
        return ParagraphData(
            text="", type_id="__table__", original_text="", features=None, meta={"table": item[1]}
        )
    if item[0] == "paragraph_xml":
        return ParagraphData(
            text="",
            type_id="__image__",
            original_text="",
            features=None,
            meta={"image_xml": item[1]},
        )
    if item[0] == "protected_paragraph_xml":
        caption_text = item[1].text
        return ParagraphData(
            text=caption_text,
            type_id="__object_caption__",
            original_text=caption_text,
            features=item[2],
            meta={"paragraph_xml": item[1]},
        )
    if item[0] == "letterhead_paragraph_xml":
        return ParagraphData(
            text="",
            type_id="__letterhead__",
            original_text="",
            features=None,
            meta={"paragraph_xml": item[1]},
        )
    return None


def materialize_text_paragraph(
    *,
    line: str,
    clean_text: str,
    type_id: str,
    features: Any,
    meta: dict,
    inline_tokens: list,
    sect_pr: Any,
    strict_preservation: bool,
    recognition_version: str,
    paragraph_index: int,
    logger: Any,
) -> ParagraphData:
    """Build one text ParagraphData with the existing Legacy provenance fields."""

    meta = dict(meta or {})
    if sect_pr is not None:
        meta["sectPr"] = sect_pr
    if features.page_break_before:
        meta["page_break_before"] = True
    meta["legacy_type_id"] = {
        "value": type_id,
        "source": "legacy_importer",
        "recognition_version": recognition_version,
    }
    paragraph = ParagraphData(
        text=clean_text,
        type_id=type_id,
        original_text=line,
        features=features,
        meta=meta,
        inline_tokens=inline_tokens if strict_preservation or clean_text == line else [],
    )
    text_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()[:12]
    logger.info(
        "[识别] #%s type=%s chars=%s text_sha256=%s",
        paragraph_index,
        type_id,
        len(clean_text),
        text_hash,
    )
    return paragraph
