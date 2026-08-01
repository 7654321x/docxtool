"""Candidate provider protocol and the built-in evidence providers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from .colon import is_organization_label, is_standalone_addressing_text
from .features import (
    DocumentBlock,
    ParagraphFeatures,
)
from .global_context import DocumentContext
from .model import DocumentMode, ParagraphType, SectionKind


_OPENING_SPEECH_TITLE_RE = re.compile(r"^(?:[一二三四五六七八九十]+、)?在[\u4e00-\u9fffA-Za-z0-9（）()、，,.·\-]{3,70}(?:上)?的?讲话$")
_EMPTY_KEY_VALUE_LABELS = frozenset({
    "责任单位", "责任人", "联系人", "联系电话", "联系地址",
    "承办单位", "牵头单位", "配合单位", "时间", "地点",
})
_STRUCTURE_CONTEXT_TYPES = {
    ParagraphType.ATTACHMENT_NOTE,
    ParagraphType.ATTACHMENT_NOTE_ITEM,
    ParagraphType.SIGNATURE_DATE,
    ParagraphType.SIGNATURE_ORG,
}
_ATTACHMENT_PAGE_MARK_RE = re.compile(r"^附件\s*[0-9一二三四五六七八九十百千]*$")


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
    document_context: DocumentContext


class CandidateProvider(Protocol):
    name: str

    def propose(self, block: DocumentBlock, features: ParagraphFeatures, context: CandidateContext) -> list[Candidate]: ...


def _section_hint_for_type(paragraph_type: ParagraphType) -> SectionKind:
    if paragraph_type in {ParagraphType.MAIN_TITLE, ParagraphType.TITLE_CONTINUATION}:
        return SectionKind.HEADER
    if paragraph_type == ParagraphType.DISPATCH_NUMBER:
        return SectionKind.DISPATCH_META
    if paragraph_type in {ParagraphType.RECIPIENT, ParagraphType.ADDRESSING}:
        return SectionKind.RECIPIENT
    if paragraph_type in {ParagraphType.SIGNATURE_ORG, ParagraphType.SIGNATURE_DATE}:
        return SectionKind.SIGNATURE
    if paragraph_type in {ParagraphType.ATTACHMENT_NOTE, ParagraphType.ATTACHMENT_NOTE_ITEM}:
        return SectionKind.ATTACHMENT_NOTE
    if paragraph_type in {
        ParagraphType.ATTACHMENT_TITLE,
        ParagraphType.ATTACHMENT_BODY,
        ParagraphType.ATTACHMENT_PAGE_MARK,
    }:
        return SectionKind.ATTACHMENT_BODY
    return SectionKind.BODY


def _body_like_candidate(features: ParagraphFeatures) -> bool:
    if not features.compact_text:
        return False
    if features.dispatch_number_match or features.date_match or features.heading_shape_level:
        return False
    return bool(
        (features.ends_with_sentence_punctuation and features.text_length >= 12)
        or features.text_length >= 34
    )


def _context_evidence_for(
    paragraph_type: ParagraphType,
    features: ParagraphFeatures,
    context: CandidateContext,
) -> tuple[str, ...]:
    document_context = context.document_context
    if document_context is None:
        return ()
    if paragraph_type == ParagraphType.ATTACHMENT_NOTE:
        return document_context.attachment_note_reasons(context.index)
    if paragraph_type == ParagraphType.ATTACHMENT_NOTE_ITEM:
        return document_context.attachment_item_reasons(context.index)
    if paragraph_type == ParagraphType.SIGNATURE_ORG:
        return document_context.signature_org_reasons(context.index)
    if paragraph_type == ParagraphType.SIGNATURE_DATE:
        return document_context.signature_date_reasons(context.index)
    return ()


def _soften_unverified_structure(
    paragraph_type: ParagraphType,
    score: float,
    evidence: str,
    features: ParagraphFeatures,
    context: CandidateContext,
) -> tuple[float, str]:
    if paragraph_type not in _STRUCTURE_CONTEXT_TYPES:
        return score, evidence
    if _context_evidence_for(paragraph_type, features, context):
        return score, evidence
    return min(score, 0.44), f"{evidence}-unverified-context"


def _soften_legacy_body_in_front_context(
    paragraph_type: ParagraphType,
    score: float,
    evidence: str,
    context: CandidateContext,
) -> tuple[float, str]:
    if paragraph_type != ParagraphType.BODY or context.document_context is None:
        return score, evidence
    if (
        context.index in context.document_context.front_positions
        or context.document_context.title_score(context.index) >= 0.44
        or context.document_context.front_metadata_kind(context.index)
    ):
        return min(score, 0.42), f"{evidence}-weak-front-context"
    return score, evidence


class StructuralCandidateProvider:
    name = "structural"

    def propose(self, block, features, context):
        result = []
        if block.kind == "caption":
            return [Candidate(ParagraphType.CAPTION, 1.0, self.name, ("object-caption",), hard=True, section_hint=SectionKind.BODY)]
        if features.compact_text.startswith(("图", "表")):
            marker = features.compact_text[1:]
            if marker and marker[0] in "0123456789一二三四五六七八九十百":
                return [Candidate(
                    ParagraphType.BODY,
                    1.0,
                    self.name,
                    ("unbound-caption-like-body",),
                    hard=True,
                    section_hint=SectionKind.BODY,
                )]
        if features.dispatch_number_match:
            result.append(Candidate(ParagraphType.DISPATCH_NUMBER, 1.0, self.name, ("dispatch-number",), hard=True, section_hint=SectionKind.DISPATCH_META))
        if (
            _ATTACHMENT_PAGE_MARK_RE.fullmatch(features.compact_text)
            and context.previous_type in {
                ParagraphType.ATTACHMENT_NOTE,
                ParagraphType.ATTACHMENT_NOTE_ITEM,
                ParagraphType.SIGNATURE_DATE,
                ParagraphType.ATTACHMENT_BODY,
            }
        ):
            result.append(Candidate(
                ParagraphType.ATTACHMENT_PAGE_MARK,
                1.0,
                self.name,
                ("attachment-page-boundary",),
                hard=True,
                section_hint=SectionKind.ATTACHMENT_BODY,
            ))
        if (
            context.previous_type == ParagraphType.ATTACHMENT_PAGE_MARK
            and features.compact_text
            and features.text_length <= 40
            and not features.contains_colon
            and features.heading_shape_level is None
        ):
            result.append(Candidate(
                ParagraphType.ATTACHMENT_TITLE,
                0.98,
                self.name,
                ("after-attachment-page-mark",),
                hard=True,
                section_hint=SectionKind.ATTACHMENT_BODY,
            ))
        if context.previous_type in {ParagraphType.ATTACHMENT_TITLE, ParagraphType.ATTACHMENT_BODY} and features.compact_text:
            result.append(Candidate(
                ParagraphType.ATTACHMENT_BODY,
                0.94,
                self.name,
                ("inside-attachment-body",),
                section_hint=SectionKind.ATTACHMENT_BODY,
            ))
        signature_date_evidence = (
            context.document_context.signature_date_reasons(context.index)
            if context.document_context is not None else ()
        )
        if signature_date_evidence:
            result.append(Candidate(
                ParagraphType.SIGNATURE_DATE,
                0.97,
                self.name,
                signature_date_evidence,
                hard=True,
                section_hint=SectionKind.SIGNATURE,
            ))
        elif features.date_match:
            result.append(Candidate(
                ParagraphType.BODY,
                0.76,
                self.name,
                ("date-without-signature-context",),
                section_hint=SectionKind.BODY,
            ))
        signature_evidence = (
            context.document_context.signature_org_reasons(context.index)
            if context.document_context is not None else ()
        )
        if signature_evidence:
            result.append(Candidate(
                ParagraphType.SIGNATURE_ORG,
                0.97,
                self.name,
                signature_evidence,
                hard=True,
                section_hint=SectionKind.SIGNATURE,
            ))
        if is_standalone_addressing_text(features.normalized_text):
            result.append(Candidate(
                ParagraphType.ADDRESSING,
                0.99,
                self.name,
                ("standalone-addressing",),
                hard=True,
                section_hint=SectionKind.RECIPIENT,
            ))
        if features.colon_inline_addressing_body:
            result.append(Candidate(
                ParagraphType.ADDRESSING,
                0.98,
                self.name,
                ("inline-addressing-boundary",),
                section_hint=SectionKind.RECIPIENT,
            ))
        elif (
            features.recipient_match
            and context.document_context is not None
            and (
                context.index == 0
                or context.document_context.before_body(context.index)
                or context.index in context.document_context.front_positions
            )
        ):
            result.append(Candidate(ParagraphType.RECIPIENT, 0.95, self.name, ("front-recipient",), hard=True, section_hint=SectionKind.RECIPIENT))
        if (
            features.colon_explanatory_body
            or (
                features.colon_body_label_candidate
                and context.document_context is not None
                and not context.document_context.before_body(context.index)
            )
        ):
            result.append(Candidate(
                ParagraphType.BODY,
                0.98,
                self.name,
                ("colon-explanatory-body" if features.colon_explanatory_body else "body-organization-label",),
                hard=True,
                section_hint=SectionKind.BODY,
            ))
        if features.attachment_note_match:
            attachment_evidence = (
                context.document_context.attachment_note_reasons(context.index)
                if context.document_context is not None else ()
            )
            if attachment_evidence:
                result.append(Candidate(
                    ParagraphType.ATTACHMENT_NOTE,
                    0.98,
                    self.name,
                    attachment_evidence,
                    hard=True,
                    section_hint=SectionKind.ATTACHMENT_NOTE,
                ))
            else:
                result.append(Candidate(
                    ParagraphType.ATTACHMENT_NOTE,
                    0.52,
                    self.name,
                    ("attachment-keyword-unverified-context",),
                    section_hint=SectionKind.ATTACHMENT_NOTE,
                ))
                result.append(Candidate(
                    ParagraphType.BODY,
                    0.94,
                    self.name,
                    ("attachment-keyword-without-tail-context",),
                    hard=True,
                    section_hint=SectionKind.BODY,
                ))
        attachment_item_evidence = (
            context.document_context.attachment_item_reasons(context.index)
            if context.document_context is not None else ()
        )
        if attachment_item_evidence:
            result.append(Candidate(
                ParagraphType.ATTACHMENT_NOTE_ITEM,
                0.97,
                self.name,
                attachment_item_evidence,
                hard=True,
                section_hint=SectionKind.ATTACHMENT_NOTE,
            ))
        if _body_like_candidate(features):
            result.append(Candidate(
                ParagraphType.BODY,
                0.82,
                self.name,
                ("body-prose-shape",),
                section_hint=SectionKind.BODY,
            ))
        return result


class KeyValueCandidateProvider:
    name = "key-value"

    def propose(self, block, features, context):
        label = features.key_value_label or ""
        if not label:
            return []
        if is_organization_label(label):
            return []
        if not str(features.key_value_value or "").strip() and label not in _EMPTY_KEY_VALUE_LABELS:
            return []
        if label in {"时间", "地点", "主持", "记录", "出席", "缺席", "列席", "参会", "参加", "议题", "议定事项", "会议名称", "会议时间", "会议地点"}:
            return [Candidate(ParagraphType.MEETING_META, 0.99, self.name, ("meeting-label",), hard=True, section_hint=SectionKind.MEETING_META)]
        # Normal key-value content is a short field label such as “责任单位”
        # or “联系人”.  Date/attachment tails and sentence-like prose must not
        # be elevated merely because they contain a colon.
        if (
            any(char.isdigit() for char in label)
            or any(mark in label for mark in "。！？；;（）()[]〔〕")
            or "附件" in label
        ):
            return []
        return [Candidate(ParagraphType.KEY_VALUE, 0.92, self.name, ("explicit-label",), section_hint=SectionKind.BODY)]


class NumberingCandidateProvider:
    name = "numbering"

    def propose(self, block, features, context):
        if features.heading_shape_level is None or features.key_value_label:
            return []
        mapping = {1: ParagraphType.HEADING_1, 2: ParagraphType.HEADING_2, 3: ParagraphType.HEADING_3, 4: ParagraphType.HEADING_4}
        kind = mapping.get(features.heading_shape_level)
        if kind is None:
            return []
        position = context.index
        global_context = context.document_context
        family = global_context.heading_family(position)
        score = 0.72
        evidence = list(global_context.heading_reasons(position) or (f"heading-level-{features.heading_shape_level}",))
        if features.heading_semantic_score >= 0.8:
            score += 0.08
            evidence.append("explicit-numbering-shape")
        if family and family.count >= 2:
            score += 0.18
        if family and position in family.supported_positions:
            score += 0.06
        if not global_context.before_body(position):
            score += 0.18
        if any(
            item in evidence
            for item in (
                "numbering-duplicate",
                "numbering-reverse",
                "numbering-gap",
                "missing-parent-heading",
                "numbering-starts-after-one",
            )
        ):
            # Sequence conflicts reduce certainty, but an explicit numbering
            # shape should stay available as the best type when structure
            # supports it.  The decoder turns the same evidence into review.
            score -= 0.06
        if (
            global_context.before_body(position)
            and features.heading_shape_level == 1
            and not (family and family.count >= 2)
        ):
            # A solitary first-level numbered first line competes with a
            # document title.  Explicit lower-level shapes remain structural
            # candidates and are reviewed through heading conflict evidence.
            score -= 0.22
            evidence.append("pre-body-heading-penalty")
        return [Candidate(
            kind,
            max(0.35, min(0.96, score)),
            self.name,
            tuple(dict.fromkeys(evidence)),
            heading_level=features.heading_shape_level,
        )]


class SemanticCandidateProvider:
    name = "semantic"

    def propose(self, block, features, context):
        result = []
        is_opening_speech = bool(_OPENING_SPEECH_TITLE_RE.fullmatch(features.compact_text))
        global_context = context.document_context
        score = global_context.title_score(context.index)
        reasons = global_context.title_reasons(context.index)
        # Existing documents commonly place a dispatch number immediately
        # before a title-continuation block.  Preserve that stable contract;
        # the front analysis still contributes metadata and body-boundary
        # evidence without changing the renderer's title-continuation style.
        follows_dispatch_continuation = (
            context.previous_type == ParagraphType.DISPATCH_NUMBER
            and str(features.legacy_type_id or "") == "title_cont"
        )
        if (score >= 0.44 or is_opening_speech) and not follows_dispatch_continuation:
            score = max(score, 0.98 if is_opening_speech else 0.0)
            result.append(Candidate(ParagraphType.MAIN_TITLE, score, self.name, reasons or ("opening-speech-title",), section_hint=SectionKind.HEADER))
        if (
            not context.boundary_before
            and context.previous_type in {ParagraphType.MAIN_TITLE, ParagraphType.TITLE_CONTINUATION}
            and context.index in global_context.front_positions
            and score >= 0.48
        ):
            result.append(Candidate(ParagraphType.TITLE_CONTINUATION, max(0.86, min(0.95, score + 0.20)), self.name, ("front-title-continuation",), section_hint=SectionKind.HEADER))
        return result


class FrontMatterMetadataCandidateProvider:
    """Promote structurally supported role/name and date lines in the document head."""

    name = "front-metadata"

    def propose(self, block, features, context):
        global_context = context.document_context
        if global_context is None or not global_context.before_body(context.index):
            return []
        kind = global_context.front_metadata_kind(context.index)
        if kind == "role_name":
            return [Candidate(
                ParagraphType.ROLE_NAME,
                0.97,
                self.name,
                ("front-role-name-shape",),
                section_hint=SectionKind.HEADER,
            )]
        if kind == "date_line":
            return [Candidate(
                ParagraphType.DATE_LINE,
                0.97,
                self.name,
                ("front-date-shape",),
                section_hint=SectionKind.HEADER,
            )]
        return []


class SourceListNumberingCandidateProvider:
    """Preserve short, visually explicit Word list headings.

    Word stores automatic list numbers outside paragraph text.  The importer
    retains that physical fact as ``@lvl_N``; without this provider the core
    prose classifier can overwrite a real heading merely because its visible
    text has no numbering prefix.
    """

    name = "source-list-numbering"

    def propose(self, block, features, context):
        if features.heading_shape_level is not None:
            return []
        source_features = getattr(block.raw_reference, "features", None)
        marker = str(
            getattr(source_features, "segment_numbering_features", "")
            or getattr(source_features, "numbering_prefix", "")
            or ""
        )
        match = re.fullmatch(r"@lvl_(\d+)", marker)
        if (
            match is None
            or features.text_length > 40
            or features.key_value_label
            or features.date_match
            or features.attachment_note_match
            or is_standalone_addressing_text(features.normalized_text)
            or not (features.is_bold or features.bold_char_ratio >= 0.65)
        ):
            return []
        level = min(int(match.group(1)) + 2, 4)
        paragraph_type = {
            2: ParagraphType.HEADING_2,
            3: ParagraphType.HEADING_3,
            4: ParagraphType.HEADING_4,
        }[level]
        return [Candidate(
            paragraph_type,
            1.0,
            self.name,
            (f"source-word-list-level-{match.group(1)}", "short-bold-list-heading"),
            hard=True,
            section_hint=SectionKind.BODY,
            heading_level=level,
        )]


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
        # Imported heading/title classifications can originate entirely from
        # a pasted Word style.  Other established structural facts (date,
        # role line, attachment, signature, etc.) remain useful evidence.
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


DEFAULT_PROVIDERS = (
    StructuralCandidateProvider(),
    KeyValueCandidateProvider(),
    NumberingCandidateProvider(),
    SemanticCandidateProvider(),
    FrontMatterMetadataCandidateProvider(),
    SourceListNumberingCandidateProvider(),
    CoreCandidateProvider(),
    LegacyCandidateProvider(),
    StyleCandidateProvider(),
)
