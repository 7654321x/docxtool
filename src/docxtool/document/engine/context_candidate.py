"""Independent local-context candidates built from importer facts only."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Iterable

from docx.oxml.ns import qn

from docxtool.document.engine.document_structure import ElementKind


_DATE_RE = re.compile(r"^(?:19|20)\d{2}年\d{1,2}月\d{1,2}日$")
_ATTACHMENT_NOTE_RE = re.compile(r"^附件\s*[:：]\s*\S+")
_ATTACHMENT_TITLE_RE = re.compile(r"^附件\s*(?:[:：]\s*)?[0-9一二三四五六七八九十]+\s*[:：]?$")
_HEADING_PATTERNS = (
    (ElementKind.HEADING_1, re.compile(r"^[一二三四五六七八九十]+、")),
    (ElementKind.HEADING_2, re.compile(r"^[（(][一二三四五六七八九十]+[）)]")),
    (ElementKind.HEADING_3, re.compile(r"^\d+[.．、]")),
    (ElementKind.HEADING_4, re.compile(r"^[（(]\d+[）)]")),
)
_BODY_TYPES = {"body", "addressing", "responsibility_line", "attachment_body"}
_TITLE_TYPES = {"title", "title_cont"}
_TITLE_META_TYPES = {"author_line", "role_name", "date_line", "title2", "meeting_line", "location_line"}
_SIGN_TYPES = {"sign_org", "sign_date", "note", "annotation"}


@dataclass(frozen=True)
class ContextEvidence:
    source: str
    detail: str
    weight: float


@dataclass(frozen=True)
class RawElementFacts:
    index: int
    source_index: int | None
    type_id: str | None
    text: str
    style_name: str
    alignment: str
    classification_confidence: float
    physical_kind: str
    text_fingerprint: str
    style_fingerprint: str
    node_identity: int | None


@dataclass(frozen=True)
class ContextCandidate:
    index: int
    kind: ElementKind
    confidence: float
    evidence: tuple[ContextEvidence, ...]
    original_type_id: str | None
    text_fingerprint: str
    style_fingerprint: str


def build_raw_element_facts(paragraphs: Iterable) -> tuple[RawElementFacts, ...]:
    """Build an index-compatible fact stream without using DocumentStructure."""

    facts = []
    for source_index, paragraph in enumerate(paragraphs):
        if _page_break_before(paragraph) or _inline_page_break(paragraph):
            facts.append(_virtual_page_fact(len(facts), source_index))
        facts.append(_paragraph_fact(len(facts), source_index, paragraph))
        if (getattr(paragraph, "meta", {}) or {}).get("sectPr") is not None:
            facts.append(_virtual_page_fact(len(facts), source_index))
    return tuple(facts)


def classify_context_candidate(
    facts: tuple[RawElementFacts, ...],
    index: int,
) -> ContextCandidate:
    """Classify one element from raw facts and a two-element local window."""

    current = facts[index]
    previous = facts[max(0, index - 2):index]
    following = facts[index + 1:index + 3]
    position = index / max(len(facts) - 1, 1)
    evidence = [_raw_type_evidence(current)] if current.type_id else []
    evidence.extend((
        ContextEvidence("style", f"style:{current.style_name or 'none'}", 0.05),
        ContextEvidence("text", "text:short" if len(current.text) <= 40 else "text:long", 0.05),
    ))

    if current.physical_kind == "page_break":
        return _candidate(current, ElementKind.PAGE_BREAK, 0.99, (
            ContextEvidence("structural", "real_page_boundary", 0.99),
        ))
    physical = {
        "table": ElementKind.TABLE,
        "figure": ElementKind.FIGURE,
        "caption": ElementKind.CAPTION,
    }.get(current.physical_kind)
    if physical:
        evidence.append(ContextEvidence("context", f"physical:{current.physical_kind}", 0.95))
        return _candidate(current, physical, 0.95, evidence)

    text = current.text.strip()
    date_text = bool(_DATE_RE.fullmatch(text))
    sentence = _body_sentence(text)
    head = index <= max(4, int(len(facts) * 0.30))
    tail = position >= 0.65 or (
        position >= 0.20 and any(item.physical_kind == "page_break" for item in facts[index + 1:])
    )
    previous_title = any(item.type_id in _TITLE_TYPES for item in previous)
    previous_signature = any(_signature_agency_facts(item, facts) for item in previous)
    following_end = not following
    following_boundary = bool(following and following[0].physical_kind == "page_break")
    following_safe_tail = following_end or following_boundary or all(
        item.type_id in {"note", "annotation", "attachment_page_mark"} or item.physical_kind == "page_break"
        for item in following
    )

    if date_text:
        evidence.append(ContextEvidence("text", "date_pattern", 0.25))
        if previous_signature and tail and following_safe_tail and not previous_title:
            evidence.extend((
                ContextEvidence("context", "previous:signature_candidate", 0.30),
                ContextEvidence("context", "position:document_tail", 0.20),
                ContextEvidence("context", "following:document_end" if following_end else "following:page_or_note", 0.15),
            ))
            return _candidate(current, ElementKind.SIGNATURE_DATE, 0.95, evidence)
        if previous_title and head and not sentence:
            evidence.extend((
                ContextEvidence("context", "title_like_before", 0.30),
                ContextEvidence("context", "position:document_head", 0.15),
            ))
            return _candidate(current, ElementKind.TITLE_METADATA, 0.90, evidence)
        if sentence or _body_neighbors(previous, following):
            evidence.append(ContextEvidence("context", "body_sentence_context", 0.35))
            return _candidate(current, ElementKind.BODY_PARAGRAPH, 0.86, evidence)
        return _candidate(current, ElementKind.UNKNOWN, 0.55, evidence)

    if _ATTACHMENT_TITLE_RE.fullmatch(text):
        evidence.append(ContextEvidence("text", "strict_attachment_title", 0.30))
        real_boundary = bool(previous and previous[-1].physical_kind == "page_break")
        if real_boundary and tail and following:
            evidence.extend((
                ContextEvidence("structural", "preceded_by:real_page_boundary", 0.35),
                ContextEvidence("context", "position:document_tail", 0.15),
            ))
            return _candidate(current, ElementKind.ATTACHMENT_TITLE, 0.95, evidence)
        evidence.append(ContextEvidence("structural", "no_real_page_boundary", -0.10))
        return _candidate(current, ElementKind.UNKNOWN, 0.55, evidence)

    if _ATTACHMENT_NOTE_RE.match(text):
        evidence.append(ContextEvidence("text", "strict_attachment_note", 0.30))
        previous_body = bool(previous and previous[-1].type_id in _BODY_TYPES | {"heading1", "heading2", "heading3", "heading4"})
        no_boundary = not previous or previous[-1].physical_kind != "page_break"
        following_tail = bool(following and following[0].type_id in {"attachment_note_item", "sign_org", "sign_date"})
        if (tail or (position >= 0.25 and following_tail)) and previous_body and no_boundary and following_tail:
            evidence.extend((
                ContextEvidence("context", "previous:main_body", 0.20),
                ContextEvidence("context", "position:document_tail", 0.15),
                ContextEvidence("context", "following:note_or_signature", 0.15),
            ))
            return _candidate(current, ElementKind.ATTACHMENT_NOTE_ITEM, 0.90, evidence)

    if _signature_agency_facts(current, facts):
        evidence.extend((
            ContextEvidence("context", "following:date_candidate", 0.35),
            ContextEvidence("context", "position:document_tail", 0.20),
            ContextEvidence("text", "short_non_sentence", 0.15),
        ))
        return _candidate(current, ElementKind.SIGNATURE_AGENCY, 0.93, evidence)

    if head and previous_title and current.type_id in (_TITLE_META_TYPES | {"sign_org"}) and _short_non_sentence(text):
        evidence.extend((
            ContextEvidence("context", "title_like_before", 0.30),
            ContextEvidence("context", "position:document_head", 0.15),
        ))
        return _candidate(current, ElementKind.TITLE_METADATA, 0.88, evidence)

    if current.type_id in _TITLE_TYPES and head and not sentence:
        evidence.extend((
            ContextEvidence("context", "position:document_head", 0.20),
            ContextEvidence("style", f"style:{current.style_name or 'none'}", 0.10),
        ))
        return _candidate(current, ElementKind.DOCUMENT_TITLE, 0.90, evidence)

    for heading_kind, pattern in _HEADING_PATTERNS:
        if pattern.match(text) and current.type_id in {f"heading{_heading_level(heading_kind)}", "heading1_report"}:
            evidence.extend((
                ContextEvidence("text", f"numbering:heading_{_heading_level(heading_kind)}", 0.35),
                ContextEvidence("context", "raw_heading_type_support", 0.25),
            ))
            return _candidate(current, heading_kind, 0.90, evidence)

    direct = {
        "list": ElementKind.LIST,
        "list_item": ElementKind.LIST,
        "quote": ElementKind.QUOTE,
        "attachment_note_item": ElementKind.ATTACHMENT_NOTE_ITEM,
        "attachment_title": ElementKind.ATTACHMENT_TITLE,
        "note": ElementKind.NOTE,
        "annotation": ElementKind.NOTE,
    }.get(current.type_id)
    if direct and not sentence:
        evidence.append(ContextEvidence("context", "raw_type_with_local_shape", 0.65))
        return _candidate(current, direct, 0.86, evidence)

    if sentence or current.type_id in _BODY_TYPES:
        if sentence:
            evidence.append(ContextEvidence("context", "body_sentence_context", 0.35))
        evidence.append(ContextEvidence("context", "raw_body_type_support", 0.30))
        confidence = 0.88 if sentence else current.classification_confidence
        return _candidate(current, ElementKind.BODY_PARAGRAPH, confidence, evidence)

    if current.type_id == "__letterhead__":
        kind = _letterhead_kind(current.style_name)
        if kind != ElementKind.UNKNOWN:
            evidence.append(ContextEvidence("style", f"style:{current.style_name}", 0.80))
            return _candidate(current, kind, 0.90, evidence)

    return _candidate(current, ElementKind.UNKNOWN, 0.45, evidence)


def _paragraph_fact(index, source_index, paragraph):
    type_id = str(getattr(paragraph, "type_id", "") or "") or None
    text = str(getattr(paragraph, "original_text", "") or getattr(paragraph, "text", "") or "").strip()
    features = getattr(paragraph, "features", None)
    style = str(getattr(features, "style_name", "") or _paragraph_style_id(paragraph) or "")
    alignment = str(getattr(features, "alignment", "") or "")
    meta = getattr(paragraph, "meta", {}) or {}
    confidence = meta.get("classification_confidence", 0.9 if type_id and type_id != "mystery" else 0.45)
    try:
        confidence = max(0.0, min(float(confidence), 1.0))
    except (TypeError, ValueError):
        confidence = 0.45
    physical = {
        "__table__": "table",
        "__image__": "figure",
        "__object_caption__": "caption",
    }.get(type_id, "paragraph")
    return RawElementFacts(
        index, source_index, type_id, text, style, alignment, confidence, physical,
        _hash(text), _style_hash(style, alignment, type_id, paragraph), _node_identity(paragraph),
    )


def _virtual_page_fact(index, source_index):
    return RawElementFacts(
        index, source_index, None, "", "", "", 0.99, "page_break",
        _hash(""), _hash("page_break"), None,
    )


def _candidate(fact, kind, confidence, evidence):
    return ContextCandidate(
        fact.index, kind, round(confidence, 3), tuple(evidence), fact.type_id,
        fact.text_fingerprint, fact.style_fingerprint,
    )


def _signature_agency_facts(current, facts):
    if current.physical_kind != "paragraph" or not _short_non_sentence(current.text):
        return False
    position = current.index / max(len(facts) - 1, 1)
    following = facts[current.index + 1:current.index + 3]
    date = next((item for item in following if item.physical_kind != "page_break"), None)
    if position < 0.35 or date is None or not _DATE_RE.fullmatch(date.text):
        return False
    between = facts[current.index + 1:date.index]
    return all(item.type_id in {"note", "annotation"} or item.physical_kind == "page_break" for item in between)


def _body_neighbors(previous, following):
    neighbors = [item for item in (*previous[-1:], *following[:1]) if item.physical_kind != "page_break"]
    return bool(neighbors) and all(item.type_id in _BODY_TYPES or _body_sentence(item.text) for item in neighbors)


def _body_sentence(text):
    return len(text) >= 8 and bool(re.search(r"[。！？；]$", text))


def _short_non_sentence(text):
    return bool(text and len(text) <= 40 and not _body_sentence(text))


def _raw_type_evidence(fact):
    return ContextEvidence("context", f"raw_type:{fact.type_id}", min(fact.classification_confidence, 0.25))


def _heading_level(kind):
    return {
        ElementKind.HEADING_1: 1, ElementKind.HEADING_2: 2,
        ElementKind.HEADING_3: 3, ElementKind.HEADING_4: 4,
    }[kind]


def _letterhead_kind(style):
    return {
        "DCT-LetterheadMark": ElementKind.LETTERHEAD_MARK,
        "DCT-DocumentNumber": ElementKind.DOCUMENT_NUMBER,
        "DCT-SignerLine": ElementKind.SIGNER,
        "DCT-LetterheadSeparator": ElementKind.LETTERHEAD_SEPARATOR,
        "Docxtool Letterhead Mark": ElementKind.LETTERHEAD_MARK,
        "Docxtool Document Number": ElementKind.DOCUMENT_NUMBER,
        "Docxtool Signer Line": ElementKind.SIGNER,
        "Docxtool Letterhead Separator": ElementKind.LETTERHEAD_SEPARATOR,
    }.get(style, ElementKind.UNKNOWN)


def _page_break_before(paragraph):
    if (getattr(paragraph, "meta", {}) or {}).get("page_break_before"):
        return True
    node = _paragraph_node(paragraph)
    p_pr = node.find(qn("w:pPr")) if node is not None else None
    return p_pr is not None and p_pr.find(qn("w:pageBreakBefore")) is not None


def _paragraph_style_id(paragraph):
    node = _paragraph_node(paragraph)
    p_pr = node.find(qn("w:pPr")) if node is not None else None
    p_style = p_pr.find(qn("w:pStyle")) if p_pr is not None else None
    return p_style.get(qn("w:val")) if p_style is not None else ""


def _inline_page_break(paragraph):
    return any(getattr(token, "kind", "") == "page_break" for token in getattr(paragraph, "inline_tokens", ()))


def _style_hash(style, alignment, type_id, paragraph):
    meta = getattr(paragraph, "meta", {}) or {}
    value = "|".join((
        style, alignment, type_id or "",
        "page" if _inline_page_break(paragraph) else "",
        "section" if meta.get("sectPr") is not None else "",
    ))
    return _hash(value)


def _hash(value):
    return sha256(str(value or "").encode("utf-8")).hexdigest()


def _node_identity(paragraph):
    node = _paragraph_node(paragraph)
    return id(node) if node is not None else None


def _paragraph_node(paragraph):
    holder = (getattr(paragraph, "meta", {}) or {}).get("paragraph_xml")
    node = getattr(holder, "_p", None)
    if node is None:
        node = getattr(holder, "_element", None)
    if node is None and getattr(holder, "tag", None) == qn("w:p"):
        node = holder
    return node
