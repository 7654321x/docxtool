"""Read-only document-wide evidence for title and heading recognition.

The decoder intentionally works with small per-paragraph candidate sets.  This
module supplies the missing document-level facts before decoding: a bounded
front-matter region, the first body boundary, and numbered heading families.
It never changes paragraph text, ordering, or legacy classifications.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from statistics import median

from .features import ParagraphFeatures


_SPEECH_TITLE_RE = re.compile(
    r"^(?:[一二三四五六七八九十]+、)?在[\u4e00-\u9fffA-Za-z0-9（）()、，,.·\-]{3,70}(?:上)?的?讲话$"
)
_ROLE_HINT_RE = re.compile(
    r"(?:书记|主任|主席|局长|县长|区长|市长|部长|院长|校长|经理|总监|"
    r"工程师|专员|督导员|顾问|秘书长|总会计师|总经济师|同志|代表|委员)"
)
_HEAD_DATE_RE = re.compile(
    r"^[（(]?\s*(?:(?:19|20)\d{2}|[零〇○一二两三四五六七八九]{4})\s*年\s*"
    r"(?:[0-9一二两三四五六七八九十〇○×X]{1,3})\s*月\s*"
    r"(?:[0-9一二两三四五六七八九十〇○×X]{1,3})\s*(?:日|号)"
)
_PERSON_NAME_RE = re.compile(r"[\u4e00-\u9fff·×X]{2,4}$")
_TITLE_STYLE_NAMES = frozenset({"title", "标题", "subtitle", "副标题"})
_HEADING_STYLE_NAMES = frozenset({"heading1", "标题1", "heading2", "标题2", "heading3", "标题3", "heading4", "标题4"})
_TITLE_LEGACY_TYPES = frozenset({"title", "title_cont", "subtitle", "title2"})
_TITLE_META_TYPES = frozenset({"role_name", "author_line", "date_line", "addressing", "meeting_line", "location_line"})
_BODY_LEGACY_TYPES = frozenset({
    "body", "addressing", "responsibility_line", "heading1", "heading1_report",
    "heading2", "heading3", "heading4", "title2", "glossary_item",
    "attachment_body",
})
_ATTACHMENT_ITEM_RE = re.compile(r"^\s*\d{1,2}[.．、]\s*\S+")
_ATTACHMENT_PAGE_RE = re.compile(r"^附件\s*[0-9一二三四五六七八九十百千]*$")
_SIGNATURE_NEGATIVE_STARTS = ("以上", "请", "现将", "特此", "有关", "此", "联系人", "联系电话", "责任单位")
_SIGNATURE_ORG_SUFFIX_RE = re.compile(
    r"(?:委员会|工作委员会|人民政府|人民法院|人民检察院|代表大会|"
    r"办公室|街道办事处|领导小组|工作组|党组|党委|政府|政协|人大|"
    r"总工会|专班|小组|集团|公司|协会|学会|商会|医院|学院|学校|"
    r"大学|研究院|研究所|中心|局|厅|部|院|处|科|办|镇|乡)$"
)
_CIRCLED_ORDINALS = {char: index for index, char in enumerate("①②③④⑤⑥⑦⑧⑨⑩", 1)}
_CN_DIGITS = {
    "零": 0, "〇": 0, "○": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _cn_ordinal(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    total = 0
    for char in text:
        digit = _CN_DIGITS.get(char)
        if digit is None:
            return None
        total = total * 10 + digit
    return total or None


def _numbering_ordinal(feature: ParagraphFeatures) -> int | None:
    prefix = str(feature.numbering_prefix or "").strip()
    if not prefix or prefix.startswith("@"):
        return None
    if prefix in _CIRCLED_ORDINALS:
        return _CIRCLED_ORDINALS[prefix]
    value = re.sub(r"^[（(]\s*|\s*[）)]$", "", prefix)
    value = re.sub(r"[、.．]+$", "", value).strip()
    if value.isdigit():
        return int(value)
    return _cn_ordinal(value)


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


def _head_role_name(feature: ParagraphFeatures, following: ParagraphFeatures | None = None) -> bool:
    """Recognize a front-matter role/name line without using a name list."""
    text = feature.raw_text.strip()
    compact = feature.compact_text
    if (
        not text
        or feature.text_length > 42
        or not _ROLE_HINT_RE.search(compact)
        or feature.ends_with_sentence_punctuation
        or any(mark in compact for mark in "：:；;")
    ):
        return False
    # A role and name separated by ordinary or full-width whitespace is the
    # strongest and most common manuscript form.
    spaced_name = re.search(r"[\s　]+([\u4e00-\u9fff·×X]{2,4})$", text)
    if spaced_name:
        return True
    # Some speech manuscripts omit the space, for example “党组书记、主席张三”.
    # Require a date or salutation immediately after it before accepting this
    # more ambiguous compact form.
    return bool(
        _PERSON_NAME_RE.search(compact)
        and following is not None
        and (_head_date_line(following) or following.recipient_match)
    )


def _title_metadata(feature: ParagraphFeatures, following: ParagraphFeatures | None = None) -> bool:
    legacy = str(feature.legacy_type_id or "")
    if legacy in _TITLE_META_TYPES:
        return True
    if _head_date_line(feature):
        return True
    return _head_role_name(feature, following)


@dataclass(frozen=True)
class HeadingFamily:
    level: int
    positions: tuple[int, ...]
    supported_positions: tuple[int, ...]
    parent_scope: tuple[int, ...] = ()

    @property
    def count(self) -> int:
        return len(self.positions)


@dataclass(frozen=True)
class DocumentContext:
    """Document-wide, index-addressable recognition evidence."""

    front_positions: tuple[int, ...]
    title_scores: tuple[float, ...]
    title_evidence: tuple[tuple[str, ...], ...]
    body_start: int | None
    body_start_reason: str
    front_scan_reason: str
    heading_families: tuple[HeadingFamily, ...]
    heading_evidence: tuple[tuple[str, ...], ...]
    front_metadata_kinds: tuple[str | None, ...]
    attachment_note_evidence: tuple[tuple[str, ...], ...]
    attachment_item_evidence: tuple[tuple[str, ...], ...]
    signature_org_evidence: tuple[tuple[str, ...], ...]

    def title_score(self, position: int) -> float:
        return self.title_scores[position] if 0 <= position < len(self.title_scores) else 0.0

    def title_reasons(self, position: int) -> tuple[str, ...]:
        return self.title_evidence[position] if 0 <= position < len(self.title_evidence) else ()

    def before_body(self, position: int) -> bool:
        return self.body_start is None or position < self.body_start

    def heading_family(self, position: int) -> HeadingFamily | None:
        for family in self.heading_families:
            if position in family.positions:
                return family
        return None

    def heading_reasons(self, position: int) -> tuple[str, ...]:
        return self.heading_evidence[position] if 0 <= position < len(self.heading_evidence) else ()

    def front_metadata_kind(self, position: int) -> str | None:
        return self.front_metadata_kinds[position] if 0 <= position < len(self.front_metadata_kinds) else None

    def attachment_note_reasons(self, position: int) -> tuple[str, ...]:
        return self.attachment_note_evidence[position] if 0 <= position < len(self.attachment_note_evidence) else ()

    def attachment_item_reasons(self, position: int) -> tuple[str, ...]:
        return self.attachment_item_evidence[position] if 0 <= position < len(self.attachment_item_evidence) else ()

    def signature_org_reasons(self, position: int) -> tuple[str, ...]:
        return self.signature_org_evidence[position] if 0 <= position < len(self.signature_org_evidence) else ()

    def diagnostic_summary(self) -> dict:
        return {
            "front_matter_positions": list(self.front_positions),
            "body_start": self.body_start,
            "body_start_reason": self.body_start_reason,
            "front_scan_reason": self.front_scan_reason,
            "heading_families": [
                _family_diagnostic(family)
                for family in self.heading_families
            ],
            "attachment_notes": [
                {"position": position, "evidence": list(evidence)}
                for position, evidence in enumerate(self.attachment_note_evidence)
                if evidence
            ],
            "attachment_note_items": [
                {"position": position, "evidence": list(evidence)}
                for position, evidence in enumerate(self.attachment_item_evidence)
                if evidence
            ],
            "signature_orgs": [
                {"position": position, "evidence": list(evidence)}
                for position, evidence in enumerate(self.signature_org_evidence)
                if evidence
            ],
            "front_metadata": [
                {"position": position, "kind": kind}
                for position, kind in enumerate(self.front_metadata_kinds)
                if kind
            ],
        }


def _family_diagnostic(family: HeadingFamily) -> dict:
    result = {
                    "level": family.level,
                    "count": family.count,
                    "positions": list(family.positions),
                    "supported_count": len(family.supported_positions),
                }
    if family.parent_scope:
        result["parent_scope"] = list(family.parent_scope)
    return result


def _front_semantic_item(feature: ParagraphFeatures) -> bool:
    if not feature.compact_text:
        return False
    return feature.legacy_type_id != "__object_caption__"


def _front_scan_positions(features: list[ParagraphFeatures]) -> tuple[tuple[int, ...], str]:
    positions: list[int] = []
    semantic_count = 0
    hard_cap = min(len(features), 80)
    reason = "document-end"
    for position, item in enumerate(features[:hard_cap]):
        if not _front_semantic_item(item):
            continue
        if semantic_count >= 12:
            reason = "effective-front-budget"
            break
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
    return tuple(positions), reason


def _next_semantic_position(features: list[ParagraphFeatures], start: int) -> int | None:
    for position in range(start, len(features)):
        if _front_semantic_item(features[position]):
            return position
    return None


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


def _signature_org_shape(feature: ParagraphFeatures) -> bool:
    text = feature.compact_text
    if (
        not text
        or feature.text_length > 30
        or feature.heading_shape_level
        or feature.date_match
        or feature.attachment_note_match
        or feature.ends_with_sentence_punctuation
        or any(mark in text for mark in "：:；;。！？")
        or text.startswith(_SIGNATURE_NEGATIVE_STARTS)
    ):
        return False
    return bool(_SIGNATURE_ORG_SUFFIX_RE.search(text))


def _has_previous_body(features: list[ParagraphFeatures], body_start: int | None, position: int) -> bool:
    if body_start is None or position <= body_start:
        return False
    for item in features[body_start:position]:
        if (
            _body_like(item)
            or item.heading_shape_level
            or str(item.legacy_type_id or "") in _BODY_LEGACY_TYPES
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


def analyze_document_context(features: list[ParagraphFeatures]) -> DocumentContext:
    """Build bounded front-matter and sibling-heading evidence for one file."""
    count = len(features)
    if not features:
        return DocumentContext((), (), (), None, "no-visible-paragraph", "no-visible-paragraph", (), (), (), (), (), ())

    body_sizes = [item.weighted_font_size or item.font_size_pt for item in features[3:] if item.weighted_font_size or item.font_size_pt]
    body_size = median(body_sizes) if body_sizes else None
    front_scan_positions, front_scan_reason = _front_scan_positions(features)
    front_scan_rank = {position: rank for rank, position in enumerate(front_scan_positions)}
    title_scores: list[float] = [0.0] * count
    title_reasons: list[tuple[str, ...]] = [()] * count
    front_metadata_kinds: list[str | None] = [None] * count
    front_positions: list[int] = []

    for position in front_scan_positions:
        item = features[position]
        following = features[position + 1] if position + 1 < count else None
        if not item.compact_text or item.dispatch_number_match or item.recipient_match:
            continue
        if _head_date_line(item):
            front_metadata_kinds[position] = "date_line"
            continue
        if _head_role_name(item, following):
            front_metadata_kinds[position] = "role_name"
            continue
        # Existing role/name and date metadata is stronger than title-like
        # visual formatting.  These lines commonly inherit bold, centering and
        # a large font from a copied title block; scoring them as titles lets a
        # later decoder overwrite a reliable document-front structure.
        if _title_metadata(item, following):
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
        if item.legacy_type_id in _TITLE_LEGACY_TYPES:
            score += 0.08
            evidence.append("legacy-title-weak")
        if _SPEECH_TITLE_RE.fullmatch(item.compact_text):
            score = max(score, 0.98)
            evidence.append("opening-speech-title")
        if item.heading_shape_level:
            score -= 0.10
            evidence.append("numbered-heading-competition")
        following_positions = [candidate for candidate in front_scan_positions if candidate > position][:4]
        for following in (features[candidate] for candidate in following_positions):
            if following.dispatch_number_match:
                score += 0.14
                evidence.append("following-dispatch-number")
                continue
            if _title_metadata(following):
                score += 0.20
                evidence.append("following-title-metadata")
                break
            if following.recipient_match:
                score += 0.14
                evidence.append("following-recipient")
                break
            if _body_like(following) or following.heading_shape_level:
                score += 0.10
                evidence.append("following-body-boundary")
                break
        title_scores[position] = min(0.99, max(0.0, score))
        title_reasons[position] = tuple(dict.fromkeys(evidence))

    # Short official titles often carry only position, legacy-title and a
    # following recipient/dispatch signal.  The threshold remains above a
    # style-only line while allowing that common compact form.
    title_positions = [
        index for index, score in enumerate(title_scores)
        if score >= 0.44 and (
            "first-visible-line" in title_reasons[index]
            or any(reason.startswith("following-") for reason in title_reasons[index])
            or "opening-speech-title" in title_reasons[index]
        ) or (
            score >= 0.30
            and "first-visible-line" in title_reasons[index]
            and "legacy-title-weak" in title_reasons[index]
        )
    ]
    if title_positions:
        first_title = min(title_positions)
        front_positions.append(first_title)
        following_front_positions = [position for position in front_scan_positions if position > first_title]
        cursor_index = 0
        while cursor_index < len(following_front_positions):
            cursor = following_front_positions[cursor_index]
            item = features[cursor]
            following = features[cursor + 1] if cursor + 1 < count else None
            if _title_metadata(item, following) or title_scores[cursor] >= 0.48:
                front_positions.append(cursor)
                cursor_index += 1
                continue
            if item.recipient_match:
                front_positions.append(cursor)
                break
            break

    body_start = None
    body_reason = "no-body-boundary"
    recipient_positions = [position for position in front_positions if features[position].recipient_match]
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

    by_family: dict[tuple[int, tuple[int, ...]], list[int]] = {}
    supported: dict[tuple[int, tuple[int, ...]], list[int]] = {}
    heading_reasons: list[tuple[str, ...]] = [()] * count
    active_heading_stack: dict[int, int] = {}
    for position, item in enumerate(features):
        level = item.heading_shape_level
        if level is None:
            continue
        parent_scope = tuple(active_heading_stack.get(parent_level, -1) for parent_level in range(1, level))
        family_key = (level, parent_scope)
        by_family.setdefault(family_key, []).append(position)
        next_item = features[position + 1] if position + 1 < count else None
        if next_item and (_body_like(next_item) or next_item.heading_shape_level is not None):
            supported.setdefault(family_key, []).append(position)
        for reset_level in range(level, 5):
            active_heading_stack.pop(reset_level, None)
        active_heading_stack[level] = position
    families = tuple(
        HeadingFamily(level, tuple(positions), tuple(supported.get(key, ())), parent_scope)
        for key, positions in sorted(by_family.items(), key=lambda item: (item[0][0], item[0][1], item[1][0]))
        for level, parent_scope in (key,)
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
                elif previous_ordinal is None and ordinal > 1:
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
            if next_item and next_item.heading_shape_level and next_item.heading_shape_level > family.level:
                evidence.append("nested-heading-support")
            if body_start is not None and position >= body_start:
                evidence.append("inside-body-region")
            elif family.count >= 2:
                evidence.append("family-establishes-body")
            heading_reasons[position] = tuple(evidence)

    signature_org_reasons: list[tuple[str, ...]] = [()] * count
    for position, item in enumerate(features):
        next_position = _next_semantic_position(features, position + 1)
        next_item = features[next_position] if next_position is not None else None
        if (
            next_item is not None
            and _signature_date_like(next_item)
            and _signature_org_shape(item)
            and _has_previous_body(features, body_start, position)
        ):
            signature_org_reasons[position] = (
                "signature-tail-context",
                "following-date",
                "short-organization-shape",
            )

    attachment_note_reasons: list[tuple[str, ...]] = [()] * count
    attachment_item_reasons: list[tuple[str, ...]] = [()] * count
    active_note = False
    for position, item in enumerate(features):
        if item.attachment_note_match:
            next_position = _next_semantic_position(features, position + 1)
            next_item = features[next_position] if next_position is not None else None
            body = _attachment_note_body(item)
            next_is_item = bool(next_item and _attachment_item_like(next_item))
            has_body = bool(body)
            has_tail = next_is_item or _has_tail_after(features, position)
            if (
                _has_previous_body(features, body_start, position)
                and has_tail
                and (has_body or next_is_item)
            ):
                attachment_note_reasons[position] = (
                    "attachment-tail-context",
                    "inside-body-region",
                    "following-attachment-or-tail",
                )
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
        if item.compact_text and not _attachment_item_like(item):
            active_note = False

    return DocumentContext(
        tuple(front_positions), tuple(title_scores), tuple(title_reasons), body_start,
        body_reason, front_scan_reason, families, tuple(heading_reasons), tuple(front_metadata_kinds),
        tuple(attachment_note_reasons), tuple(attachment_item_reasons), tuple(signature_org_reasons),
    )
