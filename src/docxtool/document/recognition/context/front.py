"""Front-matter evidence helpers for document context analysis."""

from __future__ import annotations

import re

from ...role_shape import (
    PERSON_NAME_RE,
    ROLE_HINT_RE,
    has_compact_role_name_shape,
    is_person_name_suffix,
)
from ..features import ParagraphFeatures


_SPEECH_TITLE_RE = re.compile(
    r"^(?:[一二三四五六七八九十]+、)?在[\u4e00-\u9fffA-Za-z0-9（）()、，,.·\-]{3,70}(?:上)?的?讲话$"
)
# Preserve the private compatibility names re-exported by global_context.py.
_ROLE_HINT_RE = ROLE_HINT_RE
_PERSON_NAME_RE = PERSON_NAME_RE
_HEAD_DATE_RE = re.compile(
    r"^[（(]?\s*(?:(?:19|20)\d{2}|[零〇○一二两三四五六七八九]{4})\s*年\s*"
    r"(?:[0-9一二两三四五六七八九十〇○×X]{1,3})\s*月\s*"
    r"(?:[0-9一二两三四五六七八九十〇○×X]{0,3})\s*(?:日|号)"
)
_TITLE_STYLE_NAMES = frozenset({"title", "标题", "subtitle", "副标题"})
_HEADING_STYLE_NAMES = frozenset({"heading1", "标题1", "heading2", "标题2", "heading3", "标题3", "heading4", "标题4"})
_FRONT_SCAN_SOFT_THRESHOLD = 12


def _style_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").casefold())


def _body_like(feature: ParagraphFeatures) -> bool:
    """Return whether a line is strong evidence that prose has begun."""
    if not feature.compact_text or feature.dispatch_number_match or feature.date_match:
        return False
    if feature.recipient_match or feature.key_value_label:
        return True
    if feature.heading_shape_level:
        return False
    if (
        feature.ends_with_sentence_punctuation
        and not feature.is_centered
        and feature.text_length >= 12
    ):
        return True
    return feature.text_length >= 34 and feature.ends_with_sentence_punctuation


def _head_date_line(feature: ParagraphFeatures) -> bool:
    return bool(feature.date_match or _HEAD_DATE_RE.match(feature.compact_text))


def _front_title_anchor(feature: ParagraphFeatures) -> bool:
    if (
        not feature.compact_text
        or feature.dispatch_number_match
        or feature.recipient_match
        or feature.attachment_note_match
        or feature.key_value_label
        or _head_date_line(feature)
        or _body_like(feature)
    ):
        return False
    if _SPEECH_TITLE_RE.fullmatch(feature.compact_text):
        return True
    style = _style_name(feature.style_name)
    return bool(
        style in _TITLE_STYLE_NAMES
        or feature.title_shape_score >= 0.5
        or feature.is_centered
        or (
            feature.text_length <= 50
            and not feature.heading_shape_level
            and not feature.ends_with_sentence_punctuation
        )
    )


def _head_role_name(
    feature: ParagraphFeatures,
    previous: ParagraphFeatures | None = None,
    following: ParagraphFeatures | None = None,
) -> bool:
    """Recognize a front-matter role/name line without using a name list."""
    text = feature.raw_text.strip()
    compact = feature.compact_text
    if (
        not text
        or feature.text_length > 42
        or feature.ends_with_sentence_punctuation
        or any(mark in compact for mark in "：:；;")
    ):
        return False
    # A role and name separated by ordinary or full-width whitespace is the
    # strongest and most common manuscript form.
    spaced_name = re.search(r"[\s　]+([\u4e00-\u9fff·×X]{2,4})$", text)
    has_role_hint = bool(ROLE_HINT_RE.search(compact))
    previous_title_anchor = previous is not None and _front_title_anchor(previous)
    following_metadata = following is not None and (
        _head_date_line(following) or following.recipient_match
    )
    if (
        has_role_hint
        and spaced_name
        and is_person_name_suffix(spaced_name.group(1))
        and (previous_title_anchor or following_metadata)
    ):
        return True
    if (
        PERSON_NAME_RE.fullmatch(compact)
        and previous is not None
        and following is not None
        and previous_title_anchor
        and following_metadata
    ):
        return True
    # Some speech manuscripts omit the space, for example “党组书记、主席张三”.
    # Require a date or salutation immediately after it before accepting this
    # more ambiguous compact form.
    return bool(
        has_role_hint
        and has_compact_role_name_shape(compact)
        and following_metadata
    )


def _title_metadata(
    feature: ParagraphFeatures,
    previous: ParagraphFeatures | None = None,
    following: ParagraphFeatures | None = None,
) -> bool:
    if _head_date_line(feature):
        return True
    return _head_role_name(feature, previous, following)


def _front_semantic_item(feature: ParagraphFeatures) -> bool:
    if not feature.compact_text:
        return False
    return feature.legacy_type_id != "__object_caption__"


def _front_scan_positions(features: list[ParagraphFeatures]) -> tuple[tuple[int, ...], str, bool]:
    positions: list[int] = []
    semantic_count = 0
    hard_cap = min(len(features), 80)
    reason = "document-end"
    soft_threshold_exceeded = False
    for position, item in enumerate(features[:hard_cap]):
        if not _front_semantic_item(item):
            continue
        if semantic_count >= _FRONT_SCAN_SOFT_THRESHOLD:
            soft_threshold_exceeded = True
        if semantic_count > 0 and (
            (_body_like(item) and not item.recipient_match)
            or item.attachment_note_match
            or item.key_value_label
            or item.heading_shape_level
        ):
            reason = "body-boundary"
            break
        positions.append(position)
        semantic_count += 1
    else:
        if len(features) > hard_cap:
            reason = "physical-safety-cap"
    return tuple(positions), reason, soft_threshold_exceeded


def _next_semantic_position(features: list[ParagraphFeatures], start: int) -> int | None:
    for position in range(start, len(features)):
        if _front_semantic_item(features[position]):
            return position
    return None


def _previous_semantic_position(features: list[ParagraphFeatures], start: int) -> int | None:
    for position in range(start, -1, -1):
        if _front_semantic_item(features[position]):
            return position
    return None
