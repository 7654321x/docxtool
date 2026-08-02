from __future__ import annotations

from types import SimpleNamespace

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from docxtool.document.models import DocumentData, ParagraphData, ParagraphFeatures
from docxtool.document.normalization.pipeline import (
    apply_post_recognition_normalization,
    capture_pre_normalization_snapshot,
    merge_uniform_heading_siblings,
    strip_word_auto_numbering,
)


def _paragraph(type_id: str, *, numbering: str = "") -> ParagraphData:
    """Build one minimal mutable importer paragraph for pipeline tests."""
    return ParagraphData(
        text=type_id,
        type_id=type_id,
        original_text=type_id,
        features=ParagraphFeatures(),
        meta={"numbering": numbering},
    )


def _callbacks(events: list[str]):
    """Return injected compatibility callbacks and record their call order."""
    def tail(_paragraphs, *, normalize_text: bool = True) -> None:
        events.append("tail:{0}".format(normalize_text))

    def reorder(_paragraphs) -> None:
        events.append("reorder")

    def assign(_paragraphs, _rules, reset_on_attach: bool = True) -> None:
        events.append("assign:{0}".format(reset_on_attach))

    def merge(_paragraphs) -> None:
        events.append("merge")

    def record(_data, _before) -> None:
        events.append("record")

    def fix(_paragraphs) -> None:
        events.append("fix")

    def strip(paragraph) -> None:
        events.append("strip:{0}".format(paragraph.name))

    def sync(_data) -> None:
        events.append("sync")

    return {
        "normalize_tail_structures_func": tail,
        "reorder_attachment_note_before_signature_func": reorder,
        "assign_numbering_func": assign,
        "merge_siblings_func": merge,
        "record_applied_normalization_changes_func": record,
        "fix_numbering_gaps_func": fix,
        "strip_auto_numbering_func": strip,
        "sync_recognition_consistency_func": sync,
    }


def test_capture_pre_normalization_snapshot_keeps_importer_source_order() -> None:
    """Ledger snapshots retain physical source order and skip internal blocks."""
    data = DocumentData(paragraphs=[
        _paragraph("body"),
        _paragraph("__table__"),
        _paragraph("heading1"),
    ])

    snapshot = capture_pre_normalization_snapshot(data, ["first", "second", "third"])

    assert snapshot == [
        ("first", "first", "body"),
        ("second", "second", "heading1"),
        ("third", "third", ""),
    ]


def test_post_recognition_normalization_preserves_normalize_order() -> None:
    """Normalize mode invokes the former importer operations in exact order."""
    events: list[str] = []
    data = DocumentData(paragraphs=[_paragraph("heading1"), _paragraph("body")])
    doc_paragraphs = [SimpleNamespace(name="first"), SimpleNamespace(name="second")]

    apply_post_recognition_normalization(
        data,
        [],
        doc_paragraphs,
        strict_preservation=False,
        structural_preservation=False,
        processing_strategy="normalize",
        numbering_enabled=False,
        before_normalization=[],
        **_callbacks(events),
    )

    assert events == [
        "tail:True", "reorder", "assign:True", "merge", "record", "fix",
        "strip:first", "strip:second", "sync",
    ]


def test_post_recognition_normalization_preserves_structural_order() -> None:
    """Structural mode keeps the tail call, optional numbering and final sync."""
    events: list[str] = []
    heading = _paragraph("heading1")
    data = DocumentData(paragraphs=[heading, _paragraph("body")])

    apply_post_recognition_normalization(
        data,
        [],
        [],
        strict_preservation=False,
        structural_preservation=True,
        processing_strategy="structural",
        numbering_enabled=True,
        before_normalization=[],
        **_callbacks(events),
    )

    assert events == ["tail:False", "assign:True", "sync"]
    assert heading.meta["numbering_correction"] is True


def test_post_recognition_normalization_preserves_strict_order() -> None:
    """Strict mode retains the historical no-normalization final sync only."""
    events: list[str] = []

    apply_post_recognition_normalization(
        DocumentData(paragraphs=[_paragraph("body")]),
        [],
        [],
        strict_preservation=True,
        structural_preservation=False,
        processing_strategy="strict",
        numbering_enabled=False,
        before_normalization=[],
        **_callbacks(events),
    )

    assert events == ["sync"]


def test_strip_word_auto_numbering_preserves_the_importer_cleanup_behavior() -> None:
    """The moved cleanup removes only native numbering and remains a no-op otherwise."""
    document = Document()
    paragraph = document.add_paragraph("native numbering")
    properties = paragraph._element.get_or_add_pPr()
    properties.append(OxmlElement("w:numPr"))
    messages: list[tuple] = []

    strip_word_auto_numbering(paragraph, log_debug=lambda *args: messages.append(args))

    assert properties.find(qn("w:numPr")) is None
    assert messages == [("[导入] 剥离自动编号 chars=%s", len(paragraph.text))]


def test_merge_uniform_heading_siblings_preserves_legacy_rules() -> None:
    """The moved merge retains target levels and numbering protection exactly."""
    paragraphs = [
        _paragraph("heading1"),
        _paragraph("heading3"),
        _paragraph("heading3"),
        _paragraph("body"),
    ]
    messages: list[tuple] = []

    merge_uniform_heading_siblings(
        paragraphs,
        log_debug=lambda *args: messages.append(("debug",) + args),
        log_info=lambda *args: messages.append(("info",) + args),
    )

    assert [paragraph.type_id for paragraph in paragraphs] == [
        "heading1", "heading2", "heading2", "body",
    ]
    assert [paragraph.meta["numbering"] for paragraph in paragraphs[1:3]] == ["", ""]
    assert messages == [("info", "[同级合并] heading1下2项L3→heading2")]
