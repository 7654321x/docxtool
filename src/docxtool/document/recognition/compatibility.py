"""Single compatibility boundary between recognition and legacy rendering."""

from .model import ParagraphType


TYPE_ID_MAP = {
    ParagraphType.MAIN_TITLE: "title",
    ParagraphType.TITLE_CONTINUATION: "title_cont",
    ParagraphType.DISPATCH_NUMBER: "dispatch_number",
    ParagraphType.RECIPIENT: "addressing",
    ParagraphType.ADDRESSING: "addressing",
    ParagraphType.BODY: "body",
    ParagraphType.HEADING_1: "heading1",
    ParagraphType.HEADING_2: "heading2",
    ParagraphType.HEADING_3: "heading3",
    ParagraphType.HEADING_4: "heading4",
    ParagraphType.KEY_VALUE: "responsibility_line",
    ParagraphType.MEETING_META: "meeting_meta",
    ParagraphType.SIGNATURE_ORG: "sign_org",
    ParagraphType.SIGNATURE_DATE: "sign_date",
    ParagraphType.SOURCE_NOTE: "note",
    ParagraphType.EMBEDDED_DOCUMENT_TITLE: "embedded_document_title",
    ParagraphType.ATTACHMENT_NOTE: "attachment_note",
    ParagraphType.ATTACHMENT_TITLE: "attachment_title",
    ParagraphType.DATE_LINE: "date_line",
    ParagraphType.AUTHOR_LINE: "author_line",
    ParagraphType.ROLE_NAME: "role_name",
    ParagraphType.TITLE2: "title2",
    ParagraphType.GLOSSARY_TITLE: "glossary_title",
    ParagraphType.GLOSSARY_ITEM: "glossary_item",
    ParagraphType.ATTACHMENT_NOTE_ITEM: "attachment_note_item",
    ParagraphType.ATTACHMENT_PAGE_MARK: "attachment_page_mark",
    ParagraphType.ATTACHMENT_BODY: "attachment_body",
    ParagraphType.HEADING_1_REPORT: "heading1_report",
    ParagraphType.LIST: "list",
    ParagraphType.LIST_ITEM: "list_item",
    ParagraphType.QUOTE: "quote",
    ParagraphType.ANNOTATION: "annotation",
    ParagraphType.CLOSING: "closing",
    ParagraphType.NUMBER: "number",
    ParagraphType.LETTER: "letter",
    ParagraphType.PAGE_NUMBER: "page_number",
    ParagraphType.SUPERSCRIPT: "superscript",
    ParagraphType.UNKNOWN: "body",
}


def to_type_id(paragraph_type: ParagraphType) -> str:
    return TYPE_ID_MAP[paragraph_type]


# These are deliberately explicit instead of relying on renderer ``dict.get``
# defaults.  The legacy renderer remains the implementation of the actual
# style rules, while this table documents the safe compatibility contract.
RULE_INDEX_MAP = {
    ParagraphType.MAIN_TITLE: 0, ParagraphType.TITLE_CONTINUATION: 0,
    ParagraphType.DISPATCH_NUMBER: 5, ParagraphType.RECIPIENT: 10,
    ParagraphType.BODY: 5, ParagraphType.HEADING_1: 1, ParagraphType.HEADING_2: 2,
    ParagraphType.HEADING_3: 3, ParagraphType.HEADING_4: 4, ParagraphType.KEY_VALUE: 5,
    ParagraphType.MEETING_META: 5, ParagraphType.SIGNATURE_ORG: 22,
    ParagraphType.SIGNATURE_DATE: 23, ParagraphType.SOURCE_NOTE: 5,
    ParagraphType.EMBEDDED_DOCUMENT_TITLE: 0, ParagraphType.ATTACHMENT_NOTE: 17,
    ParagraphType.ATTACHMENT_TITLE: 20, ParagraphType.ADDRESSING: 10,
    ParagraphType.DATE_LINE: 11, ParagraphType.AUTHOR_LINE: 12, ParagraphType.ROLE_NAME: 13,
    ParagraphType.TITLE2: 14, ParagraphType.GLOSSARY_TITLE: 0, ParagraphType.GLOSSARY_ITEM: 16,
    ParagraphType.ATTACHMENT_NOTE_ITEM: 18, ParagraphType.ATTACHMENT_PAGE_MARK: 19,
    ParagraphType.ATTACHMENT_BODY: 21, ParagraphType.HEADING_1_REPORT: 1,
    ParagraphType.LIST: 5, ParagraphType.LIST_ITEM: 5, ParagraphType.QUOTE: 5,
    ParagraphType.ANNOTATION: 5, ParagraphType.CLOSING: 5, ParagraphType.NUMBER: 6,
    ParagraphType.LETTER: 7, ParagraphType.PAGE_NUMBER: 8, ParagraphType.SUPERSCRIPT: 9,
    ParagraphType.UNKNOWN: None,
}
STYLE_ID_MAP = {item: "DCT-Body" for item in ParagraphType}
STYLE_ID_MAP.update({
    ParagraphType.MAIN_TITLE: "DCT-Title", ParagraphType.TITLE_CONTINUATION: "DCT-Title",
    ParagraphType.EMBEDDED_DOCUMENT_TITLE: "DCT-Title", ParagraphType.HEADING_1: "DCT-Heading1",
    ParagraphType.HEADING_2: "DCT-Heading2", ParagraphType.HEADING_3: "DCT-Heading3",
    ParagraphType.HEADING_4: "DCT-Heading4", ParagraphType.HEADING_1_REPORT: "DCT-Heading1",
    ParagraphType.RECIPIENT: "DCT-Recipient", ParagraphType.ADDRESSING: "DCT-Recipient",
    ParagraphType.KEY_VALUE: "DCT-Responsibility", ParagraphType.SIGNATURE_ORG: "DCT-Signature",
    ParagraphType.SIGNATURE_DATE: "DCT-Date", ParagraphType.DATE_LINE: "DCT-Date",
    ParagraphType.ROLE_NAME: "DCT-RoleName", ParagraphType.ATTACHMENT_NOTE: "DCT-AttachmentNote",
    ParagraphType.ATTACHMENT_NOTE_ITEM: "DCT-AttachmentNoteItem", ParagraphType.ATTACHMENT_TITLE: "DCT-AttachmentTitle",
    ParagraphType.ATTACHMENT_BODY: "DCT-AttachmentBody",
})


def resolve_render_mapping(paragraph_type: ParagraphType) -> tuple[str, int | None, str | None]:
    """Return an explicit legacy id, rule, and style for one internal type."""
    if paragraph_type is ParagraphType.UNKNOWN:
        return "body", None, None
    return to_type_id(paragraph_type), RULE_INDEX_MAP[paragraph_type], STYLE_ID_MAP[paragraph_type]
