"""One shared, non-mutating feature extractor for all providers."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any

from .model import DocumentModeDecision, DocumentMode


DISPATCH_RE = re.compile(r"^(?P<issuer>[\u4e00-\u9fffA-Za-z0-9]{0,16})(?:〔|\[)(?P<year>\d{4})(?:〕|\])\s*(?P<number>\d+)\s*号$")
DATE_RE = re.compile(r"^(?:19|20)\d{2}年\s*\d{1,2}月\s*\d{1,2}日$")
NUMBERING_RE = re.compile(r"^(?P<prefix>(?:[一二三四五六七八九十百千万零〇]{1,5}、|[（(][一二三四五六七八九十百千万零〇]{1,5}[）)]|\d{1,2}[.．、]|[（(]\d{1,2}[）)]|[①②③④⑤⑥⑦⑧⑨⑩]))(?P<body>.*)$")
KEY_VALUE_RE = re.compile(r"^(?P<label>[^:：]{1,24})(?P<separator>[:：])(?P<value>.*)$")
MEETING_LABELS = frozenset({"时间", "地点", "主持", "记录", "出席", "缺席", "列席", "参会", "参加", "议题", "议定事项", "会议名称", "会议时间", "会议地点"})
SOURCE_NOTE_RE = re.compile(r"^(?:来源|注|说明|备注)\s*[:：]")
ATTACHMENT_RE = re.compile(r"^附件\s*(?:[:：]|[0-9一二三四五六七八九十]+)?")
RECIPIENT_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9、，,（）()\s]{2,40}[:：]$")


class BlockKind(str):
    PARAGRAPH = "paragraph"
    TABLE = "table"
    IMAGE = "image"
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
    is_docxtool_style: bool
    previous_visible_block_index: int | None
    next_visible_block_index: int | None


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
        elif type_id in {"__image__", "__object_caption__", "__letterhead__"}:
            kind = BlockKind.IMAGE
        tokens = getattr(paragraph, "inline_tokens", ()) or ()
        has_page_break = any(getattr(token, "kind", "") == "page_break" for token in tokens)
        has_section_break = (getattr(paragraph, "meta", {}) or {}).get("sectPr") is not None
        paragraph_index = index if kind in {BlockKind.PARAGRAPH, BlockKind.EMPTY} else None
        blocks.append(DocumentBlock(index, kind, text, paragraph_index, getattr(pf, "style_name", ""), getattr(pf, "alignment", ""), getattr(pf, "bold", None), getattr(pf, "font_size_pt", None), kind == BlockKind.IMAGE, current_table, False, has_page_break, has_section_break, paragraph))
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
    compact_content = re.sub(r"\s+", "", content)
    level = 1 if prefix and (prefix.endswith("、") and not prefix[0].isdigit()) else 2 if prefix and prefix.startswith(("（", "(")) else 3 if prefix and prefix[0].isdigit() else None
    kv = KEY_VALUE_RE.match(compact_content)
    label = kv.group("label") if kv else None
    value = kv.group("value") if kv else None
    if label and label in MEETING_LABELS:
        kv_level = 0
    else:
        kv_level = level
    dispatch = DISPATCH_RE.fullmatch(compact)
    style = block.style_name or ""
    return ParagraphFeatures(
        block.index, block.paragraph_index if block.paragraph_index is not None else -1,
        raw, normalized, compact, prefix, kv_level, content,
        label if kv else None, value if kv else None, kv.group("separator") if kv else None,
        prefix if kv and label in MEETING_LABELS else None,
        bool(dispatch), dispatch.groupdict() if dispatch else None,
        bool(DATE_RE.fullmatch(compact)), bool(RECIPIENT_RE.fullmatch(normalized)) and not bool(kv),
        bool(ATTACHMENT_RE.match(compact)), bool(len(compact) <= 16 and not re.search(r"[。！？]", compact)),
        bool(SOURCE_NOTE_RE.match(compact)), level,
        0.8 if level and len(content) <= 40 else 0.2,
        0.8 if block.alignment and "CENTER" in str(block.alignment).upper() and len(normalized) <= 50 else 0.1,
        normalized.endswith(("。", "！", "？", ".", "!", "?")), ":" in normalized or "：" in normalized,
        len(compact), bool(block.alignment and "CENTER" in str(block.alignment).upper()), bool(block.bold), block.font_size_pt,
        style, style.startswith("DCT-"),
        previous.index if previous else None, next_block.index if next_block else None,
    )


def detect_mode(features: list[ParagraphFeatures], legacy: str = "") -> DocumentModeDecision:
    texts = [item.compact_text for item in features[:20]]
    joined = " ".join(texts)
    meeting_count = sum(1 for item in features[:40] if item.key_value_label in MEETING_LABELS)
    if any(token in joined for token in ("会议纪要", "党委会纪要", "党组会议纪要", "办公会议纪要", "专题会议纪要", "工作会议纪要", "会议记录")) or meeting_count >= 2 or any("会议认为" in item.compact_text or "会议指出" in item.compact_text for item in features[:40]):
        return DocumentModeDecision(DocumentMode.MEETING_MINUTES, min(0.99, 0.75 + meeting_count * 0.06), ("meeting-title-or-metadata",))
    if "报告" in joined or "工作回顾" in joined:
        return DocumentModeDecision(DocumentMode.REPORT, 0.82, ("report-title",))
    if "通知" in joined:
        return DocumentModeDecision(DocumentMode.NOTICE, 0.8, ("notice-title",))
    if "实施方案" in joined or "工作方案" in joined:
        return DocumentModeDecision(DocumentMode.PLAN, 0.8, ("plan-title",))
    legacy_map = {"NORMAL": DocumentMode.NORMAL, "REPORT": DocumentMode.REPORT}
    return DocumentModeDecision(legacy_map.get(str(legacy).upper(), DocumentMode.UNKNOWN), 0.45, ("legacy-mode",))
