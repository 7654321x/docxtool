"""Tail-structure evidence helpers for document context analysis."""

from __future__ import annotations

import re

from ..features import ParagraphFeatures
from .front import _body_like, _head_date_line


_ATTACHMENT_ITEM_RE = re.compile(r"^\s*\d{1,2}[.．、]\s*\S+")
_ATTACHMENT_PAGE_RE = re.compile(r"^附件\s*[0-9一二三四五六七八九十百千]*$")
_SIGNATURE_NEGATIVE_STARTS = ("以上", "请", "现将", "特此", "有关", "此", "联系人", "联系电话", "责任单位")
_SIGNATURE_ORG_SUFFIX_RE = re.compile(
    r"(?:委员会|工作委员会|人民政府|人民法院|人民检察院|代表大会|"
    r"办公室|街道办事处|领导小组|工作组|党组|党委|政府|政协|人大|"
    r"总工会|专班|小组|集团|公司|协会|学会|商会|医院|学院|学校|"
    r"大学|研究院|研究所|中心|局|厅|部|院|处|科|办|镇|乡)$"
)


def _attachment_note_body(feature: ParagraphFeatures) -> str:
    return re.sub(r"^附件\s*[:：]\s*", "", feature.compact_text, count=1)


def _attachment_item_like(feature: ParagraphFeatures) -> bool:
    return bool(
        _ATTACHMENT_ITEM_RE.match(feature.normalized_text)
        and not feature.key_value_label
    )


def _attachment_page_like(feature: ParagraphFeatures) -> bool:
    return bool(_ATTACHMENT_PAGE_RE.fullmatch(feature.compact_text))


def _signature_date_like(feature: ParagraphFeatures) -> bool:
    return bool(feature.date_match or _head_date_line(feature))


def _signature_org_text(feature: ParagraphFeatures) -> str:
    if feature.heading_shape_level == 1 and feature.content_without_numbering:
        return re.sub(r"\s+", "", feature.content_without_numbering)
    return feature.compact_text


def _signature_org_shape(feature: ParagraphFeatures) -> bool:
    text = _signature_org_text(feature)
    if (
        not text
        or feature.text_length > 30
        or feature.date_match
        or feature.attachment_note_match
        or feature.ends_with_sentence_punctuation
        or any(mark in text for mark in "：:；;。！？")
        or text.startswith(_SIGNATURE_NEGATIVE_STARTS)
    ):
        return False
    return bool(_SIGNATURE_ORG_SUFFIX_RE.search(text))


def _tail_bridge_item(feature: ParagraphFeatures) -> bool:
    return bool(
        feature.attachment_note_match
        or _attachment_item_like(feature)
        or _signature_date_like(feature)
        or _signature_org_shape(feature)
    )


def _all_tail_bridge(features: list[ParagraphFeatures], start: int, end: int) -> bool:
    if start > end:
        return True
    return all(_tail_bridge_item(features[position]) for position in range(start, end + 1))


def _has_previous_body(features: list[ParagraphFeatures], body_start: int | None, position: int) -> bool:
    if body_start is None or position <= body_start:
        return False
    for item in features[body_start:position]:
        if (
            _body_like(item)
            or item.heading_shape_level
        ):
            return True
    return False


def _has_tail_after(features: list[ParagraphFeatures], position: int, *, limit: int = 8) -> bool:
    for item in features[position + 1:position + 1 + limit]:
        if (
            _attachment_item_like(item)
            or _attachment_page_like(item)
            or _signature_date_like(item)
            or _signature_org_shape(item)
        ):
            return True
        if _body_like(item) or item.heading_shape_level:
            return False
    return False
