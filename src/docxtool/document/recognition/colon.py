"""Shared colon-structure evidence for recognition and segmentation.

The analyzer deliberately returns facts instead of final paragraph types.  A
front recipient, body label, salutation, key-value field, or explanatory body
depends on document state and neighbouring paragraphs, so callers combine
these facts with context before making a decision.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


STRUCTURAL_KEY_VALUE_LABELS = frozenset({
    "责任单位", "责任人", "联系人", "联系电话", "联系地址",
    "承办单位", "牵头单位", "配合单位", "时间", "地点",
    "主持", "记录", "出席", "缺席", "列席", "参会", "参加",
    "议题", "议定事项", "会议名称", "会议时间", "会议地点",
})
EMPTY_VALUE_KEY_VALUE_LABELS = frozenset({
    "责任单位", "责任人", "联系人", "联系电话", "联系地址",
    "承办单位", "牵头单位", "配合单位", "时间", "地点",
})
MEETING_KEY_VALUE_LABELS = frozenset({
    "时间", "地点", "主持", "记录", "出席", "缺席", "列席",
    "参会", "参加", "议题", "议定事项", "会议名称", "会议时间", "会议地点",
})
STANDALONE_ADDRESSING_RE = re.compile(
    r"^(?:"
    r"各位[\u4e00-\u9fff、，,]{1,18}"
    r"|同志们"
    r"|(?:尊敬的)?[\u4e00-\u9fff·]{1,6}"
    r"(?:书记|主席|主任|部长|局长|处长|科长|司长|厅长|市长|县长|区长|"
    r"镇长|乡长|院长|校长|政委|组长|队长|秘书长|委员|常委|经理|总监|"
    r"老师|教授|同志|先生|女士)"
    r")[：:！!]$"
)
ORGANIZATION_LABEL_SUFFIX_RE = re.compile(
    r"(?:学院|学校|大学|公司|集团|委员会|政府|办公室|中心|协会|学会|医院|"
    r"研究院|研究所|园区|社区|街道|机关|党委|党组|党支部|团委|工会|商会|"
    r"局|厅|处|科|院|所|乡|镇)$"
)
RECIPIENT_LABEL_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9、，,（）()\s]{2,40}$")
WRAPPING_QUOTE_PAIRS = {
    "“": "”",
    "‘": "’",
    "「": "」",
    "『": "』",
    "《": "》",
    '"': '"',
    "'": "'",
}


@dataclass(frozen=True)
class ColonAnalysis:
    raw_text: str
    normalized_text: str
    has_colon: bool
    separator_index: int | None = None
    separator: str = ""
    label: str = ""
    value: str = ""
    colon_at_end: bool = False
    single_line: bool = True
    label_length: int = 0
    value_length: int = 0
    value_has_sentence_punctuation: bool = False
    value_sentence_like: bool = False
    structural_label: bool = False
    meeting_label: bool = False
    organization_label: bool = False
    standalone_addressing: bool = False
    inline_addressing_body: bool = False
    recipient_candidate: bool = False
    key_value_candidate: bool = False
    body_label_candidate: bool = False
    explanatory_body_candidate: bool = False
    kind: str = "none"


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"[ \t\u00a0]+", " ", value).strip()


def compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def contains_colon(text: str) -> bool:
    """判断文本是否包含中文或英文冒号。

    传入数据是一段可见文本。返回值为布尔值，只提供冒号存在事实，
    不分析标签和值，也不决定最终段落类型。
    """
    return "：" in (text or "") or ":" in (text or "")


def _strip_wrapping_quotes(value: str) -> tuple[str, int]:
    stripped = (value or "").strip()
    if len(stripped) < 2:
        return value or "", 0
    closing = WRAPPING_QUOTE_PAIRS.get(stripped[0])
    if closing is None or stripped[-1] != closing:
        return value or "", 0
    leading_offset = len(value) - len(value.lstrip())
    return stripped[1:-1], leading_offset + 1


def is_standalone_addressing_text(value: str) -> bool:
    return bool(STANDALONE_ADDRESSING_RE.fullmatch(compact_text(value)))


def is_organization_label(value: str) -> bool:
    compact = compact_text(value).rstrip("：:")
    return bool(compact and ORGANIZATION_LABEL_SUFFIX_RE.search(compact))


def analyze_colon_structure(value: str) -> ColonAnalysis:
    """Return colon-related structure facts without assigning a final type."""

    raw = value or ""
    normalized = _normalize(raw)
    single_line = "\n" not in raw and "\r" not in raw
    semantic_raw, semantic_offset = _strip_wrapping_quotes(raw)
    indexes = [index for index, char in enumerate(semantic_raw) if char in ":："]
    if not indexes:
        return ColonAnalysis(
            raw_text=raw,
            normalized_text=normalized,
            has_colon=False,
            single_line=single_line,
            standalone_addressing=is_standalone_addressing_text(raw),
            kind="addressing" if is_standalone_addressing_text(raw) else "none",
        )

    semantic_index = indexes[0]
    index = semantic_offset + semantic_index
    separator = semantic_raw[semantic_index]
    label_raw = semantic_raw[:semantic_index].strip()
    value_raw = semantic_raw[semantic_index + 1:].strip()
    label = compact_text(_normalize(label_raw))
    after = _normalize(value_raw)
    value_compact = compact_text(after)
    colon_at_end = value_compact == ""
    structural_label = label in STRUCTURAL_KEY_VALUE_LABELS
    meeting_label = label in MEETING_KEY_VALUE_LABELS
    organization_label = is_organization_label(label)
    standalone_addressing = is_standalone_addressing_text(f"{label}{separator}")
    inline_addressing_body = bool(
        single_line
        and not colon_at_end
        and standalone_addressing
        and len(value_compact) >= 5
    )
    value_has_sentence_punctuation = any(mark in after for mark in "。！？；;")
    value_sentence_like = bool(
        value_compact
        and (
            value_has_sentence_punctuation
            or len(value_compact) >= 10
        )
    )
    key_value_candidate = bool(
        single_line
        and structural_label
        and (value_compact or label in EMPTY_VALUE_KEY_VALUE_LABELS)
    )
    recipient_candidate = bool(
        single_line
        and colon_at_end
        and not structural_label
        and bool(RECIPIENT_LABEL_RE.fullmatch(label_raw))
    )
    body_label_candidate = bool(single_line and colon_at_end and organization_label)
    explanatory_body_candidate = bool(
        single_line
        and not structural_label
        and not inline_addressing_body
        and bool(value_compact)
        and (
            value_sentence_like
            or organization_label
            or label.endswith(("如下", "如下说明", "情况"))
        )
    )

    if inline_addressing_body:
        kind = "inline_addressing_body"
    elif standalone_addressing and colon_at_end:
        kind = "addressing"
    elif key_value_candidate:
        kind = "key_value"
    elif explanatory_body_candidate:
        kind = "explanatory_body"
    elif body_label_candidate:
        kind = "body_label"
    elif recipient_candidate:
        kind = "recipient_candidate"
    else:
        kind = "ambiguous"

    return ColonAnalysis(
        raw_text=raw,
        normalized_text=normalized,
        has_colon=True,
        separator_index=index,
        separator=separator,
        label=label,
        value=after,
        colon_at_end=colon_at_end,
        single_line=single_line,
        label_length=len(compact_text(label)),
        value_length=len(value_compact),
        value_has_sentence_punctuation=value_has_sentence_punctuation,
        value_sentence_like=value_sentence_like,
        structural_label=structural_label,
        meeting_label=meeting_label,
        organization_label=organization_label,
        standalone_addressing=standalone_addressing,
        inline_addressing_body=inline_addressing_body,
        recipient_candidate=recipient_candidate,
        key_value_candidate=key_value_candidate,
        body_label_candidate=body_label_candidate,
        explanatory_body_candidate=explanatory_body_candidate,
        kind=kind,
    )


__all__ = [
    "ColonAnalysis",
    "EMPTY_VALUE_KEY_VALUE_LABELS",
    "MEETING_KEY_VALUE_LABELS",
    "STRUCTURAL_KEY_VALUE_LABELS",
    "analyze_colon_structure",
    "compact_text",
    "contains_colon",
    "is_organization_label",
    "is_standalone_addressing_text",
]
