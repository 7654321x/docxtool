"""Front-matter evidence helpers for document context analysis."""

from __future__ import annotations

import re
import unicodedata

from ...role_shape import (
    PERSON_NAME_RE,
    ROLE_HINT_RE,
    is_person_name_suffix,
    parse_role_name_shape,
    person_name_shape_strength,
)
from ...text.front_matter import (
    is_meeting_title_descriptor,
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
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")


def _style_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").casefold())


def _front_visible_text(feature: ParagraphFeatures) -> str:
    return _ZERO_WIDTH_RE.sub("", re.sub(r"\s+", "", feature.compact_text or ""))


def _front_recipient_line(feature: ParagraphFeatures) -> bool:
    return bool(feature.recipient_match or feature.colon_standalone_addressing)


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


def _head_meeting_title_date(
    feature: ParagraphFeatures,
    previous: ParagraphFeatures | None,
    following: ParagraphFeatures | None,
) -> bool:
    """Return whether a front date belongs to a following meeting descriptor."""
    return bool(
        previous is not None
        and following is not None
        and _front_title_anchor(previous)
        and _head_date_line(feature)
        and is_meeting_title_descriptor(following.raw_text)
    )


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
    *,
    within_title_opening_window: bool = False,
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
    previous_title_anchor = previous is not None and _front_title_anchor(previous)
    previous_front_metadata_anchor = previous_title_anchor or bool(
        previous is not None
        and (
            _head_date_line(previous)
            or previous.legacy_type_id in {"date_line", "meeting_title_meta", "author_line", "role_name"}
        )
    )
    following_metadata = following is not None and (
        _head_date_line(following) or _front_recipient_line(following)
    )
    parsed = parse_role_name_shape(text)
    if parsed is not None:
        strength = person_name_shape_strength(parsed[1])
        if strength == "strong" and (previous_title_anchor or following_metadata):
            return True
        if (
            strength == "weak"
            and previous_title_anchor
            and following_metadata
            and feature.is_centered
        ):
            return True
    bare_name_has_punctuation = any(
        unicodedata.category(character).startswith("P")
        for character in compact
    )
    strength = (
        person_name_shape_strength(compact)
        if not bare_name_has_punctuation and is_person_name_suffix(compact)
        else None
    )
    if within_title_opening_window and strength is not None:
        return True
    if previous is not None and following is not None:
        if previous_front_metadata_anchor and following_metadata:
            if strength == "strong":
                return True
            style = _style_name(feature.style_name)
            weak_title_evidence = bool(
                feature.legacy_type_id in {"title", "title_cont"}
                or style in _TITLE_STYLE_NAMES
                or style in _HEADING_STYLE_NAMES
            )
            if (
                strength == "weak"
                and (
                    feature.is_centered
                    and not weak_title_evidence
                )
            ):
                return True
    return False


def _title_metadata(
    feature: ParagraphFeatures,
    previous: ParagraphFeatures | None = None,
    following: ParagraphFeatures | None = None,
    *,
    within_title_opening_window: bool = False,
) -> bool:
    if _head_date_line(feature):
        return True
    return _head_role_name(
        feature,
        previous,
        following,
        within_title_opening_window=within_title_opening_window,
    )


def _front_semantic_item(feature: ParagraphFeatures) -> bool:
    if not _front_visible_text(feature):
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
