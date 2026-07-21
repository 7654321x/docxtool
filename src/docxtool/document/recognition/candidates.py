"""Candidate provider protocol and the built-in evidence providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .features import DocumentBlock, ParagraphFeatures
from .model import DocumentMode, ParagraphType, SectionKind


@dataclass(frozen=True)
class Candidate:
    paragraph_type: ParagraphType
    score: float
    source: str
    evidence: tuple[str, ...] = ()
    vetoes: frozenset[ParagraphType] = frozenset()
    hard: bool = False
    section_hint: SectionKind | None = None
    heading_level: int | None = None


class CandidateContext(Protocol):
    mode: DocumentMode
    previous_type: ParagraphType | None
    index: int
    boundary_before: bool


class CandidateProvider(Protocol):
    name: str

    def propose(self, block: DocumentBlock, features: ParagraphFeatures, context: CandidateContext) -> list[Candidate]: ...


class StructuralCandidateProvider:
    name = "structural"

    def propose(self, block, features, context):
        result = []
        if features.dispatch_number_match:
            result.append(Candidate(ParagraphType.DISPATCH_NUMBER, 1.0, self.name, ("dispatch-number",), hard=True, section_hint=SectionKind.DISPATCH_META))
        if features.date_match:
            result.append(Candidate(ParagraphType.SIGNATURE_DATE, 0.99, self.name, ("date",), hard=True, section_hint=SectionKind.SIGNATURE))
        if features.recipient_match:
            result.append(Candidate(ParagraphType.RECIPIENT, 0.95, self.name, ("recipient",), hard=True, section_hint=SectionKind.RECIPIENT))
        if features.attachment_note_match:
            result.append(Candidate(ParagraphType.ATTACHMENT_NOTE, 0.97, self.name, ("attachment-note",), hard=True, section_hint=SectionKind.ATTACHMENT_NOTE))
        return result


class KeyValueCandidateProvider:
    name = "key-value"

    def propose(self, block, features, context):
        if not features.key_value_label:
            return []
        if features.key_value_label in {"时间", "地点", "主持", "记录", "出席", "缺席", "列席", "参会", "参加", "议题", "议定事项", "会议名称", "会议时间", "会议地点"}:
            return [Candidate(ParagraphType.MEETING_META, 0.99, self.name, ("meeting-label",), hard=True, section_hint=SectionKind.MEETING_META)]
        return [Candidate(ParagraphType.KEY_VALUE, 0.92, self.name, ("explicit-label",), section_hint=SectionKind.BODY)]


class NumberingCandidateProvider:
    name = "numbering"

    def propose(self, block, features, context):
        if features.heading_shape_level is None or features.key_value_label:
            return []
        mapping = {1: ParagraphType.HEADING_1, 2: ParagraphType.HEADING_2, 3: ParagraphType.HEADING_3}
        kind = mapping.get(features.heading_shape_level)
        if kind is None:
            return []
        return [Candidate(kind, 0.68, self.name, (f"heading-level-{features.heading_shape_level}",), heading_level=features.heading_shape_level)]


class SemanticCandidateProvider:
    name = "semantic"

    def propose(self, block, features, context):
        result = []
        if context.index == 0 and features.title_shape_score >= 0.5:
            result.append(Candidate(ParagraphType.MAIN_TITLE, 0.82, self.name, ("title-shape",), section_hint=SectionKind.HEADER))
        if not context.boundary_before and context.previous_type in {ParagraphType.MAIN_TITLE, ParagraphType.TITLE_CONTINUATION} and features.title_shape_score >= 0.5:
            result.append(Candidate(ParagraphType.TITLE_CONTINUATION, 0.64, self.name, ("title-continuation",), section_hint=SectionKind.HEADER))
        return result


class CoreCandidateProvider:
    """Adapter for the existing evidence-producing core classifier."""

    name = "core"

    def propose(self, block, features, context):
        meta = getattr(block.raw_reference, "meta", {}) or {}
        value = str(meta.get("classification_kind", ""))
        mapping = {
            "main_title": ParagraphType.MAIN_TITLE,
            "title_continuation": ParagraphType.TITLE_CONTINUATION,
            "dispatch_number": ParagraphType.DISPATCH_NUMBER,
            "recipient": ParagraphType.RECIPIENT,
            "heading_level_1": ParagraphType.HEADING_1,
            "heading1_report": ParagraphType.HEADING_1_REPORT,
            "heading_level_2": ParagraphType.HEADING_2,
            "heading_level_3": ParagraphType.HEADING_3,
            "heading_level_4": ParagraphType.HEADING_4,
            "body": ParagraphType.BODY,
            "attachment_note": ParagraphType.ATTACHMENT_NOTE,
            "attachment_title": ParagraphType.ATTACHMENT_TITLE,
            "signature_date": ParagraphType.SIGNATURE_DATE,
            "date_line": ParagraphType.DATE_LINE,
            "author_line": ParagraphType.AUTHOR_LINE,
            "role_name": ParagraphType.ROLE_NAME,
            "title2": ParagraphType.TITLE2,
            "glossary_title": ParagraphType.GLOSSARY_TITLE,
            "glossary_item": ParagraphType.GLOSSARY_ITEM,
            "attachment_note_item": ParagraphType.ATTACHMENT_NOTE_ITEM,
            "attachment_page_mark": ParagraphType.ATTACHMENT_PAGE_MARK,
            "attachment_body": ParagraphType.ATTACHMENT_BODY,
        }
        kind = mapping.get(value)
        if kind is None:
            return []
        try:
            score = float(meta.get("classification_confidence", 0.6))
        except (TypeError, ValueError):
            score = 0.6
        return [Candidate(kind, max(0.0, min(score, 0.95)), self.name, ("core-classifier",))]


class StyleCandidateProvider:
    name = "style"

    def propose(self, block, features, context):
        if not features.style_name:
            return []
        score = 0.08 if features.is_docxtool_style else 0.18
        evidence = "docxtool-style-low-weight" if features.is_docxtool_style else "external-style"
        return [Candidate(ParagraphType.BODY, score, self.name, (evidence,), section_hint=SectionKind.BODY)]


class LegacyCandidateProvider:
    name = "legacy"

    def propose(self, block, features, context):
        return [Candidate(_legacy_type(block.raw_reference), 0.55, self.name, ("legacy-importer",))]


def _legacy_type(paragraph) -> ParagraphType:
    historical = (getattr(paragraph, "meta", {}) or {}).get("legacy_type_id")
    if isinstance(historical, dict):
        historical = historical.get("value")
    value = str(historical or getattr(paragraph, "type_id", "body") or "body")
    aliases = {
        "title": ParagraphType.MAIN_TITLE,
        "title_cont": ParagraphType.TITLE_CONTINUATION,
        "heading1": ParagraphType.HEADING_1,
        "heading1_report": ParagraphType.HEADING_1_REPORT,
        "heading2": ParagraphType.HEADING_2,
        "heading3": ParagraphType.HEADING_3,
        "heading4": ParagraphType.HEADING_4,
        "sign_org": ParagraphType.SIGNATURE_ORG,
        "sign_date": ParagraphType.SIGNATURE_DATE,
        "addressing": ParagraphType.ADDRESSING,
        "date_line": ParagraphType.DATE_LINE,
        "author_line": ParagraphType.AUTHOR_LINE,
        "role_name": ParagraphType.ROLE_NAME,
        "title2": ParagraphType.TITLE2,
        "glossary_title": ParagraphType.GLOSSARY_TITLE,
        "glossary_item": ParagraphType.GLOSSARY_ITEM,
        "attachment_note": ParagraphType.ATTACHMENT_NOTE,
        "attachment_note_item": ParagraphType.ATTACHMENT_NOTE_ITEM,
        "attachment_page_mark": ParagraphType.ATTACHMENT_PAGE_MARK,
        "attachment_title": ParagraphType.ATTACHMENT_TITLE,
        "attachment_body": ParagraphType.ATTACHMENT_BODY,
        "list": ParagraphType.LIST,
        "list_item": ParagraphType.LIST_ITEM,
        "quote": ParagraphType.QUOTE,
        "annotation": ParagraphType.ANNOTATION,
        "closing": ParagraphType.CLOSING,
        "number": ParagraphType.NUMBER,
        "letter": ParagraphType.LETTER,
        "page_number": ParagraphType.PAGE_NUMBER,
        "superscript": ParagraphType.SUPERSCRIPT,
    }
    return aliases.get(value, ParagraphType.BODY)


DEFAULT_PROVIDERS = (StructuralCandidateProvider(), KeyValueCandidateProvider(), NumberingCandidateProvider(), SemanticCandidateProvider(), CoreCandidateProvider(), LegacyCandidateProvider(), StyleCandidateProvider())
