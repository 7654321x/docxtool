from __future__ import annotations

from pathlib import Path

import pytest

from apps.wps.control import document_transaction as transaction_module
from apps.wps.control.format_current_document import FormatResult
from apps.wps.control.logging_adapter import file_identity


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


def test_transaction_commit_then_rollback_restores_original(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    assert source.read_bytes() == b"original"
    assert operation.temporary_path.read_bytes() == b"formatted"

    manager.commit(operation.operation_id)
    assert source.read_bytes() == b"formatted"
    assert operation.backup_path.read_bytes() == b"original"

    manager.rollback(operation.operation_id)
    assert source.read_bytes() == b"original"


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


def test_file_identity_does_not_expose_path(tmp_path):
    source = tmp_path / "private-name.docx"
    value = file_identity(source)
    assert len(value) == 12
    assert "private-name" not in value


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
