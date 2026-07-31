from __future__ import annotations

import json
from pathlib import Path

import pytest
from docx import Document

from docxtool import __version__ as package_version
from docxtool.document.importer import DocxImporter
from docxtool.document.style_config import load_rules_and_settings
from docxtool.paths import default_format_config_path
from docxtool.sdk import RecognitionInputError, recognize_docx
from docxtool.sdk.cli import main as sdk_main


def _source_document(path: Path) -> None:
    document = Document()
    document.add_paragraph("关于推进基层治理工作的通知")
    document.add_paragraph("一、总体要求")
    document.add_paragraph("要坚持问题导向，完善基层治理工作机制。")
    document.save(path)


def _default_config() -> dict:
    return json.loads(default_format_config_path().read_text(encoding="utf-8"))


def test_sdk_matches_existing_authoritative_recognition_and_redacts_text(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    _source_document(source)
    config = _default_config()
    plan = recognize_docx(source, format_config=config)

    rules, _settings, features = load_rules_and_settings(config)
    features["processing"] = {"strategy": "structural"}
    features["recognition"] = {"mode": "authoritative"}
    imported = DocxImporter().load(str(source), rules, features=features)

    assert plan.processing_mode == "structural"
    assert plan.recognition_mode == "authoritative"
    assert plan.package_version == package_version == "1.9"
    assert plan.locator_version == "source-locator-v2"
    assert plan.host_text_contract_version == "host-text-v1"
    assert [block.type_id for block in plan.blocks] == [item.type_id for item in imported.paragraphs]
    assert all(len(block.text_sha256) in {0, 64} for block in plan.blocks)
    payload = json.dumps(plan.to_dict(), ensure_ascii=False)
    assert "基层治理" not in payload
    assert "总体要求" not in payload


def test_sdk_emits_verified_physical_utf16_ranges_and_local_text_is_opt_in(tmp_path: Path) -> None:
    source = tmp_path / "mixed.docx"
    document = Document()
    document.add_paragraph("一、测试标题。这是同一物理段落中的测试正文内容。")
    document.save(source)

    redacted = recognize_docx(source, recognition_mode="legacy")
    local = recognize_docx(source, recognition_mode="legacy", include_text=True)
    assert len(local.blocks) >= 2
    assert "recognized_text" not in redacted.blocks[0].to_dict()
    for block in local.blocks:
        if block.kind != "paragraph":
            continue
        assert block.source_paragraph_index == 0
        assert block.physical_paragraph_index == 0
        assert block.locator_verified is True
        assert len(block.physical_text_sha256) == 64
        assert block.range_start_utf16 is not None
        assert block.range_end_utf16 is not None
        assert block.text_length_utf16 == len(block.recognized_text.encode("utf-16-le")) // 2
        physical = "一、测试标题。这是同一物理段落中的测试正文内容。".encode("utf-16-le")
        selected = physical[block.range_start_utf16 * 2:block.range_end_utf16 * 2].decode("utf-16-le")
        assert selected == block.recognized_text


def test_sdk_cli_writes_json_plan(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    output = tmp_path / "plan.json"
    _source_document(source)

    assert sdk_main([str(source), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["data"]["schema_version"] == "1.0"
    assert payload["data"]["blocks"]


def test_sdk_rejects_invalid_input_and_modes(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    _source_document(source)

    with pytest.raises(RecognitionInputError, match="processing_mode"):
        recognize_docx(source, processing_mode="unexpected")
    with pytest.raises(RecognitionInputError, match="可读取"):
        recognize_docx(tmp_path / "missing.docx")
