"""Compatibility facade for document-wide recognition context helpers."""

from __future__ import annotations

from .context import DocumentContext, HeadingFamily, analyze_document_context
from .context.front import (
    _FRONT_SCAN_SOFT_THRESHOLD,
    _HEAD_DATE_RE,
    _HEADING_STYLE_NAMES,
    _PERSON_NAME_RE,
    _ROLE_HINT_RE,
    _SPEECH_TITLE_RE,
    _TITLE_STYLE_NAMES,
    _body_like,
    _front_scan_positions,
    _front_semantic_item,
    _front_title_anchor,
    _head_date_line,
    _head_role_name,
    _next_semantic_position,
    _previous_semantic_position,
    _style_name,
    _title_metadata,
)
from .context.model import _family_diagnostic
from .context.numbering import _CIRCLED_ORDINALS, _CN_DIGITS, _cn_ordinal, _numbering_ordinal
from .context.tail import (
    _ATTACHMENT_ITEM_RE,
    _ATTACHMENT_PAGE_RE,
    _SIGNATURE_NEGATIVE_STARTS,
    _SIGNATURE_ORG_SUFFIX_RE,
    _all_tail_bridge,
    _attachment_item_like,
    _attachment_note_body,
    _attachment_page_like,
    _has_previous_body,
    _has_tail_after,
    _signature_date_like,
    _signature_org_shape,
    _signature_org_text,
    _tail_bridge_item,
)

_COMPATIBILITY_HELPERS = (
    _FRONT_SCAN_SOFT_THRESHOLD,
    _HEAD_DATE_RE,
    _HEADING_STYLE_NAMES,
    _PERSON_NAME_RE,
    _ROLE_HINT_RE,
    _SPEECH_TITLE_RE,
    _TITLE_STYLE_NAMES,
    _body_like,
    _front_scan_positions,
    _front_semantic_item,
    _front_title_anchor,
    _head_date_line,
    _head_role_name,
    _next_semantic_position,
    _previous_semantic_position,
    _style_name,
    _title_metadata,
    _family_diagnostic,
    _CIRCLED_ORDINALS,
    _CN_DIGITS,
    _cn_ordinal,
    _numbering_ordinal,
    _ATTACHMENT_ITEM_RE,
    _ATTACHMENT_PAGE_RE,
    _SIGNATURE_NEGATIVE_STARTS,
    _SIGNATURE_ORG_SUFFIX_RE,
    _all_tail_bridge,
    _attachment_item_like,
    _attachment_note_body,
    _attachment_page_like,
    _has_previous_body,
    _has_tail_after,
    _signature_date_like,
    _signature_org_shape,
    _signature_org_text,
    _tail_bridge_item,
)

__all__ = ["DocumentContext", "HeadingFamily", "analyze_document_context"]
