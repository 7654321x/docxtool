"""Stable vocabulary for the recognition pipeline."""

from dataclasses import dataclass
from enum import Enum


class DocumentMode(str, Enum):
    UNKNOWN = "unknown"
    NORMAL = "normal"
    REPORT = "report"
    NOTICE = "notice"
    PLAN = "plan"
    MEETING_MINUTES = "meeting_minutes"


class SectionKind(str, Enum):
    HEADER = "header"
    DISPATCH_META = "dispatch_meta"
    RECIPIENT = "recipient"
    BODY = "body"
    MEETING_META = "meeting_meta"
    SIGNATURE = "signature"
    SOURCE_NOTE = "source_note"
    EMBEDDED_DOCUMENT = "embedded_document"
    ATTACHMENT_NOTE = "attachment_note"
    ATTACHMENT_BODY = "attachment_body"


class ParagraphType(str, Enum):
    MAIN_TITLE = "main_title"
    TITLE_CONTINUATION = "title_continuation"
    DISPATCH_NUMBER = "dispatch_number"
    RECIPIENT = "recipient"
    BODY = "body"
    HEADING_1 = "heading1"
    HEADING_2 = "heading2"
    HEADING_3 = "heading3"
    HEADING_4 = "heading4"
    KEY_VALUE = "key_value"
    MEETING_META = "meeting_meta"
    SIGNATURE_ORG = "signature_org"
    SIGNATURE_DATE = "signature_date"
    SOURCE_NOTE = "source_note"
    EMBEDDED_DOCUMENT_TITLE = "embedded_document_title"
    ATTACHMENT_NOTE = "attachment_note"
    ATTACHMENT_TITLE = "attachment_title"
    ADDRESSING = "addressing"
    DATE_LINE = "date_line"
    AUTHOR_LINE = "author_line"
    ROLE_NAME = "role_name"
    TITLE2 = "title2"
    GLOSSARY_TITLE = "glossary_title"
    GLOSSARY_ITEM = "glossary_item"
    ATTACHMENT_NOTE_ITEM = "attachment_note_item"
    ATTACHMENT_PAGE_MARK = "attachment_page_mark"
    ATTACHMENT_BODY = "attachment_body"
    HEADING_1_REPORT = "heading1_report"
    LIST = "list"
    LIST_ITEM = "list_item"
    QUOTE = "quote"
    ANNOTATION = "annotation"
    CLOSING = "closing"
    NUMBER = "number"
    LETTER = "letter"
    PAGE_NUMBER = "page_number"
    SUPERSCRIPT = "superscript"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DocumentModeDecision:
    mode: DocumentMode
    confidence: float
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecognitionSummary:
    engine_version: str
    diagnostic_schema_version: str
    document_mode: str
    block_count: int
    paragraph_count: int
    table_count: int
    image_count: int
    low_confidence_count: int
    needs_review_count: int
    validator_action_count: int
    unknown_type_fallback_count: int
    candidate_count_total: int
    max_candidate_count: int
    beam_width: int
