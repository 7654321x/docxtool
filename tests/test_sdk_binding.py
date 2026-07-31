from __future__ import annotations

import json
from pathlib import Path

from docx import Document

from docxtool.document.source_tape import SourceTape, canonicalize_text
from docxtool.sdk import bind_recognition_plan, recognize_docx
from docxtool.sdk.cli import main as sdk_main


def _write_document(path: Path, paragraphs: list[str]) -> None:
    document = Document()
    for value in paragraphs:
        document.add_paragraph(value)
    document.save(path)


def test_source_tape_keeps_utf16_and_canonical_boundaries_reversible() -> None:
    raw = "甲\u00a0😀\r\nＢ"
    tape = SourceTape.from_text(raw)

    assert tape.canonical_text == "甲 😀\nB"
    raw_start = tape.raw_offset_utf16(1)
    raw_end = tape.raw_offset_utf16(3)
    assert raw_start is not None and raw_end is not None
    canonical_range = tape.canonical_range_for_raw_span(1, 3)
    assert canonical_range is not None
    assert tape.raw_span_for_canonical_range(*canonical_range) == (1, 3)
    assert tape.raw_slice_utf16(raw_start, raw_end) == "\u00a0😀"


def test_sdk_splits_one_physical_paragraph_into_ordered_verified_segments(tmp_path: Path) -> None:
    source = tmp_path / "mixed.docx"
    raw = "一、总体要求。总体要求应覆盖😀、\t空格和重复文字。"
    _write_document(source, [raw])

    plan = recognize_docx(source, recognition_mode="legacy", include_text=True, include_raw_text=True)
    blocks = [block for block in plan.blocks if block.physical_paragraph_index == 0]

    assert len(blocks) == 2
    assert [block.segment_index for block in blocks] == [0, 1]
    assert {block.segment_count for block in blocks} == {2}
    assert [block.type_id for block in blocks] == ["heading1", "body"]
    assert all(block.source_locator_status == "confirmed" for block in blocks)
    assert all(block.locator_verified for block in blocks)
    assert blocks[0].raw_end_utf16 <= blocks[1].raw_start_utf16
    physical = raw.encode("utf-16-le")
    for block in blocks:
        selected = physical[block.raw_start_utf16 * 2:block.raw_end_utf16 * 2].decode("utf-16-le")
        assert selected == block.raw_fragment_text
        assert canonicalize_text(selected) == block.canonical_fragment_text
        assert block.raw_fragment_sha256
        assert block.canonical_fragment_sha256


def test_host_binding_uses_monotonic_order_and_handles_shifted_paragraphs(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    _write_document(source, ["重复段落", "一、总体要求。正文内容不少于五个字。", "重复段落"])
    plan = recognize_docx(source, recognition_mode="legacy")

    binding = bind_recognition_plan(plan, {
        "host_type": "test-host",
        "document_identity": "local-only",
        "paragraphs": [
            {"host_paragraph_index": 9, "raw_text": "额外段落"},
            {"host_paragraph_index": 10, "raw_text": "重复段落"},
            {"host_paragraph_index": 11, "raw_text": "一、总体要求。正文内容不少于五个字。"},
            {"host_paragraph_index": 12, "raw_text": "重复段落"},
        ],
    })

    assert all(item.binding_status == "confirmed" for item in binding.blocks)
    assert [item.host_paragraph_index for item in binding.blocks] == [10, 11, 11, 12]
    assert all(item.host_raw_end_utf16 is not None for item in binding.blocks)
    assert any("DUPLICATE_TEXT_DISAMBIGUATED" in item.binding_evidence for item in binding.blocks)


def test_host_binding_maps_canonical_text_to_host_raw_text_without_reusing_offsets(tmp_path: Path) -> None:
    source = tmp_path / "canonical.docx"
    _write_document(source, ["正文\u00a0内容😀"])
    plan = recognize_docx(source, recognition_mode="legacy")

    binding = bind_recognition_plan(plan, {
        "host_type": "test-host",
        "paragraphs": [{"raw_text": "正文 内容😀"}],
    })

    assert binding.blocks[0].binding_status == "confirmed"
    assert "PHYSICAL_CANONICAL_TEXT_MATCH" in binding.blocks[0].binding_evidence
    assert "RAW_TEXT_NORMALIZED" in binding.blocks[0].binding_warnings


def test_host_binding_refuses_ambiguous_duplicate_occurrences(tmp_path: Path) -> None:
    source = tmp_path / "ambiguous.docx"
    _write_document(source, ["相同内容"])
    plan = recognize_docx(source, recognition_mode="legacy")

    binding = bind_recognition_plan(plan, {
        "host_type": "test-host",
        "paragraphs": [{"raw_text": "相同内容"}, {"raw_text": "相同内容"}],
    })

    assert binding.blocks[0].binding_status == "unresolved"
    assert "SOURCE_OCCURRENCE_AMBIGUOUS" in binding.blocks[0].binding_warnings


def test_sdk_cli_can_bind_a_local_snapshot_without_default_text_output(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    output = tmp_path / "plan.json"
    snapshot = tmp_path / "snapshot.json"
    _write_document(source, ["普通正文内容"])
    snapshot.write_text(json.dumps({"host_type": "test-host", "paragraphs": [{"raw_text": "普通正文内容"}]}), encoding="utf-8")

    assert sdk_main([str(source), "--host-snapshot", str(snapshot), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["binding"]["blocks"][0]["binding_status"] == "confirmed"
    assert "recognized_text" not in payload["data"]["blocks"][0]
