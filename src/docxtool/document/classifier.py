"""Conservative public-document paragraph classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class ParagraphKind(str, Enum):
    MAIN_TITLE = "main_title"
    TITLE_CONTINUATION = "title_continuation"
    DISPATCH_NUMBER = "dispatch_number"
    RECIPIENT = "recipient"
    HEADING_LEVEL_1 = "heading_level_1"
    HEADING_LEVEL_2 = "heading_level_2"
    HEADING_LEVEL_3 = "heading_level_3"
    HEADING_LEVEL_4 = "heading_level_4"
    BODY = "body"
    ATTACHMENT_NOTE = "attachment_note"
    ATTACHMENT_TITLE = "attachment_title"
    CLOSING = "closing"
    SIGNATURE_ORG = "signature_org"
    SIGNATURE_DATE = "signature_date"
    CC_RECIPIENT = "cc_recipient"


@dataclass(frozen=True)
class ClassificationEvidence:
    source: str
    detail: str
    weight: float


@dataclass(frozen=True)
class ParagraphClassification:
    kind: ParagraphKind
    confidence: float
    evidence: tuple[ClassificationEvidence, ...]
    auto_format: bool


@dataclass(frozen=True)
class ClassificationOptions:
    auto_format_threshold: float = 0.78
    aggressive_format_threshold: float = 0.88
    title_scan_limit: int = 4


@dataclass
class _Features:
    text: str
    index: int
    style_name: str = ""
    alignment: str = ""
    first_line_indent: float | None = None
    left_indent: float | None = None
    font_size_pt: float | None = None
    bold: bool = False
    native_numbering: bool = False


_CN_NUM = "一二三四五六七八九十百千万零〇"
_DISPATCH_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9]{0,12}[〔\[]\s*\d{4}\s*[〕\]]\s*\d+\s*号$")
_SIGN_DATE_RE = re.compile(
    rf"^((?:19|20)\d{{2}}|[零〇一二三四五六七八九]{{4}})年"
    rf"([0-9]{{1,2}}|[{_CN_NUM}]{{1,3}})月"
    rf"([0-9]{{1,2}}|[{_CN_NUM}]{{1,3}})日$"
)
_LEVEL_PATTERNS: tuple[tuple[ParagraphKind, re.Pattern[str]], ...] = (
    (ParagraphKind.HEADING_LEVEL_1, re.compile(rf"^[{_CN_NUM}]{{1,5}}、\S+")),
    (ParagraphKind.HEADING_LEVEL_2, re.compile(rf"^[（(][{_CN_NUM}]{{1,5}}[）)]\S+")),
    (ParagraphKind.HEADING_LEVEL_3, re.compile(r"^\d{1,2}[.．]\S+")),
    (ParagraphKind.HEADING_LEVEL_3, re.compile(r"^\d{1,2}、\S+")),
    (ParagraphKind.HEADING_LEVEL_4, re.compile(r"^[（(]\d{1,2}[）)]\S+")),
    (ParagraphKind.HEADING_LEVEL_4, re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]\S+")),
)
_CLOSING_RE = re.compile(r"^(特此(?:报告|通知|函达|批复|公告)|妥否，请批示|请予审示|以上报告)")
_RECIPIENT_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9、，,（）()\s]{2,40}[:：]$")
_CC_RE = re.compile(r"^抄送[:：]\S+")
_ATTACHMENT_NOTE_RE = re.compile(r"^附件[:：]\s*\S+")
_ATTACHMENT_TITLE_RE = re.compile(r"^附件\s*([0-9一二三四五六七八九十]+)?$")
_LAW_ARTICLE_RE = re.compile(r"^第[一二三四五六七八九十百千万0-9]+条")


def classify_paragraphs(
    paragraphs: Iterable[object],
    options: ClassificationOptions | None = None,
) -> list[ParagraphClassification]:
    """Classify paragraph-like objects in document order."""

    opts = options or ClassificationOptions()
    features = [_extract_features(item, index) for index, item in enumerate(paragraphs)]
    results: list[ParagraphClassification] = []
    seen_body = False
    seen_main_title = False
    signature_candidate_index = _find_signature_date_pair(features)

    for index, feat in enumerate(features):
        prev_kind = results[-1].kind if results else None
        next_feat = features[index + 1] if index + 1 < len(features) else None
        classification = _classify_one(
            feat,
            opts,
            prev_kind,
            next_feat,
            seen_body,
            seen_main_title,
            signature_candidate_index == index,
        )
        results.append(classification)
        if classification.kind in {
            ParagraphKind.BODY,
            ParagraphKind.HEADING_LEVEL_1,
            ParagraphKind.HEADING_LEVEL_2,
            ParagraphKind.HEADING_LEVEL_3,
            ParagraphKind.HEADING_LEVEL_4,
            ParagraphKind.CLOSING,
        }:
            seen_body = True
        if classification.kind == ParagraphKind.MAIN_TITLE:
            seen_main_title = True

    return results


def classify_paragraph(
    paragraph: object,
    options: ClassificationOptions | None = None,
) -> ParagraphClassification:
    return classify_paragraphs([paragraph], options)[0]


def _classify_one(
    feat: _Features,
    opts: ClassificationOptions,
    prev_kind: ParagraphKind | None,
    next_feat: _Features | None,
    seen_body: bool,
    seen_main_title: bool,
    is_signature_candidate: bool,
) -> ParagraphClassification:
    text = feat.text
    if not text:
        return _result(ParagraphKind.BODY, 0.4, [("default", "empty paragraph", 0.4)], opts, False)

    evidence: list[tuple[str, str, float]] = []
    if _CC_RE.match(text):
        return _result(ParagraphKind.CC_RECIPIENT, 0.95, [("pattern", "cc recipient label", 0.95)], opts, False)
    if _SIGN_DATE_RE.match(text):
        evidence.append(("pattern", "signature date", 0.95))
        if prev_kind == ParagraphKind.SIGNATURE_ORG:
            evidence.append(("context", "follows signature org", 0.04))
        return _result(ParagraphKind.SIGNATURE_DATE, min(_sum(evidence), 0.99), evidence, opts, False)
    if is_signature_candidate:
        evidence.append(("context", "followed by signature date near tail", 0.7))
        if _alignment_is(feat, "right") or _short_without_sentence_punctuation(text):
            evidence.append(("layout", "short unpunctuated org line", 0.18))
        return _result(ParagraphKind.SIGNATURE_ORG, min(_sum(evidence), 0.95), evidence, opts, False)
    if _DISPATCH_RE.match(text):
        evidence.append(("pattern", "dispatch number", 0.9))
        if feat.index <= opts.title_scan_limit:
            evidence.append(("position", "document head", 0.05))
        return _result(ParagraphKind.DISPATCH_NUMBER, min(_sum(evidence), 0.97), evidence, opts, False)
    if _RECIPIENT_RE.match(text) and not _looks_like_key_value_body(text):
        evidence.append(("pattern", "recipient colon line", 0.78))
        if not seen_body:
            evidence.append(("context", "before body", 0.1))
        return _result(ParagraphKind.RECIPIENT, min(_sum(evidence), 0.95), evidence, opts, False)
    if _ATTACHMENT_NOTE_RE.match(text):
        return _result(ParagraphKind.ATTACHMENT_NOTE, 0.92, [("pattern", "attachment note", 0.92)], opts, False)
    if _ATTACHMENT_TITLE_RE.match(text):
        evidence.append(("pattern", "attachment page mark", 0.7))
        if next_feat and _is_title_like(next_feat):
            evidence.append(("context", "next paragraph title-like", 0.18))
            return _result(ParagraphKind.ATTACHMENT_TITLE, 0.88, evidence, opts, False)
        return _result(ParagraphKind.ATTACHMENT_TITLE, 0.72, evidence, opts, False)

    heading_result = _classify_heading(feat, opts, seen_body)
    if heading_result is not None:
        return heading_result
    if _CLOSING_RE.match(text):
        return _result(ParagraphKind.CLOSING, 0.86, [("pattern", "closing phrase", 0.86)], opts, False)
    if _is_main_title_candidate(feat, opts, seen_main_title, seen_body):
        evidence.extend(
            [
                ("position", "first title scan block", 0.34),
                ("layout", "centered or title style", 0.3),
                ("shape", "title-like length and punctuation", 0.25),
            ]
        )
        return _result(ParagraphKind.MAIN_TITLE, min(_sum(evidence), 0.94), evidence, opts, True)
    if _is_title_continuation_candidate(feat, prev_kind, seen_body):
        evidence.extend(
            [
                ("context", "follows main title", 0.5),
                ("layout", "centered continuation", 0.24),
                ("shape", "title-like continuation", 0.16),
            ]
        )
        return _result(ParagraphKind.TITLE_CONTINUATION, min(_sum(evidence), 0.9), evidence, opts, True)

    evidence.append(("default", "no strong structural evidence", 0.62))
    if _has_sentence_punctuation(text) or len(text) >= 18:
        evidence.append(("shape", "body-like sentence", 0.16))
    if _looks_like_short_heading_without_support(feat):
        evidence.append(("policy", "short paragraph protected from title promotion", 0.08))
    return _result(ParagraphKind.BODY, min(_sum(evidence), 0.86), evidence, opts, False)


def _classify_heading(feat: _Features, opts: ClassificationOptions, seen_body: bool) -> ParagraphClassification | None:
    text = feat.text
    if _LAW_ARTICLE_RE.match(text) or _looks_like_date(text):
        return None
    for kind, pattern in _LEVEL_PATTERNS:
        if not pattern.match(text):
            continue
        evidence = [("pattern", f"{kind.value} numbering", 0.72)]
        if feat.native_numbering:
            evidence.append(("layout", "native numbering present", 0.1))
        if seen_body or feat.index > opts.title_scan_limit:
            evidence.append(("context", "inside body", 0.06))
        if _heading_has_inline_body(text):
            evidence.append(("shape", "heading followed by body sentence", 0.04))
        return _result(kind, min(_sum(evidence), 0.94), evidence, opts, True)
    return None


def _extract_features(paragraph: object, index: int) -> _Features:
    text = str(getattr(paragraph, "text", "") or "").strip()
    style = getattr(paragraph, "style_name", "")
    style_obj = getattr(paragraph, "style", None)
    if not style and style_obj is not None:
        style = str(getattr(style_obj, "name", "") or "")
    alignment = str(getattr(paragraph, "alignment", "") or "")
    paragraph_format = getattr(paragraph, "paragraph_format", None)
    first_line_indent = getattr(paragraph, "first_line_indent", None)
    left_indent = getattr(paragraph, "left_indent", None)
    if paragraph_format is not None:
        first_line_indent = first_line_indent or getattr(paragraph_format, "first_line_indent", None)
        left_indent = left_indent or getattr(paragraph_format, "left_indent", None)
    font_size = getattr(paragraph, "font_size_pt", None)
    bold = bool(getattr(paragraph, "bold", False))
    for run in getattr(paragraph, "runs", None) or []:
        if not str(getattr(run, "text", "") or "").strip():
            continue
        font = getattr(run, "font", None)
        font_size = font_size or _length_to_pt(getattr(font, "size", None))
        bold = bool(bold or getattr(font, "bold", False))
        break
    return _Features(
        text=text,
        index=index,
        style_name=str(style or ""),
        alignment=alignment,
        first_line_indent=_length_to_float(first_line_indent),
        left_indent=_length_to_float(left_indent),
        font_size_pt=_length_to_pt(font_size) if font_size is not None else None,
        bold=bold,
        native_numbering=_has_native_numbering(paragraph),
    )


def _find_signature_date_pair(features: list[_Features]) -> int | None:
    for index in range(max(0, len(features) - 8), len(features) - 1):
        if _SIGN_DATE_RE.match(features[index + 1].text) and _looks_like_signature_org(features[index].text):
            return index
    return None


def _looks_like_signature_org(text: str) -> bool:
    if not text or len(text) > 32:
        return False
    if any(mark in text for mark in "。；;：:"):
        return False
    return not text.startswith(("联系人", "以上", "请", "附件", "抄送"))


def _result(
    kind: ParagraphKind,
    confidence: float,
    evidence: list[tuple[str, str, float]],
    opts: ClassificationOptions,
    aggressive: bool,
) -> ParagraphClassification:
    normalized = max(0.0, min(confidence, 1.0))
    threshold = opts.aggressive_format_threshold if aggressive else opts.auto_format_threshold
    return ParagraphClassification(
        kind=kind,
        confidence=round(normalized, 3),
        evidence=tuple(ClassificationEvidence(source=s, detail=d, weight=w) for s, d, w in evidence),
        auto_format=normalized >= threshold,
    )


def _sum(evidence: list[tuple[str, str, float]]) -> float:
    return sum(item[2] for item in evidence)


def _is_main_title_candidate(feat: _Features, opts: ClassificationOptions, seen_main_title: bool, seen_body: bool) -> bool:
    if seen_main_title or seen_body or feat.index > opts.title_scan_limit:
        return False
    if _DISPATCH_RE.match(feat.text) or _RECIPIENT_RE.match(feat.text):
        return False
    return _is_title_like(feat)


def _is_title_continuation_candidate(feat: _Features, prev_kind: ParagraphKind | None, seen_body: bool) -> bool:
    if seen_body or prev_kind not in {ParagraphKind.MAIN_TITLE, ParagraphKind.TITLE_CONTINUATION}:
        return False
    if _DISPATCH_RE.match(feat.text) or _RECIPIENT_RE.match(feat.text):
        return False
    return _is_title_like(feat)


def _is_title_like(feat: _Features) -> bool:
    text = feat.text
    if not (4 <= len(text) <= 36):
        return False
    if _has_sentence_punctuation(text) or text.endswith(("：", ":")):
        return False
    style = feat.style_name.lower()
    return (
        _alignment_is(feat, "center")
        or "title" in style
        or "标题" in style
        or (feat.font_size_pt is not None and feat.font_size_pt >= 18)
        or feat.bold
    )


def _looks_like_short_heading_without_support(feat: _Features) -> bool:
    return len(feat.text) <= 8 and not _is_title_like(feat)


def _looks_like_key_value_body(text: str) -> bool:
    return text.startswith(("联系人", "责任单位", "联系电话", "地址", "邮编"))


def _heading_has_inline_body(text: str) -> bool:
    period = text.find("。")
    return period >= 0 and len(text[period + 1 :].strip()) >= 5


def _short_without_sentence_punctuation(text: str) -> bool:
    return len(text) <= 32 and not _has_sentence_punctuation(text)


def _has_sentence_punctuation(text: str) -> bool:
    return any(mark in text for mark in "。！？；;")


def _looks_like_date(text: str) -> bool:
    return bool(re.search(r"(?:19|20)\d{2}年\d{1,2}月\d{1,2}日", text))


def _alignment_is(feat: _Features, expected: str) -> bool:
    alignment = feat.alignment.lower()
    return expected in alignment or {"center": "居中", "right": "右", "left": "左"}.get(expected, "\0") in feat.alignment


def _length_to_pt(value: object) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            number = float(value)
            return number / 12700 if number > 1000 else number
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _length_to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _has_native_numbering(paragraph: object) -> bool:
    element = getattr(paragraph, "_element", None)
    if element is None:
        return bool(getattr(paragraph, "native_numbering", False))
    try:
        from docx.oxml.ns import qn

        ppr = element.find(qn("w:pPr"))
        return ppr is not None and ppr.find(qn("w:numPr")) is not None
    except Exception:
        return bool(getattr(paragraph, "native_numbering", False))
