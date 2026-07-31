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
    heading_families: tuple[HeadingFamily, ...]
    heading_evidence: tuple[tuple[str, ...], ...]
    front_metadata_kinds: tuple[str | None, ...]

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

    def diagnostic_summary(self) -> dict:
        return {
            "front_matter_positions": list(self.front_positions),
            "body_start": self.body_start,
            "body_start_reason": self.body_start_reason,
            "heading_families": [
                {
                    "level": family.level,
                    "count": family.count,
                    "positions": list(family.positions),
                    "supported_count": len(family.supported_positions),
                }
                for family in self.heading_families
            ],
            "front_metadata": [
                {"position": position, "kind": kind}
                for position, kind in enumerate(self.front_metadata_kinds)
                if kind
            ],
        }


def analyze_document_context(features: list[ParagraphFeatures]) -> DocumentContext:
    """Build bounded front-matter and sibling-heading evidence for one file."""
    count = len(features)
    if not features:
        return DocumentContext((), (), (), None, "no-visible-paragraph", (), (), ())

    body_sizes = [item.weighted_font_size or item.font_size_pt for item in features[3:] if item.weighted_font_size or item.font_size_pt]
    body_size = median(body_sizes) if body_sizes else None
    front_limit = min(count, 12)
    title_scores: list[float] = [0.0] * count
    title_reasons: list[tuple[str, ...]] = [()] * count
    front_metadata_kinds: list[str | None] = [None] * count
    front_positions: list[int] = []

    for position, item in enumerate(features[:front_limit]):
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
        if position == 0:
            score += 0.13
            evidence.append("first-visible-line")
        elif position < 5:
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
        for following in features[position + 1:min(count, position + 5)]:
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
    title_positions = [index for index, score in enumerate(title_scores) if score >= 0.44]
    if title_positions:
        first_title = min(title_positions)
        front_positions.append(first_title)
        cursor = first_title + 1
        while cursor < front_limit:
            item = features[cursor]
            following = features[cursor + 1] if cursor + 1 < count else None
            if _title_metadata(item, following) or title_scores[cursor] >= 0.48:
                front_positions.append(cursor)
                cursor += 1
                continue
            break

    body_start = None
    body_reason = "no-body-boundary"
    recipient_positions = [position for position in front_positions if features[position].recipient_match]
    if recipient_positions and recipient_positions[-1] + 1 < count:
        body_start = recipient_positions[-1] + 1
        body_reason = "recipient-following-body"
    scan_start = front_positions[-1] + 1 if front_positions else 0
    for position in range(scan_start, count):
        if body_start is not None:
            break
        item = features[position]
        if not item.compact_text:
            continue
        if item.recipient_match:
            body_start, body_reason = position, "recipient"
            break
        if _body_like(item):
            body_start, body_reason = position, "body-paragraph"
            break
        if item.heading_shape_level and (front_positions or position > 0):
            body_start, body_reason = position, "numbered-heading-after-front"
            break
    if body_start is None and not front_positions:
        body_start, body_reason = 0, "no-front-matter"

    by_level: dict[int, list[int]] = {}
    supported: dict[int, list[int]] = {}
    heading_reasons: list[tuple[str, ...]] = [()] * count
    for position, item in enumerate(features):
        level = item.heading_shape_level
        if level is None:
            continue
        by_level.setdefault(level, []).append(position)
        next_item = features[position + 1] if position + 1 < count else None
        if next_item and (_body_like(next_item) or next_item.heading_shape_level is not None):
            supported.setdefault(level, []).append(position)
    families = tuple(
        HeadingFamily(level, tuple(positions), tuple(supported.get(level, ())))
        for level, positions in sorted(by_level.items())
    )
    for family in families:
        for position in family.positions:
            evidence = [f"numbered-heading-level-{family.level}"]
            if family.count >= 2:
                evidence.append("parallel-heading-family")
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

    return DocumentContext(
        tuple(front_positions), tuple(title_scores), tuple(title_reasons), body_start,
        body_reason, families, tuple(heading_reasons), tuple(front_metadata_kinds),
    )
