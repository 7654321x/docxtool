"""Recognition-post normalization helpers.

This package contains steps that consume final recognition results and prepare
the document model for rendering without owning classification decisions.
"""

from docxtool.document.normalization.tail import (
    normalize_tail_structures,
    reorder_attachment_note_before_signature,
    sync_recognition_consistency,
)
from docxtool.document.normalization.changes import (
    record_applied_normalization_changes,
    record_strict_normalization_suggestions,
)
from docxtool.document.normalization.dates import (
    chinese_number_to_int,
    chinese_year_to_int,
    is_attachment_page_mark,
    is_sign_date_text,
    normalize_attachment_page_mark,
    normalize_sign_date,
)
from docxtool.document.normalization.numbering import (
    assign_heading_numbering,
    fix_heading_numbering_gaps,
    strip_numbering_prefix,
    style_key_to_rule_row,
)
from docxtool.document.normalization.pipeline import (
    apply_post_recognition_normalization,
    capture_pre_normalization_snapshot,
    merge_uniform_heading_siblings,
    strip_word_auto_numbering,
)
from docxtool.document.normalization.signature import normalize_sign_org
from docxtool.document.normalization.text import (
    normalize_basic_text,
    normalize_legacy_punctuation_text,
    normalize_quotes,
    to_chinese_punctuation,
)
from docxtool.document.normalization.responsibility import (
    is_responsibility_line,
    normalize_responsibility_line,
)

__all__ = [
    "chinese_number_to_int",
    "chinese_year_to_int",
    "assign_heading_numbering",
    "apply_post_recognition_normalization",
    "capture_pre_normalization_snapshot",
    "fix_heading_numbering_gaps",
    "is_attachment_page_mark",
    "is_sign_date_text",
    "normalize_attachment_page_mark",
    "normalize_sign_org",
    "normalize_sign_date",
    "normalize_tail_structures",
    "normalize_basic_text",
    "normalize_legacy_punctuation_text",
    "normalize_quotes",
    "is_responsibility_line",
    "normalize_responsibility_line",
    "merge_uniform_heading_siblings",
    "record_applied_normalization_changes",
    "record_strict_normalization_suggestions",
    "reorder_attachment_note_before_signature",
    "sync_recognition_consistency",
    "strip_numbering_prefix",
    "style_key_to_rule_row",
    "strip_word_auto_numbering",
    "to_chinese_punctuation",
]
