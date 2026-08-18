"""One shared, non-mutating feature extractor for all providers."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any

from .colon import (
    MEETING_KEY_VALUE_LABELS,
    analyze_colon_structure,
)
from .document_mode import REPORT_DOCUMENT_TITLE_MARKERS
from .model import DocumentModeDecision, DocumentMode


DISPATCH_RE = re.compile(r"^(?P<issuer>[\u4e00-\u9fffA-Za-z0-9]{0,16})(?:〔|\[)(?P<year>\d{4})(?:〕|\])\s*(?P<number>\d+)\s*号$")
DATE_RE = re.compile(r"^(?:19|20)\d{2}年\s*\d{1,2}月\s*\d{1,2}日$")
NUMBERING_RE = re.compile(r"^(?P<prefix>(?:[一二三四五六七八九十百千万零〇]{1,5}[、.．]+|[（(][一二三四五六七八九十百千万零〇]{1,5}[）)]|\d{1,2}[.．、]+|[（(]\d{1,2}[）)]|[①②③④⑤⑥⑦⑧⑨⑩]))(?P<body>.*)$")
MEETING_LABELS = MEETING_KEY_VALUE_LABELS
SOURCE_NOTE_RE = re.compile(r"^(?:来源|注|说明|备注)\s*[:：]")
ATTACHMENT_RE = re.compile(r"^附件\s*[:：]")


class BlockKind(str):
    PARAGRAPH = "paragraph"
    TABLE = "table"
    IMAGE = "image"
    CAPTION = "caption"
    EMPTY = "empty"
    PAGE_BREAK = "page_break"
    SECTION_BREAK = "section_break"


@dataclass(frozen=True)
class DocumentBlock:
    index: int
    kind: str
    text: str = ""
    paragraph_index: int | None = None
    style_name: str = ""
    alignment: str | None = None
    bold: bool | None = None
    font_size_pt: float | None = None
    has_image: bool = False
    table_index: int | None = None
    page_break_before: bool = False
    page_break_after: bool = False
    section_break: bool = False
    raw_reference: object | None = None
    legacy_type_id: str = ""
    dominant_font_name: str = ""
    weighted_font_size: float | None = None
    max_font_size: float | None = None
    min_font_size: float | None = None
    bold_char_ratio: float = 0.0
    italic_char_ratio: float = 0.0
    explicitly_formatted_char_ratio: float = 0.0


@dataclass(frozen=True)
class ParagraphFeatures:
    block_index: int
    paragraph_index: int
    raw_text: str
    normalized_text: str
    compact_text: str
    numbering_prefix: str | None
    numbering_level: int | None
    content_without_numbering: str
    key_value_label: str | None
    key_value_value: str | None
    key_value_separator: str | None
    optional_numbering_before_label: str | None
    dispatch_number_match: bool
    dispatch_number_parts: dict[str, str] | None
    date_match: bool
    recipient_match: bool
    attachment_note_match: bool
    signature_org_match: bool
    source_note_match: bool
    heading_shape_level: int | None
    heading_semantic_score: float
    title_shape_score: float
    ends_with_sentence_punctuation: bool
    contains_colon: bool
    text_length: int
    is_centered: bool
    is_bold: bool
    font_size_pt: float | None
    style_name: str
    legacy_type_id: str
    is_docxtool_style: bool
    previous_visible_block_index: int | None
    next_visible_block_index: int | None
    dominant_font_name: str = ""
    weighted_font_size: float | None = None
    max_font_size: float | None = None
    min_font_size: float | None = None
    bold_char_ratio: float = 0.0
    italic_char_ratio: float = 0.0
    explicitly_formatted_char_ratio: float = 0.0
    colon_kind: str = "none"
    colon_label: str | None = None
    colon_value: str | None = None
    colon_at_end: bool = False
    colon_value_sentence_like: bool = False
    colon_label_organization: bool = False
    colon_standalone_addressing: bool = False
    colon_inline_addressing_body: bool = False
    colon_key_value_candidate: bool = False
    colon_body_label_candidate: bool = False
    colon_explanatory_body: bool = False
    numbered_heading2_colon_inline_body: bool = False
    numbered_heading2_period_inline_body: bool = False
    native_numbering_level: int | None = None
    native_numbering_ordinal: int | None = None
    native_numbering_family: str = ""
    native_numbering_present: bool = False
    native_numbering_template_level: int | None = None
    native_numbering_ilvl: int | None = None
    native_numbering_start: int | None = None
    native_numbering_level_source: str = ""
    native_numbering_body_list: bool = False


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"[ \t\u00a0]+", " ", value).strip()


def _paragraph_blocks(data: Any) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    table_index = 0
    for index, paragraph in enumerate(getattr(data, "paragraphs", ())):
        text = str(getattr(paragraph, "original_text", "") or getattr(paragraph, "text", "") or "")
        pf = getattr(paragraph, "features", None)
        kind = BlockKind.EMPTY if not text.strip() else BlockKind.PARAGRAPH
        type_id = str(getattr(paragraph, "type_id", ""))
        current_table = None
        if type_id == "__table__":
            kind = BlockKind.TABLE
            current_table = table_index
            table_index += 1
        elif type_id in {"__image__", "__letterhead__"}:
            kind = BlockKind.IMAGE
        elif type_id == "__object_caption__":
            kind = BlockKind.CAPTION
        tokens = getattr(paragraph, "inline_tokens", ()) or ()
        has_page_break = any(getattr(token, "kind", "") == "page_break" for token in tokens)
        has_section_break = (getattr(paragraph, "meta", {}) or {}).get("sectPr") is not None
        paragraph_index = index if kind in {BlockKind.PARAGRAPH, BlockKind.EMPTY, BlockKind.CAPTION} else None
        blocks.append(DocumentBlock(
            index=index,
            kind=kind,
            text=text,
            paragraph_index=paragraph_index,
            style_name=getattr(pf, "style_name", ""),
            alignment=getattr(pf, "alignment", ""),
            bold=getattr(pf, "bold", None),
            font_size_pt=getattr(pf, "weighted_font_size", None) or getattr(pf, "font_size_pt", None),
            has_image=kind == BlockKind.IMAGE,
            table_index=current_table,
            page_break_after=has_page_break,
            section_break=has_section_break,
            raw_reference=paragraph,
            legacy_type_id=type_id,
            dominant_font_name=getattr(pf, "dominant_font_name", "") or getattr(pf, "font_name", ""),
            weighted_font_size=getattr(pf, "weighted_font_size", None),
            max_font_size=getattr(pf, "max_font_size", None),
            min_font_size=getattr(pf, "min_font_size", None),
            bold_char_ratio=float(getattr(pf, "bold_char_ratio", 0.0) or 0.0),
            italic_char_ratio=float(getattr(pf, "italic_char_ratio", 0.0) or 0.0),
            explicitly_formatted_char_ratio=float(getattr(pf, "explicitly_formatted_char_ratio", 0.0) or 0.0),
        ))
    return blocks


def extract_blocks(data: Any) -> tuple[DocumentBlock, ...]:
    """Expose stable block objects without dropping tables or image markers."""
    return tuple(_paragraph_blocks(data))


def extract_features(block: DocumentBlock, previous: DocumentBlock | None = None, next_block: DocumentBlock | None = None) -> ParagraphFeatures:
    raw = block.text
    normalized = normalize_text(raw)
    compact = re.sub(r"\s+", "", normalized)
    numbering = NUMBERING_RE.match(normalized)
    prefix = numbering.group("prefix") if numbering else None
    content = numbering.group("body").strip() if numbering else normalized
    level = None
    if prefix:
        if not prefix[0].isdigit() and not prefix.startswith(("（", "(")):
            level = 1
        elif prefix.startswith(("（", "(")):
            inner = prefix[1:-1].strip()
            level = 4 if inner and inner[0].isdigit() else 2
        elif prefix[0].isdigit():
            level = 3
    # A key-value line is a single visible line.  Shared colon analysis keeps
    # explanatory prose such as “主要原因如下：……” out of field-label logic.
    has_line_break = "\n" in raw or "\r" in raw
    colon = analyze_colon_structure(content if not has_line_break else raw)
    label = colon.label if (not has_line_break and colon.key_value_candidate) else None
    value = colon.value if label else None
    if label and colon.meeting_label:
        kv_level = 0
    else:
        kv_level = level
    dispatch = DISPATCH_RE.fullmatch(compact)
    style = block.style_name or ""
    source_features = getattr(block.raw_reference, "features", None)
    native_numbering = getattr(source_features, "native_numbering", None)
    source_numbering_prefix = str(
        getattr(source_features, "numbering_prefix", "") or ""
    )
    from .numbering import native_numbering_heading_level

    native_level = native_numbering_heading_level(native_numbering)
    heading_level = level
    if not (label and colon.meeting_label):
        kv_level = heading_level
    numbered_heading2_colon_inline_body = bool(
        heading_level == 2
        and colon.label
        and not colon.colon_at_end
        and bool(colon.value.strip())
    )
    period_position = normalized.find("。")
    numbered_heading2_period_inline_body = bool(
        (heading_level == 2 or source_numbering_prefix == "@style_heading2")
        and period_position >= 0
        and len(normalized[period_position + 1:].strip()) >= 5
    )
    return ParagraphFeatures(
        block.index, block.paragraph_index if block.paragraph_index is not None else -1,
        raw, normalized, compact, prefix, kv_level, content,
        label, value, colon.separator if label else None,
        prefix if label and colon.meeting_label else None,
        bool(dispatch), dispatch.groupdict() if dispatch else None,
        bool(DATE_RE.fullmatch(compact)), bool(colon.recipient_candidate),
        bool(ATTACHMENT_RE.match(compact)), bool(len(compact) <= 16 and not re.search(r"[。！？]", compact)),
        bool(SOURCE_NOTE_RE.match(compact)), heading_level,
        0.8 if heading_level and len(content) <= 40 else 0.2,
        0.8 if block.alignment and "CENTER" in str(block.alignment).upper() and len(normalized) <= 50 else 0.1,
        normalized.endswith(("。", "！", "？", ".", "!", "?")), ":" in normalized or "：" in normalized,
        len(compact), bool(block.alignment and "CENTER" in str(block.alignment).upper()), block.bold_char_ratio >= 0.5 if block.bold_char_ratio else bool(block.bold), block.weighted_font_size or block.font_size_pt,
        style, block.legacy_type_id, style.startswith("DCT-"),
        previous.index if previous else None, next_block.index if next_block else None,
        block.dominant_font_name, block.weighted_font_size, block.max_font_size,
        block.min_font_size, block.bold_char_ratio, block.italic_char_ratio,
        block.explicitly_formatted_char_ratio,
        colon.kind, colon.label or None, colon.value or None, colon.colon_at_end,
        colon.value_sentence_like, colon.organization_label,
        colon.standalone_addressing, colon.inline_addressing_body,
        colon.key_value_candidate, colon.body_label_candidate,
        colon.explanatory_body_candidate,
        numbered_heading2_colon_inline_body,
        numbered_heading2_period_inline_body,
        None,
        getattr(native_numbering, "ordinal", None),
        str(getattr(native_numbering, "family_id", "") or ""),
        native_numbering is not None,
        native_level,
        getattr(native_numbering, "ilvl", None),
        (
            getattr(native_numbering, "effective_start", None)
            if native_numbering is not None
            else None
        ),
        "",
        False,
    )


def detect_mode(features: list[ParagraphFeatures]) -> DocumentModeDecision:
    visible = [item for item in features if item.compact_text]
    meeting_count = sum(1 for item in features[:40] if item.key_value_label in MEETING_LABELS)
    title_region = visible[:8]
    body_sizes = sorted(item.weighted_font_size or item.font_size_pt for item in visible[3:] if (item.weighted_font_size or item.font_size_pt))
    body_size = body_sizes[len(body_sizes) // 2] if body_sizes else None

    def title_evidence(item: ParagraphFeatures, index: int) -> tuple[str, ...]:
        evidence = ["front-position"] if index < 5 else []
        style = re.sub(r"\s+", " ", item.style_name.strip().casefold())
        if style in {"title", "标题", "subtitle", "副标题"}:
            evidence.append("title-style")
        if item.is_centered:
            evidence.append("centered")
        if item.bold_char_ratio >= 0.5 or item.is_bold:
            evidence.append("bold-majority")
        size = item.weighted_font_size or item.font_size_pt
        if size and body_size and size >= body_size + 1:
            evidence.append("larger-than-body")
        if 4 <= item.text_length <= 60:
            evidence.append("title-length")
        return tuple(evidence)

    meeting_titles = ("会议纪要", "党委会纪要", "党组会议纪要", "办公会议纪要", "专题会议纪要", "工作会议纪要", "会议记录")
    for index, item in enumerate(title_region):
        evidence = title_evidence(item, index)
        strong = {
            "title-style", "centered",
            "bold-majority", "larger-than-body",
        }.intersection(evidence)
        if item.compact_text.endswith(meeting_titles) and (len(evidence) >= 3 and strong or index == 0 and "title-length" in evidence):
            return DocumentModeDecision(DocumentMode.MEETING_MINUTES, min(0.99, 0.72 + meeting_count * 0.06), evidence + ("meeting-title-suffix",))
    if meeting_count >= 2:
        return DocumentModeDecision(DocumentMode.MEETING_MINUTES, min(0.99, 0.75 + meeting_count * 0.06), ("meeting-title-or-metadata",))
    suffixes = (
        (DocumentMode.REPORT, REPORT_DOCUMENT_TITLE_MARKERS, "report-title-suffix"),
        (DocumentMode.NOTICE, ("通知",), "notice-title-suffix"),
        (DocumentMode.PLAN, ("实施方案", "工作方案"), "plan-title-suffix"),
    )
    for index, item in enumerate(title_region):
        evidence = title_evidence(item, index)
        strong = {
            "title-style", "centered",
            "bold-majority", "larger-than-body",
        }.intersection(evidence)
        for mode, endings, reason in suffixes:
            if item.compact_text.endswith(endings) and len(evidence) >= 3 and strong:
                return DocumentModeDecision(mode, min(0.95, 0.55 + len(evidence) * 0.07), evidence + (reason,))
    return DocumentModeDecision(DocumentMode.UNKNOWN, 0.25, ("insufficient-title-evidence",))
