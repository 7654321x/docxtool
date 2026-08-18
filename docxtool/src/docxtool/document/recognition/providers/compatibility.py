"""Core, style and Legacy compatibility candidate providers."""

from __future__ import annotations

from ..model import ParagraphType
from .base import (
    Candidate,
    _section_hint_for_type,
    _soften_legacy_body_in_front_context,
    _soften_unverified_structure,
)


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
            "meeting_meta": ParagraphType.MEETING_META,
            "meeting_title_meta": ParagraphType.MEETING_TITLE_META,
            "attachment_note": ParagraphType.ATTACHMENT_NOTE,
            "attachment_title": ParagraphType.ATTACHMENT_TITLE,
            "signature_org": ParagraphType.SIGNATURE_ORG,
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
        score, evidence = _soften_unverified_structure(kind, max(0.0, min(score, 0.95)), "core-classifier", features, context)
        score, evidence = _soften_legacy_body_in_front_context(kind, score, evidence, context)
        return [Candidate(
            kind,
            score,
            self.name,
            (evidence,),
            section_hint=_section_hint_for_type(kind),
        )]


class StyleCandidateProvider:
    name = "style"

    def propose(self, block, features, context):
        if not features.style_name:
            return []
        style = " ".join(features.style_name.strip().casefold().split())
        compact = style.replace(" ", "")
        mapping = {
            "title": (ParagraphType.MAIN_TITLE, 0.44, "word-style-title-weak"),
            "标题": (ParagraphType.MAIN_TITLE, 0.44, "word-style-title-zh-weak"),
            "subtitle": (ParagraphType.TITLE_CONTINUATION, 0.42, "word-style-subtitle-weak"),
            "副标题": (ParagraphType.TITLE_CONTINUATION, 0.42, "word-style-subtitle-zh-weak"),
            "heading1": (ParagraphType.HEADING_1, 0.40, "word-style-heading1-weak"),
            "标题1": (ParagraphType.HEADING_1, 0.40, "word-style-heading1-zh-weak"),
            "heading2": (ParagraphType.HEADING_2, 0.40, "word-style-heading2-weak"),
            "标题2": (ParagraphType.HEADING_2, 0.40, "word-style-heading2-zh-weak"),
            "heading3": (ParagraphType.HEADING_3, 0.40, "word-style-heading3-weak"),
            "标题3": (ParagraphType.HEADING_3, 0.40, "word-style-heading3-zh-weak"),
            "heading4": (ParagraphType.HEADING_4, 0.40, "word-style-heading4-weak"),
            "标题4": (ParagraphType.HEADING_4, 0.40, "word-style-heading4-zh-weak"),
            "normal": (ParagraphType.BODY, 0.30, "word-style-normal-weak"),
            "正文": (ParagraphType.BODY, 0.30, "word-style-body-zh-weak"),
        }
        mapped = mapping.get(compact)
        if mapped is None:
            return []
        paragraph_type, score, evidence = mapped
        return [Candidate(paragraph_type, score, self.name, (evidence,), section_hint=_section_hint_for_type(paragraph_type))]


class LegacyCandidateProvider:
    name = "legacy"

    def propose(self, block, features, context):
        paragraph_type = _legacy_type(block.raw_reference)
        weak = {
            ParagraphType.MAIN_TITLE,
            ParagraphType.TITLE_CONTINUATION,
            ParagraphType.HEADING_1,
            ParagraphType.HEADING_2,
            ParagraphType.HEADING_3,
            ParagraphType.HEADING_4,
            ParagraphType.HEADING_1_REPORT,
        }
        score = 0.55 if paragraph_type in weak else 0.88
        evidence = "legacy-importer-weak" if paragraph_type in weak else "legacy-importer"
        score, evidence = _soften_unverified_structure(paragraph_type, score, evidence, features, context)
        score, evidence = _soften_legacy_body_in_front_context(paragraph_type, score, evidence, context)
        if (
            paragraph_type == ParagraphType.TITLE_CONTINUATION
            and context.previous_type == ParagraphType.DISPATCH_NUMBER
        ):
            score, evidence = 0.88, "legacy-dispatch-title-continuation"
        return [Candidate(
            paragraph_type,
            score,
            self.name,
            (evidence,),
            section_hint=_section_hint_for_type(paragraph_type),
        )]


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
        "meeting_meta": ParagraphType.MEETING_META,
        "meeting_title_meta": ParagraphType.MEETING_TITLE_META,
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
