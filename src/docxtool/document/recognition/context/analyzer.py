"""Read-only document-wide evidence for title and heading recognition.

The decoder intentionally works with small per-paragraph candidate sets.  This
module supplies the missing document-level facts before decoding: a bounded
front-matter region, the first body boundary, and numbered heading families.
It never changes paragraph text, ordering, or legacy classifications.
"""

from __future__ import annotations

import re
from statistics import median

from ..features import ParagraphFeatures
from ...text.front_matter import is_meeting_title_descriptor
from .front import (
    _FRONT_SCAN_SOFT_THRESHOLD,
    _SPEECH_TITLE_RE,
    _TITLE_STYLE_NAMES,
    _body_like,
    _front_scan_positions,
    _front_semantic_item,
    _front_recipient_line,
    _head_date_line,
    _head_meeting_title_date,
    _head_role_name,
    _next_semantic_position,
    _previous_semantic_position,
    _style_name,
    _title_metadata,
)
from .model import DocumentContext, HeadingFamily
from .numbering import _numbering_ordinal
from .tail import (
    _SIGNATURE_NEGATIVE_STARTS,
    _all_tail_bridge,
    _attachment_item_like,
    _attachment_note_body,
    _attachment_page_like,
    _has_previous_body,
    _has_tail_after,
    _signature_date_like,
    _signature_org_shape,
    _tail_bridge_item,
)


_DOCUMENT_TYPE_TITLE_SUFFIX_RE = re.compile(
    r"(?:决议|决定|命令|公报|公告|通告|意见|通知|通报|报告|请示|批复|议案|函|纪要|令|汇报)"
    r"(?:[（(][^（）()]{1,12}[）)])?$"
)
_DOCUMENT_TYPE_FRONT_VISIBLE_LIMIT = 5
_PRE_RECIPIENT_TITLE_VISIBLE_LIMIT = 3
_FRONT_TITLE_VISIBLE_LIMIT = 3
_BODY_FIRST_HEADING_LOOKAHEAD = 4


def _context_heading_level(item: ParagraphFeatures) -> int | None:
    """Return the canonical heading level used by hierarchy analysis."""
    if item.heading_shape_level is not None:
        return item.heading_shape_level
    return item.native_numbering_level


def _document_type_title_suffix(item: ParagraphFeatures) -> bool:
    """Return whether a short front line ends with a bounded document type."""
    return bool(
        4 <= item.text_length <= 60
        and not item.dispatch_number_match
        and not item.date_match
        and not item.recipient_match
        and not item.key_value_label
        and not item.attachment_note_match
        and not item.heading_shape_level
        and not item.ends_with_sentence_punctuation
        and not any(mark in item.compact_text for mark in "：:；;")
        and _DOCUMENT_TYPE_TITLE_SUFFIX_RE.search(item.compact_text)
    )


def _front_titles_before_body_and_first_heading(
    features: list[ParagraphFeatures],
) -> set[int]:
    """Find bounded front title lines supported by prose and a first heading."""
    semantic_positions = [
        position for position, item in enumerate(features) if _front_semantic_item(item)
    ]
    body_rank = next(
        (
            rank
            for rank, position in enumerate(semantic_positions)
            if _body_like(features[position])
            and not features[position].recipient_match
            and not features[position].key_value_label
        ),
        None,
    )
    if body_rank is None or not 0 < body_rank <= _FRONT_TITLE_VISIBLE_LIMIT:
        return set()

    first_heading_level = next(
        (
            features[position].heading_shape_level
            for position in semantic_positions[
                body_rank + 1 : body_rank + 1 + _BODY_FIRST_HEADING_LOOKAHEAD
            ]
            if features[position].heading_shape_level is not None
        ),
        None,
    )
    if first_heading_level != 1:
        return set()

    return {
        position
        for position in semantic_positions[:body_rank]
        if 4 <= features[position].text_length <= 60
        and not features[position].dispatch_number_match
        and not features[position].date_match
        and not _front_recipient_line(features[position])
        and not features[position].key_value_label
        and not features[position].attachment_note_match
        and not features[position].heading_shape_level
        and not features[position].ends_with_sentence_punctuation
        and not any(mark in features[position].compact_text for mark in "：:；;")
    }


def analyze_document_context(features: list[ParagraphFeatures]) -> DocumentContext:
    """Build bounded front-matter and sibling-heading evidence for one file."""
    count = len(features)
    if not features:
        return DocumentContext(
            (),
            (),
            (),
            None,
            "no-visible-paragraph",
            "no-visible-paragraph",
            False,
            _FRONT_SCAN_SOFT_THRESHOLD,
            (),
            (),
            (),
            (),
            (),
            (),
            (),
        )

    body_sizes = [
        item.weighted_font_size or item.font_size_pt
        for item in features[3:]
        if item.weighted_font_size or item.font_size_pt
    ]
    body_size = median(body_sizes) if body_sizes else None
    front_scan_positions, front_scan_reason, front_soft_threshold_exceeded = _front_scan_positions(
        features
    )
    front_scan_rank = {position: rank for rank, position in enumerate(front_scan_positions)}
    document_type_title_positions = {
        position
        for position in front_scan_positions[:_DOCUMENT_TYPE_FRONT_VISIBLE_LIMIT]
        if _document_type_title_suffix(features[position])
    }
    body_first_heading_title_positions = _front_titles_before_body_and_first_heading(features)
    title_scores: list[float] = [0.0] * count
    title_reasons: list[tuple[str, ...]] = [()] * count
    front_metadata_kinds: list[str | None] = [None] * count
    front_positions: list[int] = []

    for position in front_scan_positions:
        item = features[position]
        following_position = _next_semantic_position(features, position + 1)
        following = features[following_position] if following_position is not None else None
        previous_position = _previous_semantic_position(features, position - 1)
        previous = features[previous_position] if previous_position is not None else None
        if not item.compact_text or item.dispatch_number_match or item.recipient_match:
            continue
        if _head_meeting_title_date(item, previous, following):
            front_metadata_kinds[position] = "meeting_title_meta"
            continue
        if (
            previous_position is not None
            and front_metadata_kinds[previous_position] == "meeting_title_meta"
            and is_meeting_title_descriptor(item.raw_text)
        ):
            front_metadata_kinds[position] = "meeting_title_meta"
            continue
        if _head_date_line(item):
            front_metadata_kinds[position] = "date_line"
            continue
        if _head_role_name(item, previous, following):
            front_metadata_kinds[position] = "role_name"
            continue
        # Existing role/name and date metadata is stronger than title-like
        # visual formatting.  These lines commonly inherit bold, centering and
        # a large font from a copied title block; scoring them as titles lets a
        # later decoder overwrite a reliable document-front structure.
        if _title_metadata(item, previous, following):
            continue
        if item.attachment_note_match or item.key_value_label or _body_like(item):
            continue
        score = 0.12
        evidence: list[str] = ["front-position"]
        if front_scan_rank.get(position) == 0:
            score += 0.13
            evidence.append("first-visible-line")
        elif front_scan_rank.get(position, 99) < 5:
            score += 0.08
        if position in document_type_title_positions:
            score += 0.24
            evidence.append("document-type-title-suffix")
        current_rank = front_scan_rank.get(position, 99)
        if any(
            0 < front_scan_rank[candidate] - current_rank <= 2
            for candidate in document_type_title_positions
        ):
            score += 0.18
            evidence.append("following-document-type-title")
        if position in body_first_heading_title_positions:
            score += 0.28
            evidence.append("following-body-first-heading")
        if item.is_centered:
            score += 0.18
            evidence.append("centered")
        if item.title_shape_score >= 0.5:
            score += 0.16
            evidence.append("title-shape")
        if item.bold_char_ratio >= 0.5 or item.is_bold:
            score += 0.07
            evidence.append("bold-majority")
        size = item.weighted_font_size or item.font_size_pt
        if body_size and size and size >= body_size + 1:
            score += 0.12
            evidence.append("larger-than-body")
        style = _style_name(item.style_name)
        if style in _TITLE_STYLE_NAMES:
            score += 0.08
            evidence.append("title-style-weak")
        if _SPEECH_TITLE_RE.fullmatch(item.compact_text):
            score = max(score, 0.98)
            evidence.append("opening-speech-title")
        if item.heading_shape_level:
            score -= 0.10
            evidence.append("numbered-heading-competition")
        following_positions = [
            candidate for candidate in front_scan_positions if candidate > position
        ][:4]
        for candidate in following_positions:
            following = features[candidate]
            following_next_position = _next_semantic_position(features, candidate + 1)
            following_next = (
                features[following_next_position]
                if following_next_position is not None
                else None
            )
            if following.dispatch_number_match:
                score += 0.14
                evidence.append("following-dispatch-number")
                continue
            if _title_metadata(following, item, following_next):
                score += 0.20
                evidence.append("following-title-metadata")
                break
            if following.recipient_match:
                score += 0.14
                evidence.append("following-recipient")
                if current_rank < _PRE_RECIPIENT_TITLE_VISIBLE_LIMIT:
                    score += 0.14
                    evidence.append("pre-recipient-title-context")
                break
            if _body_like(following) or following.heading_shape_level:
                score += 0.10
                evidence.append("following-body-boundary")
                break
        if front_scan_rank.get(position, 0) >= _FRONT_SCAN_SOFT_THRESHOLD:
            evidence.append("front-soft-threshold-exceeded")
            if not any(
                reason in evidence
                for reason in (
                    "following-dispatch-number",
                    "following-title-metadata",
                    "following-recipient",
                    "opening-speech-title",
                )
            ):
                score -= 0.20
        title_scores[position] = min(0.99, max(0.0, score))
        title_reasons[position] = tuple(dict.fromkeys(evidence))

    # Short official titles often carry only position, legacy-title and a
    # following recipient/dispatch signal.  The threshold remains above a
    # style-only line while allowing that common compact form.
    title_positions = [
        index
        for index, score in enumerate(title_scores)
        if score >= 0.44
        and (
            "first-visible-line" in title_reasons[index]
            or any(reason.startswith("following-") for reason in title_reasons[index])
            or "opening-speech-title" in title_reasons[index]
        )
    ]
    if title_positions:
        first_title = min(title_positions)
        front_positions.append(first_title)
        following_front_positions = [
            position for position in front_scan_positions if position > first_title
        ]
        cursor_index = 0
        while cursor_index < len(following_front_positions):
            cursor = following_front_positions[cursor_index]
            item = features[cursor]
            following_position = _next_semantic_position(features, cursor + 1)
            following = features[following_position] if following_position is not None else None
            previous_position = _previous_semantic_position(features, cursor - 1)
            previous = features[previous_position] if previous_position is not None else None
            if _title_metadata(item, previous, following) or title_scores[cursor] >= 0.48:
                front_positions.append(cursor)
                cursor_index += 1
                continue
            if item.recipient_match:
                front_positions.append(cursor)
                break
            break

    body_start = None
    body_reason = "no-body-boundary"
    recipient_positions = [
        position for position in front_positions if features[position].recipient_match
    ]
    if recipient_positions:
        next_position = _next_semantic_position(features, recipient_positions[-1] + 1)
        if next_position is not None:
            body_start = next_position
        elif recipient_positions[-1] + 1 < count:
            body_start = recipient_positions[-1] + 1
        else:
            body_start = recipient_positions[-1]
        body_reason = "recipient-following-body"
    scan_start = front_positions[-1] + 1 if front_positions else 0
    for position in range(scan_start, count):
        if body_start is not None:
            break
        item = features[position]
        if not item.compact_text:
            continue
        if item.recipient_match:
            body_start = position + 1 if position + 1 < count else position
            body_reason = "recipient-following-body" if body_start != position else "recipient"
            break
        if _body_like(item):
            body_start, body_reason = position, "body-paragraph"
            break
        if item.heading_shape_level and (front_positions or position > 0):
            body_start, body_reason = position, "numbered-heading-after-front"
            break
    if body_start is None and not front_positions:
        body_start, body_reason = 0, "no-front-matter"

    by_family: dict[tuple[int, tuple[int, ...], str], list[int]] = {}
    supported: dict[tuple[int, tuple[int, ...], str], list[int]] = {}
    heading_reasons: list[tuple[str, ...]] = [()] * count
    active_heading_stack: dict[int, int] = {}
    for position, item in enumerate(features):
        level = _context_heading_level(item)
        if level is None:
            continue
        parent_scope = tuple(
            active_heading_stack.get(parent_level, -1) for parent_level in range(1, level)
        )
        source_family = item.native_numbering_family
        family_key = (level, parent_scope, source_family)
        by_family.setdefault(family_key, []).append(position)
        next_item = features[position + 1] if position + 1 < count else None
        if next_item and (
            _body_like(next_item) or _context_heading_level(next_item) is not None
        ):
            supported.setdefault(family_key, []).append(position)
        for reset_level in range(level, 5):
            active_heading_stack.pop(reset_level, None)
        active_heading_stack[level] = position
    families = tuple(
        HeadingFamily(
            level,
            tuple(positions),
            tuple(supported.get(key, ())),
            parent_scope,
            source_family,
        )
        for key, positions in sorted(
            by_family.items(),
            key=lambda item: (item[0][0], item[0][1], item[0][2], item[1][0]),
        )
        for level, parent_scope, source_family in (key,)
    )
    for family in families:
        previous_ordinal = None
        seen_ordinals: dict[int, int] = {}
        for position in family.positions:
            evidence = [f"numbered-heading-level-{family.level}"]
            ordinal = _numbering_ordinal(features[position])
            if ordinal is not None:
                if ordinal in seen_ordinals:
                    evidence.append("numbering-duplicate")
                elif (
                    previous_ordinal is None
                    and ordinal
                    != (features[position].native_numbering_start or 1)
                ):
                    evidence.append("numbering-starts-after-one")
                elif previous_ordinal is not None and ordinal < previous_ordinal:
                    evidence.append("numbering-reverse")
                elif previous_ordinal is not None and ordinal > previous_ordinal + 1:
                    evidence.append("numbering-gap")
                seen_ordinals[ordinal] = position
                previous_ordinal = ordinal
            if family.level > 1:
                if len(family.parent_scope) < family.level - 1 or family.parent_scope[-1] < 0:
                    evidence.append("missing-parent-heading")
            if family.count >= 2:
                evidence.append("parallel-heading-family")
            if family.parent_scope:
                evidence.append("parent-scope")
            if position in family.supported_positions:
                evidence.append("following-body-or-heading")
            next_item = features[position + 1] if position + 1 < count else None
            next_level = _context_heading_level(next_item) if next_item else None
            if (
                next_level is not None
                and next_level > family.level
            ):
                evidence.append("nested-heading-support")
            if body_start is not None and position >= body_start:
                evidence.append("inside-body-region")
            elif family.count >= 2:
                evidence.append("family-establishes-body")
            heading_reasons[position] = tuple(evidence)

    signature_org_reasons: list[tuple[str, ...]] = [()] * count
    for position, item in enumerate(features):
        if not (_signature_org_shape(item) and _has_previous_body(features, body_start, position)):
            continue
        date_position = None
        date_direction = "following-date"
        for candidate in range(position + 1, min(count, position + 9)):
            if not _front_semantic_item(features[candidate]):
                continue
            if _signature_date_like(features[candidate]) and _all_tail_bridge(
                features, position + 1, candidate - 1
            ):
                date_position = candidate
                break
            if not _tail_bridge_item(features[candidate]):
                break
        if date_position is None:
            for candidate in range(position - 1, max(-1, position - 9), -1):
                if not _front_semantic_item(features[candidate]):
                    continue
                if _signature_date_like(features[candidate]) and _all_tail_bridge(
                    features, candidate + 1, position - 1
                ):
                    date_position = candidate
                    date_direction = "previous-date"
                    break
                if not _tail_bridge_item(features[candidate]):
                    break
        if date_position is not None:
            signature_org_reasons[position] = (
                "signature-tail-context",
                date_direction,
                "short-organization-shape",
            )

    signature_date_reasons: list[tuple[str, ...]] = [()] * count
    for position, item in enumerate(features):
        if not (_signature_date_like(item) and _has_previous_body(features, body_start, position)):
            continue
        org_position = None
        org_direction = "previous-signature-org"
        tail_boundary = ""
        for candidate in range(position - 1, max(-1, position - 9), -1):
            if not _front_semantic_item(features[candidate]):
                continue
            if _signature_org_shape(features[candidate]) and _all_tail_bridge(
                features, candidate + 1, position - 1
            ):
                org_position = candidate
                break
            if not _tail_bridge_item(features[candidate]):
                break
        if org_position is None:
            for candidate in range(position + 1, min(count, position + 9)):
                if not _front_semantic_item(features[candidate]):
                    continue
                if _signature_org_shape(features[candidate]) and _all_tail_bridge(
                    features, position + 1, candidate - 1
                ):
                    org_position = candidate
                    org_direction = "following-signature-org"
                    break
                if not _tail_bridge_item(features[candidate]):
                    break
        if org_position is not None:
            signature_date_reasons[position] = (
                "signature-tail-context",
                "date-shape",
                org_direction,
            )
            continue
        next_position = _next_semantic_position(features, position + 1)
        if next_position is None:
            previous_position = _previous_semantic_position(features, position - 1)
            previous_item = features[previous_position] if previous_position is not None else None
            previous_supports_tail_date = bool(
                previous_item is not None
                and not previous_item.key_value_label
                and not previous_item.compact_text.startswith(_SIGNATURE_NEGATIVE_STARTS)
                and (
                    _body_like(previous_item)
                    or previous_item.heading_shape_level
                    or previous_item.attachment_note_match
                    or _attachment_item_like(previous_item)
                )
            )
            if previous_supports_tail_date:
                tail_boundary = "document-tail-date"
        else:
            for candidate in range(position + 1, min(count, position + 9)):
                if not _front_semantic_item(features[candidate]):
                    continue
                candidate_item = features[candidate]
                if _attachment_page_like(candidate_item) and _all_tail_bridge(
                    features, position + 1, candidate - 1
                ):
                    tail_boundary = "following-attachment-page"
                    break
                if (
                    candidate_item.attachment_note_match
                    and _all_tail_bridge(features, position + 1, candidate - 1)
                    and (
                        _attachment_note_body(candidate_item)
                        or _has_tail_after(features, candidate)
                    )
                ):
                    tail_boundary = "following-attachment-note"
                    break
                if not _tail_bridge_item(candidate_item):
                    break
        if tail_boundary:
            signature_date_reasons[position] = (
                "signature-tail-context",
                "date-shape",
                tail_boundary,
            )

    attachment_note_reasons: list[tuple[str, ...]] = [()] * count
    attachment_item_reasons: list[tuple[str, ...]] = [()] * count
    active_note = False
    for position, item in enumerate(features):
        if item.attachment_note_match:
            next_position = _next_semantic_position(features, position + 1)
            next_item = features[next_position] if next_position is not None else None
            previous_position = _previous_semantic_position(features, position - 1)
            previous_item = features[previous_position] if previous_position is not None else None
            body = _attachment_note_body(item)
            next_is_item = bool(next_item and _attachment_item_like(next_item))
            previous_signature_tail = bool(
                previous_item is not None
                and (_signature_date_like(previous_item) or _signature_org_shape(previous_item))
            )
            has_body = bool(body)
            has_tail = (
                next_is_item or _has_tail_after(features, position) or previous_signature_tail
            )
            if (
                _has_previous_body(features, body_start, position)
                and has_tail
                and (has_body or next_is_item)
            ):
                evidence = [
                    "attachment-tail-context",
                    "inside-body-region",
                ]
                if previous_signature_tail:
                    evidence.append("near-signature-tail")
                if next_is_item or _has_tail_after(features, position):
                    evidence.append("following-attachment-or-tail")
                attachment_note_reasons[position] = tuple(evidence)
                active_note = True
            else:
                active_note = False
            continue
        if active_note and _attachment_item_like(item):
            attachment_item_reasons[position] = (
                "attachment-note-item-context",
                "previous-attachment-note",
            )
            continue
        if _attachment_item_like(item):
            note_position = None
            for candidate in range(position - 1, max(-1, position - 12), -1):
                if not _front_semantic_item(features[candidate]):
                    continue
                if features[candidate].attachment_note_match and _all_tail_bridge(
                    features, candidate + 1, position - 1
                ):
                    note_position = candidate
                    break
                if not _tail_bridge_item(features[candidate]):
                    break
            if note_position is not None:
                attachment_item_reasons[position] = (
                    "attachment-note-item-context",
                    "previous-attachment-note",
                    "tail-structure-bridge",
                )
                continue
        if item.compact_text and not _attachment_item_like(item):
            active_note = False

    return DocumentContext(
        tuple(front_positions),
        tuple(title_scores),
        tuple(title_reasons),
        body_start,
        body_reason,
        front_scan_reason,
        front_soft_threshold_exceeded,
        _FRONT_SCAN_SOFT_THRESHOLD,
        families,
        tuple(heading_reasons),
        tuple(front_metadata_kinds),
        tuple(attachment_note_reasons),
        tuple(attachment_item_reasons),
        tuple(signature_date_reasons),
        tuple(signature_org_reasons),
    )
