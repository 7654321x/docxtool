from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from apps.wps.control import document_transaction as transaction_module
from apps.wps.control.format_current_document import FormatResult
from apps.wps.control.logging_adapter import document_log_context, file_identity
from apps.wps.control.recognize_document import bind_preview
from apps.wps.control.server import _safe_warnings
from docxtool.sdk import recognize_docx


def _fake_result(output_path: Path, log_dir: Path) -> FormatResult:
    log_path = log_dir / "test.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    return FormatResult(
        output_path=output_path,
        log_path=log_path,
        document_mode="NORMAL",
        paragraph_count=3,
        heading_count=1,
        body_count=2,
        export_stats={},
    )


def _install_fake_formatter(monkeypatch):
    def fake_format(source_path, output_path, *, operation_id, log_dir, format_config=None):
        target = Path(output_path)
        target.write_bytes(b"formatted")
        return _fake_result(target, Path(log_dir))

    monkeypatch.setattr(transaction_module, "format_current_document", fake_format)


def _snapshot(raw_text: str, *, snapshot_id: str = "snap-wps") -> dict:
    return {
        "schema_version": "host-snapshot-v1",
        "integration_contract_version": "integration-contract-v1",
        "snapshot_id": snapshot_id,
        "document_identity": "doc-wps",
        "document_revision": "rev-wps",
        "host": {"kind": "wps", "platform": "windows"},
        "host_type": "wps",
        "text_contract_version": "host-text-v1",
        "offset_encoding": "utf16_code_unit",
        "paragraphs": [
            {
                "host_paragraph_id": "main:000000",
                "host_paragraph_index": 0,
                "story_id": "main",
                "story_type": "main",
                "story_paragraph_index": 0,
                "section_index": None,
                "is_in_table": False,
                "raw_text": raw_text,
            }
        ],
    }


def test_transaction_commit_then_rollback_restores_original(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    assert source.read_bytes() == b"original"
    assert operation.temporary_path.read_bytes() == b"formatted"
    assert manager.journal_path.is_file()

    manager.commit(operation.operation_id)
    assert source.read_bytes() == b"formatted"
    assert operation.backup_path.read_bytes() == b"original"

    manager.rollback(operation.operation_id)
    assert source.read_bytes() == b"original"
    assert not manager.journal_path.exists()


def test_transaction_finalize_keeps_formatted_document(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    manager.commit(operation.operation_id)
    manager.finalize(operation.operation_id)

    assert source.read_bytes() == b"formatted"
    assert not operation.backup_path.exists()
    assert not manager.journal_path.exists()


def test_second_format_transaction_is_rejected_until_first_finishes(tmp_path, monkeypatch):
    first = tmp_path / "first.docx"
    second = tmp_path / "second.docx"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.prepare(str(first))
    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        manager.prepare(str(second))
    assert exc_info.value.code == "WPS_FORMAT_BUSY"

    manager.rollback(operation.operation_id)
    replacement = manager.prepare(str(second))
    manager.rollback(replacement.operation_id)


def test_restart_cleans_prepared_transaction(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    assert operation.temporary_path.exists()

    recovered = transaction_module.DocumentTransactionManager(log_dir)
    assert source.read_bytes() == b"original"
    assert not operation.temporary_path.exists()
    assert not recovered.journal_path.exists()


def test_restart_restores_committed_transaction(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    manager.commit(operation.operation_id)
    assert source.read_bytes() == b"formatted"
    assert operation.backup_path.exists()

    recovered = transaction_module.DocumentTransactionManager(log_dir)
    assert source.read_bytes() == b"original"
    assert not operation.backup_path.exists()
    assert not recovered.journal_path.exists()


def test_preview_binding_uses_sdk_confirmed_host_range(tmp_path):
    source = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph("普通正文内容")
    document.save(source)

    plan = recognize_docx(source, recognition_mode="authoritative")
    result = bind_preview(plan, _snapshot("普通正文内容"))

    assert result["confirmed_count"] >= 1
    eligible = [item for item in result["items"] if item["preview_eligible"]]
    assert eligible
    assert all(item["binding_status"] == "confirmed" for item in eligible)
    assert all(item["host_paragraph_index"] == 0 for item in eligible)
    assert all(item["raw_fragment_sha256"] for item in eligible)


def test_preview_binding_does_not_write_canonical_review_range(tmp_path):
    source = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph("正文\u00a0内容")
    document.save(source)

    plan = recognize_docx(source, recognition_mode="authoritative")
    result = bind_preview(plan, _snapshot("正文 内容"))

    assert result["binding_review_count"] >= 1
    assert not any(item["preview_eligible"] for item in result["items"])


def test_document_log_name_does_not_expose_source_filename(tmp_path):
    source = tmp_path / "private-name.docx"
    source.write_bytes(b"x")
    log_dir = tmp_path / "logs"
    with document_log_context(source, log_dir, "1234567890abcdef") as log_path:
        assert "private-name" not in Path(log_path).name
        assert "document" in Path(log_path).name


def test_file_identity_does_not_expose_path(tmp_path):
    source = tmp_path / "private-name.docx"
    value = file_identity(source)
    assert len(value) == 12
    assert "private-name" not in value


def test_compatibility_warnings_are_json_safe_and_bounded():
    warnings = _safe_warnings([
        "plain warning",
        {"code": "TEST", "count": 2, "nested": {"hidden": True}},
        object(),
    ])
    assert warnings == ["plain warning", {"code": "TEST", "count": 2}]


def test_wps_production_code_does_not_contain_old_second_format_engine():
    root = Path(__file__).resolve().parents[1]
    forbidden = (
        "LocalFormatCommandGenerator",
        "WpsApiDocumentExecutor",
        "paragraph.set_font",
        "paragraph.set_spacing",
        "section.set_page_setup",
    )
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".py", ".js"}:
            continue
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"old formatting engine token {token!r} found in {path}"
