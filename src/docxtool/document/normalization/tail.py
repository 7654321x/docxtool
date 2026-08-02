"""Tail normalization after authoritative recognition.

The functions in this module accept importer paragraph-like objects and only
operate on already recognized tail types.  They preserve the old data shape so
``DocxImporter`` can keep its public compatibility facade.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from docxtool.document.recognition.attachment import (
    match_attachment_item as _recognition_match_attachment_item,
    match_attachment_note as _recognition_match_attachment_note,
)
from docxtool.document.normalization.dates import (
    is_attachment_page_mark as _is_attachment_page_mark_text,
    is_sign_date_text as _is_sign_date_text,
    normalize_attachment_page_mark as _norm_attach_mark,
    normalize_sign_date as _norm_sign_date,
)
from docxtool.document.normalization.signature import normalize_sign_org as _norm_sign_org
from docxtool.document.recognition.colon import contains_colon as _recognition_contains_colon
from docxtool.document.recognition.signature import (
    has_signature_org_shape as _recognition_has_signature_org_shape,
    starts_with_signature_negative as _recognition_starts_with_signature_negative,
)
from docxtool.document.recognition.validators import validate_diagnostics


def _contains_colon(text: str) -> bool:
    """Return whether text contains a Chinese or ASCII colon."""
    return _recognition_contains_colon(text)


def _tail_source_text(paragraph: Any) -> str:
    """Read the stable source text used for tail normalization.

    Input is a paragraph-like object with ``original_text`` and ``text``
    attributes.  The return value is stripped original text when available,
    otherwise stripped current text.
    """
    return (getattr(paragraph, "original_text", "") or getattr(paragraph, "text", "") or "").strip()


def _is_attachment_page_mark(text: str) -> bool:
    """Return whether text is an already recognized attachment-page mark shape."""
    return _is_attachment_page_mark_text(text)


def _is_tail_signature_org_text(text: str) -> bool:
    """Check generic organization-name evidence for a tail signature.

    Input is a short text line near the document tail.  The return value is a
    boolean structural fact; it is not used to retag body paragraphs directly.
    """
    return _recognition_has_signature_org_shape(text, max_length=40)


def _is_tail_structural_text(text: str) -> bool:
    """Return whether text has a tail-structure shape.

    Input is text that lies after a candidate tail date.  The return value is a
    shape check used only to prove the bounded tail region is safe to reorder.
    """
    value = (text or "").strip()
    return bool(
        _recognition_match_attachment_note(value)
        or _recognition_match_attachment_item(value)
        or _is_sign_date_text(value)
        or _is_attachment_page_mark(value)
        or _is_tail_signature_org_text(value)
    )


def _allows_standalone_tail_date(paragraphs: list[Any], index: int) -> bool:
    """Decide whether a recognized date may end the tail without a sign_org.

    Input is the paragraph list and candidate date index.  The return value is
    true only when the previous visible text does not look like an invalid
    label or negative phrase.
    """
    previous = next(
        (
            _tail_source_text(paragraphs[position])
            for position in range(index - 1, -1, -1)
            if _tail_source_text(paragraphs[position])
        ),
        "",
    )
    if not previous or _recognition_starts_with_signature_negative(previous):
        return False
    return not _contains_colon(previous)


def _retag_tail_paragraph(
    paragraph: Any,
    type_id: str,
    text: str,
    meta: Optional[dict] = None,
) -> None:
    """Update a paragraph after recognition-post normalization.

    Input is a paragraph-like object, its final type, replacement display text,
    and optional metadata.  The function returns ``None`` and mutates the
    paragraph while preserving existing metadata and locator fields.
    """
    old_text = getattr(paragraph, "text", "")
    preserved = dict(getattr(paragraph, "meta", None) or {})
    preserved.update(meta or {})
    preserved["final_type"] = type_id
    preserved.setdefault("recognition_type", type_id)
    preserved.setdefault("recognized_type", type_id)
    paragraph.type_id = type_id
    paragraph.text = text
    paragraph.meta = preserved
    if text != old_text:
        paragraph.inline_tokens = []


def _normalize_attachment_note_block(
    note: Any,
    items: list[Any],
    *,
    normalize_text: bool,
) -> None:
    """Normalize an already recognized attachment-note group.

    Input is the attachment-note paragraph, its recognized item paragraphs, and
    the text-normalization switch.  The function returns ``None`` and updates
    the paragraphs in place.
    """
    match = _recognition_match_attachment_note(_tail_source_text(note))
    if match is None:
        return
    body = match.group(1).strip()
    first_number = re.match(r"^(\d+)[.．、]\s*(.*)$", body)
    if items:
        if first_number:
            start = int(first_number.group(1))
            first_body = first_number.group(2).strip()
        else:
            start = 1
            first_body = body
        _retag_tail_paragraph(
            note,
            "attachment_note",
            f"附件：{start}. {first_body}".rstrip() if normalize_text else _tail_source_text(note),
            {"attachment_single": False, "attachment_multi": True},
        )
        for offset, item in enumerate(items, start=1):
            item_body = re.sub(r"^\s*\d+[.．、]\s*", "", _tail_source_text(item), count=1).strip()
            _retag_tail_paragraph(
                item,
                "attachment_note_item",
                f"{start + offset}. {item_body}".rstrip() if normalize_text else _tail_source_text(item),
            )
        return

    if first_number:
        body = first_number.group(2).strip()
    _retag_tail_paragraph(
        note,
        "attachment_note",
        f"附件：{body}".rstrip() if normalize_text else _tail_source_text(note),
        {"attachment_single": True, "attachment_multi": False},
    )


def normalize_tail_structures(
    paragraphs: list[Any],
    *,
    normalize_text: bool = True,
) -> None:
    """Normalize the confirmed document tail after recognition.

    Input is the mutable paragraph list and a text-normalization switch.  The
    function returns ``None``; it can reorder only a fully bounded recognized
    tail and can normalize dates, attachment marks, and attachment numbering.
    """

    plain_indexes = [
        index
        for index, paragraph in enumerate(paragraphs)
        if not paragraph.type_id.startswith("__") and _tail_source_text(paragraph)
    ]
    if not plain_indexes:
        return

    raw_markers = [
        index for index in plain_indexes
        if paragraphs[index].type_id == "attachment_page_mark"
    ]
    raw_notes = [
        index for index in plain_indexes
        if paragraphs[index].type_id == "attachment_note"
    ]
    raw_dates = [
        index for index in plain_indexes
        if paragraphs[index].type_id == "sign_date"
    ]
    first_marker = raw_markers[0] if raw_markers else len(paragraphs)

    tail_date = None
    for index in reversed([value for value in raw_dates if value < first_marker]):
        following = [
            _tail_source_text(paragraphs[position])
            for position in plain_indexes
            if index < position < first_marker
        ]
        has_later_anchor = any(value > index for value in raw_notes + raw_markers)
        if (index == plain_indexes[-1] and _allows_standalone_tail_date(paragraphs, index)) or (
            has_later_anchor and all(_is_tail_structural_text(text) for text in following)
        ):
            tail_date = index
            break

    note_index = None
    for index in raw_notes:
        if index >= first_marker:
            continue
        following_plain = [
            position for position in plain_indexes
            if index < position < first_marker
        ]
        next_is_item = bool(
            following_plain
            and _recognition_match_attachment_item(_tail_source_text(paragraphs[following_plain[0]]))
        )
        near_tail_date = tail_date is not None and abs(index - tail_date) <= 12
        if near_tail_date or next_is_item:
            note_index = index
            break
    item_indexes = []
    if note_index is not None:
        item_indexes = [
            index
            for index in plain_indexes
            if note_index < index < first_marker
            and paragraphs[index].type_id == "attachment_note_item"
        ]

    sign_index = None
    if tail_date is not None:
        sign_candidates = [
            index
            for index in plain_indexes
            if max(0, min(note_index if note_index is not None else tail_date, tail_date) - 4)
            <= index < first_marker
            and index != tail_date
            and paragraphs[index].type_id == "sign_org"
        ]
        if sign_candidates:
            sign_index = min(sign_candidates, key=lambda index: abs(index - tail_date))

    if note_index is not None:
        _normalize_attachment_note_block(
            paragraphs[note_index],
            [paragraphs[index] for index in item_indexes],
            normalize_text=normalize_text,
        )
    if sign_index is not None:
        _retag_tail_paragraph(
            paragraphs[sign_index],
            "sign_org",
            _norm_sign_org(_tail_source_text(paragraphs[sign_index]))
            if normalize_text
            else _tail_source_text(paragraphs[sign_index]),
        )
    if tail_date is not None:
        _retag_tail_paragraph(
            paragraphs[tail_date],
            "sign_date",
            _norm_sign_date(_tail_source_text(paragraphs[tail_date])),
        )

    ordered_indexes = [index for index in [note_index, *item_indexes, sign_index, tail_date] if index is not None]
    if len(ordered_indexes) >= 2:
        region_start = min(ordered_indexes)
        region_end = max(ordered_indexes)
        region_plain = [
            index for index in plain_indexes if region_start <= index <= region_end
        ]
        if set(region_plain) == set(ordered_indexes):
            canonical = []
            if note_index is not None:
                canonical.append(paragraphs[note_index])
                canonical.extend(paragraphs[index] for index in item_indexes)
            if sign_index is not None:
                canonical.append(paragraphs[sign_index])
            if tail_date is not None:
                canonical.append(paragraphs[tail_date])
            paragraphs[region_start:region_end + 1] = canonical

    anchor_seen = False
    attachment_mode = False
    for paragraph in paragraphs:
        source_text = _tail_source_text(paragraph)
        if paragraph.type_id in {"attachment_note", "attachment_note_item", "sign_org", "sign_date"}:
            anchor_seen = True
        if paragraph.type_id.startswith("__") or not source_text:
            continue
        if anchor_seen and paragraph.type_id == "attachment_page_mark":
            _retag_tail_paragraph(
                paragraph,
                "attachment_page_mark",
                _norm_attach_mark(source_text) if normalize_text else source_text,
            )
            attachment_mode = True
            continue
        if not attachment_mode:
            continue
        if paragraph.type_id in {"attachment_title", "attachment_body"}:
            _retag_tail_paragraph(paragraph, paragraph.type_id, source_text)


def _diagnostic_text_hash(paragraph: Any, length: int) -> str:
    """Build the redacted text hash used in recognition diagnostics.

    Input is a paragraph-like object and requested preview length.  The return
    value is a SHA-256 prefix, not document text.
    """
    text = getattr(paragraph, "text", "") or getattr(paragraph, "original_text", "") or ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def sync_recognition_consistency(data: Any) -> None:
    """Synchronize final paragraph metadata and diagnostics.

    Input is a document-like object with ``paragraphs`` and
    ``recognition_diagnostics``.  The function returns ``None`` and keeps
    ``type_id``, paragraph metadata, and diagnostic final types aligned after
    normalization has moved or updated tail paragraphs.
    """
    report = getattr(data, "recognition_diagnostics", None)
    if not isinstance(report, dict):
        return
    diagnostics = report.get("paragraphs")
    if not isinstance(diagnostics, list):
        return
    by_block = {
        item.get("block_index"): dict(item)
        for item in diagnostics
        if isinstance(item, dict) and item.get("block_index") is not None
    }
    refreshed: list[dict] = []
    fallback_index = 0
    preview_length = int(
        (report.get("config") or {}).get("text_preview_length")
        or 12
    )
    for paragraph_index, paragraph in enumerate(data.paragraphs):
        if paragraph.type_id in {"__table__", "__image__", "__letterhead__"}:
            continue
        meta = dict(paragraph.meta or {})
        block_index = meta.get("recognition_block_index")
        old = by_block.get(block_index)
        if old is None and fallback_index < len(diagnostics) and isinstance(diagnostics[fallback_index], dict):
            old = dict(diagnostics[fallback_index])
        fallback_index += 1
        if old is None:
            continue
        meta["final_type"] = paragraph.type_id
        meta.setdefault("recognition_type", paragraph.type_id)
        meta.setdefault("recognized_type", meta.get("recognition_type", paragraph.type_id))
        paragraph.meta = meta
        old.update({
            "paragraph_index": paragraph_index,
            "text_preview": _diagnostic_text_hash(paragraph, preview_length),
            "recognized_type": meta.get("recognized_type", paragraph.type_id),
            "final_type": paragraph.type_id,
            "review_confidence": meta.get("review_confidence", old.get("review_confidence")),
            "review_level": meta.get("review_level", old.get("review_level")),
            "evidence_summary": meta.get("recognition_evidence", old.get("evidence_summary", [])),
            "review_reasons": meta.get("review_reasons", old.get("review_reasons", [])),
            "needs_review": meta.get("review_level", old.get("review_level")) in {"review", "critical_review"},
            "mapping_applied": meta.get("mapping_applied", old.get("mapping_applied")),
            "mapping_failed": meta.get("mapping_failed", old.get("mapping_failed")),
        })
        refreshed.append(old)
    report["paragraphs"] = refreshed
    report["validation"] = validate_diagnostics(report)
    summary = report.get("summary")
    if isinstance(summary, dict):
        summary.update({
            "paragraph_count": len(refreshed),
            "low_confidence_count": sum(
                item.get("review_confidence", 0) < (report.get("config") or {}).get("review_low_score", 0.62)
                for item in refreshed
            ),
            "needs_review_count": sum(bool(item.get("needs_review")) for item in refreshed),
            "unknown_type_fallback_count": sum(item.get("final_type") == "unknown" for item in refreshed),
            "confirmed_count": sum(item.get("review_level") == "confirmed" for item in refreshed),
            "info_count": sum(item.get("review_level") == "info" for item in refreshed),
            "review_count": sum(item.get("review_level") == "review" for item in refreshed),
            "critical_review_count": sum(item.get("review_level") == "critical_review" for item in refreshed),
        })
