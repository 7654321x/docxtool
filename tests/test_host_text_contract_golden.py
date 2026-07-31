from __future__ import annotations

import json
from pathlib import Path

from docx import Document

from docxtool.document.source_tape import SourceTape, canonicalize_host_paragraph_text, utf16_length
from docxtool.sdk import bind_recognition_plan, recognize_docx


_GOLDEN_PATH = Path(__file__).resolve().parents[1] / "docs" / "HOST_TEXT_V1_GOLDEN.json"


def _golden() -> dict:
    return json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(path)


def test_host_text_v1_golden_canonical_cases_are_stable() -> None:
    payload = _golden()

    assert payload["text_contract_version"] == "host-text-v1"
    for case in payload["canonical_cases"]:
        result = canonicalize_host_paragraph_text(case["raw_text"])
        assert result.canonical_text == case["canonical_text"]
        assert list(result.raw_to_canonical_utf16) == case["raw_to_canonical_utf16"]
        assert list(result.canonical_to_raw_index) == case["canonical_to_raw_index"]
        assert list(result.warnings) == case["warnings"]


def test_host_text_v1_golden_segment_coordinates_are_readable() -> None:
    example = _golden()["recognition_plan_examples"][0]
    tape = SourceTape.from_text(example["physical_raw_text"])

    assert sum(utf16_length(tape.raw_slice_utf16(
        segment["raw_start_utf16"], segment["raw_end_utf16"]
    ) or "") for segment in example["segments"]) == utf16_length(example["physical_raw_text"])
    assert all(segment["source_locator_status"] == "confirmed" for segment in example["segments"])


def test_host_text_v1_golden_binding_statuses(tmp_path: Path) -> None:
    examples = {item["id"]: item for item in _golden()["binding_status_examples"]}
    confirmed = examples["confirmed-raw-match"]
    source = tmp_path / "confirmed.docx"
    _write_docx(source, [confirmed["source_text"]])
    plan = recognize_docx(source, recognition_mode="legacy")
    binding = bind_recognition_plan(plan, {"host_type": "golden", "paragraphs": [
        {"raw_text": confirmed["host_text"]},
    ]})
    assert binding.blocks[0].binding_status == confirmed["binding_status"]

    review = examples["review-canonical-match"]
    source = tmp_path / "review.docx"
    _write_docx(source, [review["source_text"]])
    plan = recognize_docx(source, recognition_mode="legacy")
    binding = bind_recognition_plan(plan, {"host_type": "golden", "paragraphs": [
        {"raw_text": review["host_text"]},
    ]})
    assert binding.blocks[0].binding_status == review["binding_status"]

    duplicate = examples["unresolved-local-duplicate"]
    source = tmp_path / "duplicate.docx"
    _write_docx(source, duplicate["source_paragraphs"])
    plan = recognize_docx(source, recognition_mode="legacy")
    binding = bind_recognition_plan(plan, {"host_type": "golden", "paragraphs": [
        {"raw_text": value} for value in duplicate["host_paragraphs"]
    ]})
    assert [item.binding_status for item in binding.blocks] == duplicate["binding_status_by_source"]
