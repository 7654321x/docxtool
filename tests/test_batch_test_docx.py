from __future__ import annotations

import importlib.util
from pathlib import Path

from docx import Document


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


def test_batch_defaults_to_normal_formatting_mode() -> None:
    assert batch_test_docx.parse_args([]).strict_preservation is False
    assert batch_test_docx.parse_args(["--strict-preservation"]).strict_preservation is True


def test_batch_report_marks_visual_rendering_as_not_run() -> None:
    status = batch_test_docx.visual_rendering_not_run()

    assert status["executed"] is False
    assert "未执行视觉渲染检查" in str(status["reason"])
