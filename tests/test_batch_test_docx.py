from __future__ import annotations

import importlib.util
from pathlib import Path

from docx import Document
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "batch_test_docx.py"
SPEC = importlib.util.spec_from_file_location("batch_test_docx", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
batch_test_docx = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch_test_docx)


def test_template_letterhead_options_are_derived_from_reference(tmp_path: Path) -> None:
    template = tmp_path / "correct.docx"
    document = Document()
    document.add_paragraph("测试市政府文件")
    document.add_paragraph("测试办〔2026〕12号")
    document.save(template)

    options = batch_test_docx.letterhead_options_from_template(template)

    assert options is not None
    assert options["enabled"] is True
    assert options["agencies"][0]["name"] == "测试市政府"
    assert options["document_number"] == {"agency_code": "测试办", "year": 2026, "sequence": 12}


def test_template_letterhead_options_require_mark_and_dispatch_number(tmp_path: Path) -> None:
    template = tmp_path / "incomplete.docx"
    document = Document()
    document.add_paragraph("关于进一步推进测试工作的通知")
    document.save(template)

    assert batch_test_docx.letterhead_options_from_template(template) is None


def test_batch_defaults_to_frontend_structural_mode() -> None:
    assert batch_test_docx.parse_args([]).strict_preservation is False
    assert batch_test_docx.parse_args([]).mode == "structural"
    assert batch_test_docx.parse_args(["--strict-preservation"]).strict_preservation is True
    assert batch_test_docx.parse_args(["--mode", "normalize"]).mode == "normalize"


def test_special_output_directory_is_fixed_to_long_term_regression_location() -> None:
    assert batch_test_docx._validate_special_output_dir(batch_test_docx.SPECIAL_OUTPUT_DIR) == batch_test_docx.SPECIAL_OUTPUT_DIR.resolve()


def test_batch_report_marks_visual_rendering_as_not_run() -> None:
    status = batch_test_docx.visual_rendering_not_run()

    assert status["executed"] is False
    assert "未执行视觉渲染检查" in str(status["reason"])


def _recognition_item(index: int, text: str, type_id: str = "body") -> dict:
    item = {
        "index": index,
        "_text": text,
        "text_hash": batch_test_docx.text_hash(text),
        "length": len(text),
        "type": type_id,
        "recognition_type": type_id,
        "section": "",
        "heading_level": batch_test_docx._heading_level(type_id),
    }
    item["region"] = batch_test_docx._recognition_region(item, index)
    return item


def _recognition_snapshot(items: list[dict]) -> dict:
    return {"mode": "document", "paragraphs": items, "tables": 0, "blocks": 0, "images": 0}


def test_structural_alignment_does_not_cascade_after_generated_letterhead() -> None:
    actual = _recognition_snapshot([
        _recognition_item(0, "测试市政府文件", "__letterhead__"),
        _recognition_item(1, "测试办〔2026〕12号", "dispatch_number"),
        _recognition_item(2, "正文甲"),
        _recognition_item(3, "正文乙"),
    ])
    expected = _recognition_snapshot([
        _recognition_item(0, "正文甲"),
        _recognition_item(1, "正文乙"),
    ])

    differences, stats = batch_test_docx.compare_snapshots(
        actual, expected, source="recognition", fields=("type",), document_fields=(), report_unmatched=True,
    )

    assert stats["matched_pairs"] == 2
    additions = [item for item in differences if item["category"] == "output_addition"]
    assert len(additions) == 2
    assert all(item["expected_change"] for item in additions)
    assert not any(item["actual_paragraph_index"] in {2, 3} for item in additions)


def test_structural_alignment_preserves_duplicate_paragraph_order() -> None:
    actual = _recognition_snapshot([
        _recognition_item(0, "重复正文"), _recognition_item(1, "重复正文"), _recognition_item(2, "结束"),
    ])
    expected = _recognition_snapshot([
        _recognition_item(0, "重复正文"), _recognition_item(1, "重复正文"), _recognition_item(2, "结束"),
    ])

    _, stats = batch_test_docx.compare_snapshots(
        actual, expected, source="recognition", fields=("type",), document_fields=(), report_unmatched=True,
    )

    assert stats["matched_pairs"] == 3
    assert stats["output_additions"] == 0
    assert stats["template_missing"] == 0


def test_expected_date_and_heading_normalization_are_not_real_structure_errors() -> None:
    actual = _recognition_snapshot([
        _recognition_item(0, "一、主要任务", "heading1"),
        _recognition_item(1, "2025年10月15日", "sign_date"),
    ])
    expected = _recognition_snapshot([
        _recognition_item(0, "一、主要任务。", "heading1"),
        _recognition_item(1, "二〇二五年十月十五日", "sign_date"),
    ])

    differences, stats = batch_test_docx.compare_snapshots(
        actual, expected, source="recognition", fields=("type",), document_fields=(), report_unmatched=True,
    )

    normalizations = [item for item in differences if item["category"] == "expected_normalization"]
    assert stats["matched_pairs"] == 2
    assert len(normalizations) == 2
    assert all(item["expected_change"] for item in normalizations)


def test_unmatched_content_is_reported_as_real_p1_problem() -> None:
    actual = _recognition_snapshot([_recognition_item(0, "保留段落")])
    expected = _recognition_snapshot([_recognition_item(0, "保留段落"), _recognition_item(1, "缺失段落")])

    differences, _ = batch_test_docx.compare_snapshots(
        actual, expected, source="recognition", fields=("type",), document_fields=(), report_unmatched=True,
    )
    missing = next(item for item in differences if item["category"] == "template_missing")

    assert missing["expected_change"] is False
    assert batch_test_docx.severity(missing["category"], expected_change=missing["expected_change"]) == "P1"


def test_input_fixture_content_difference_is_not_reported_as_output_p1() -> None:
    source = _recognition_snapshot([_recognition_item(0, "测试输入中的错误序号")])
    actual = {
        "recognition": _recognition_snapshot([_recognition_item(0, "测试输入中的错误序号")]),
        "physical": {"paragraphs": [], "tables": 0, "sections": 1, "inline_shapes": 0, "headers": 0, "footers": 0},
    }
    expected = {
        "recognition": _recognition_snapshot([_recognition_item(0, "正确模板序号")]),
        "physical": {"paragraphs": [], "tables": 0, "sections": 1, "inline_shapes": 0, "headers": 0, "footers": 0},
    }

    differences, summary = batch_test_docx.compare_documents(actual, expected, source_recognition=source)

    fixture_differences = [item for item in differences if item["expected_reason"] == "input_fixture_difference"]
    assert summary["input_fixture_differences"] == 2
    assert len(fixture_differences) == 2
    assert summary["unexpected_differences"] == 0


def test_reordered_content_does_not_match_across_the_sequence() -> None:
    actual = _recognition_snapshot([_recognition_item(0, "乙"), _recognition_item(1, "甲")])
    expected = _recognition_snapshot([_recognition_item(0, "甲"), _recognition_item(1, "乙")])

    differences, _ = batch_test_docx.compare_snapshots(
        actual, expected, source="recognition", fields=("type",), document_fields=(), report_unmatched=True,
    )

    assert any(item["category"] in {"output_addition", "template_missing"} and not item["expected_change"] for item in differences)


def test_render_sample_selection_is_deterministic_and_risk_first() -> None:
    records = [
        {"编号": "001", "成功": True, "模板对齐": {"real_issue_counts": {"P1": 0}}, "结构诊断": {}},
        {"编号": "002", "成功": True, "模板对齐": {"real_issue_counts": {"P1": 2}}, "结构诊断": {}},
        {"编号": "003", "成功": True, "模板对齐": {"real_issue_counts": {"P2": 5}}, "结构诊断": {}},
        {"编号": "004", "成功": True, "模板对齐": {"real_issue_counts": {}}, "结构诊断": {}},
    ]

    selected = batch_test_docx.select_render_samples(records, 2)

    assert [item["编号"] for item in selected] == ["002", "003"]


@pytest.mark.parametrize(
    ("text", "ink_ratio", "expected_status", "suspected"),
    [
        ("— 17 —", 0.001, "empty_page", True),
        ("区政协办\n2025年10月15日\n— 17 —", 0.002, "sparse_page", True),
        ("附件2\n测试正文\n— 19 —", 0.001, "attachment_title_page", False),
        ("正常正文内容足够用于页面识别。" * 6, 0.04, "normal", False),
    ],
)
def test_page_visual_status_distinguishes_empty_sparse_and_attachment_pages(
    text: str, ink_ratio: float, expected_status: str, suspected: bool,
) -> None:
    status, actual_suspected, _ = batch_test_docx._page_visual_status(text, ink_ratio)

    assert status == expected_status
    assert actual_suspected is suspected


def test_require_render_implies_render_review() -> None:
    args = batch_test_docx.parse_args(["--require-render"])

    assert args.render_review is True


def test_visual_review_reports_conversion_failure_without_leaking_content(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "sample.docx"
    output.write_bytes(b"placeholder")
    record = {"编号": "001", "成功": True, "模板对齐": {"real_issue_counts": {}}, "结构诊断": {}}
    monkeypatch.setattr(batch_test_docx, "_rendering_dependencies", lambda: ("soffice", object()))
    monkeypatch.setattr(batch_test_docx, "_render_document", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("conversion failed")))

    status = batch_test_docx.run_visual_review(
        [record], {"001": output}, [], {}, [],
        standard_root=tmp_path / "standard", special_root=tmp_path / "special", sample_size=1,
    )

    assert status["executed"] is True
    assert status["failures"][0]["error"] == "RuntimeError: conversion failed"
