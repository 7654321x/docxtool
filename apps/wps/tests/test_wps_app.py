from __future__ import annotations

import http.client
import json
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import threading
from types import SimpleNamespace

import pytest
from docx import Document

import apps.wps.main as wps_main
from apps.wps.control import logging_adapter
from apps.wps.control import server as server_module
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


def test_stale_transaction_recovery_logs_lifecycle(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    events = []
    monkeypatch.setattr(
        transaction_module,
        "log_event",
        lambda _level, _component, event, _message, _fields=None: events.append(event),
    )

    transaction_module.DocumentTransactionManager(log_dir)

    assert events == [
        "transaction.recovery.start",
        "transaction.recovery.completed",
    ]
    assert not operation.temporary_path.exists()


def test_invalid_stale_transaction_logs_recovery_failure(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "transaction-state.json").write_text("{}", encoding="utf-8")
    events = []
    monkeypatch.setattr(
        transaction_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append((event, fields)),
    )

    with pytest.raises(transaction_module.DocumentTransactionError):
        transaction_module.DocumentTransactionManager(tmp_path / "logs")

    assert [event for event, _fields in events] == [
        "transaction.recovery.start",
        "transaction.recovery.failed",
    ]
    assert events[-1][1]["error_code"] == "WPS_TRANSACTION_JOURNAL_INVALID"


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


def test_wps_bootstrap_structure_is_explicit():
    root = Path(__file__).resolve().parents[1]
    index_source = (root / "index.html").read_text(encoding="utf-8")
    assert './main.js' in index_source
    for token in (
        "runtime/runtime-config.js",
        "js/bootstrap-log.js",
        "js/ribbon.js",
        "host-runtime.js",
        "taskpane.js",
        "PluginStorage",
        "Application",
        "fetch(",
        "runPreview",
        "runFormat",
        "buildHostSnapshot",
        "OnAddinLoad",
        "OnAction",
    ):
        assert token not in index_source

    main_source = (root / "main.js").read_text(encoding="utf-8")
    for token in (
        "runPreview",
        "runFormat",
        "buildHostSnapshot",
        "applyPreviewComments",
        "pollTaskpaneRequests",
        "DocxImporter",
    ):
        assert token not in main_source
    expected_order = (
        "js/bootstrap-log.js",
        "runtime/runtime-config.js",
        "host-runtime.js",
        "js/ribbon.js",
        "js/bootstrap-complete.js",
    )
    for source in expected_order:
        assert source in main_source
    positions = [main_source.index(source) for source in expected_order]
    assert positions == sorted(positions)
    assert "document.write(" in main_source
    assert "Promise" not in main_source
    assert "async " not in main_source
    assert "defer" not in main_source

    ribbon_source = (root / "js" / "ribbon.js").read_text(encoding="utf-8")
    for callback in ("OnAddinLoad", "OnAction", "GetActionEnabled"):
        assert re.search(rf"^function {callback}\(", ribbon_source, re.MULTILINE)
    assert "window.DocxToolHostRuntime.start()" in ribbon_source


def test_wps_logging_uses_ten_mib_rotating_file(tmp_path):
    logging_adapter.configure_wps_logging(tmp_path)
    handler = logging_adapter._WPS_FILE_HANDLER
    try:
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == 10 * 1024 * 1024
        assert handler.backupCount == 5
        assert handler.encoding.lower().replace("-", "") == "utf8"
    finally:
        if handler is not None:
            logging_adapter.LOGGER.removeHandler(handler)
            handler.close()
            logging_adapter._WPS_FILE_HANDLER = None


def test_control_request_id_header_reaches_dispatch(monkeypatch, tmp_path):
    observed = []

    def fake_dispatch(self, path, body, request_id=""):
        observed.append((path, body, request_id))
        return {"status": "ok"}

    monkeypatch.setattr(server_module.WpsControlApplication, "dispatch", fake_dispatch)
    server = server_module.create_server(tmp_path, "test-token", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        connection.request(
            "POST",
            "/v1/recognize",
            body=json.dumps({"source_path": "ignored"}),
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
                "X-DocxTool-Request-Id": "pane-request-123",
            },
        )
        response = connection.getresponse()
        response.read()
        assert response.status == 200
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert observed == [
        ("/v1/recognize", {"source_path": "ignored"}, "pane-request-123")
    ]


def test_control_recognize_and_bind_logs_keep_request_id(monkeypatch, tmp_path):
    application = object.__new__(server_module.WpsControlApplication)
    application.log_dir = tmp_path
    application._remember_plan = lambda _plan: None
    application._get_plan = lambda _plan_id: object()
    events = []
    monkeypatch.setattr(
        server_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append((event, fields)),
    )
    monkeypatch.setattr(
        server_module,
        "recognize_document",
        lambda *_args, **_kwargs: SimpleNamespace(
            plan=object(), public_result={"block_count": 3}
        ),
    )
    monkeypatch.setattr(
        server_module,
        "bind_preview",
        lambda _plan, _snapshot: {"confirmed_count": 2, "unresolved_count": 1},
    )

    application.dispatch("/v1/recognize", {}, request_id="request-42")
    application.dispatch(
        "/v1/recognize/bind",
        {"plan_id": "plan", "host_snapshot": {}},
        request_id="request-42",
    )

    assert [event for event, _fields in events] == [
        "recognize.request.start",
        "recognize.request.completed",
        "bind.request.start",
        "bind.request.completed",
    ]
    assert all(fields["request_id"] == "request-42" for _event, fields in events)


def test_verify_files_requires_new_bootstrap_files(monkeypatch, tmp_path):
    monkeypatch.setattr(wps_main, "APP_ROOT", tmp_path)
    for relative in (
        "package.json",
        "manifest.xml",
        "ribbon.xml",
        "index.html",
        "main.js",
        "js/bootstrap-log.js",
        "js/bootstrap-complete.js",
        "js/ribbon.js",
        "host-runtime.js",
        "taskpane.html",
        "taskpane.js",
        "control/server.py",
        "control/format_current_document.py",
        "control/document_transaction.py",
        "control/logging_adapter.py",
        "control/recognize_document.py",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        '{"devDependencies":{"wpsjs":"2.2.3"},'
        '"overrides":{"wpsjs-rpc-sdk-new":"1.1.0"}}',
        encoding="utf-8",
    )

    wps_main.verify_files()


def test_start_handles_keyboard_interrupt_without_traceback(monkeypatch):
    events = []

    class FakeServer:
        def serve_forever(self, **_kwargs):
            return None

        def shutdown(self):
            events.append("shutdown")

        def server_close(self):
            events.append("close")

    class FakeThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            events.append("thread-start")

        def join(self, timeout):
            events.append(("join", timeout))

    monkeypatch.setattr(wps_main, "verify_files", lambda: None)
    monkeypatch.setattr(wps_main, "configure_wps_logging", lambda _root: None)
    monkeypatch.setattr(wps_main, "_wpsjs_command", lambda: ["wpsjs"])
    monkeypatch.setattr(wps_main, "_start_control", lambda _port: (FakeServer(), 45678))
    monkeypatch.setattr(wps_main.threading, "Thread", FakeThread)
    monkeypatch.setattr(wps_main.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(wps_main, "clear_runtime_config", lambda: events.append("clear"))
    monkeypatch.setattr(wps_main, "log_event", lambda _level, _component, event, _message, _fields=None: events.append(event))

    wps_main.start(0)

    assert "launcher.interrupt.received" in events
    assert events[-1] == "launcher.session.stop"


def test_wps_diagnostic_event_contract_is_present():
    root = Path(__file__).resolve().parents[1]
    sources = {
        "main": (root / "main.js").read_text(encoding="utf-8"),
        "ribbon": (root / "js" / "ribbon.js").read_text(encoding="utf-8"),
        "host": (root / "host-runtime.js").read_text(encoding="utf-8"),
        "taskpane": (root / "taskpane.js").read_text(encoding="utf-8"),
    }
    expected = {
        "main": (
            "bootstrap.main.loaded",
            '"bootstrap." + label + ".load.start"',
            '"bootstrap." + label + ".loaded"',
            '"bootstrap." + label + ".failed"',
            '"bootstrap_log"',
            '"runtime_config"',
            '"ribbon"',
            '"host_runtime"',
        ),
        "ribbon": (
            "ribbon.addin.load.enter",
            "ribbon.addin.host_start.call",
            "ribbon.addin.host_start.returned",
            "ribbon.addin.load.completed",
            "ribbon.addin.load.failed",
        ),
        "host": (
            "host.start.enter",
            "host.start.failed",
            "host.poll.started",
            "host.storage.request.observed",
            "host.request.parsed",
            "host.request.ignored",
            "host.request.claimed",
            "preview.start",
            "preview.document_path.wait.start",
            "preview.document_path.wait.completed",
            "preview.document_path.wait.failed",
            "preview.range_validation.start",
            "preview.range_validation.completed",
            "preview.range_validation.failed",
            "preview.comment_cleanup.item.failed",
            "preview.completed",
            "preview.failed",
            "format.start",
            "format.completed",
            "format.failed",
            "transaction.recovery.start",
            "transaction.recovery.completed",
            "transaction.recovery.failed",
        ),
        "taskpane": (
            "taskpane.request.prepare",
            "taskpane.storage.write.start",
            "taskpane.storage.write.completed",
            "taskpane.storage.write.verified",
            "taskpane.request.created",
        ),
    }
    for source_name, events in expected.items():
        for event in events:
            assert event in sources[source_name], f"missing {event} in {source_name}"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["main.py"], "start"),
        (["main.py", "start"], "start"),
        (["main.py", "control"], "control"),
        (["main.py", "verify"], "verify"),
    ],
)
def test_main_action_defaults_and_routes(monkeypatch, argv, expected):
    calls = []

    def fake_start(port):
        calls.append(("start", port))

    def fake_control(port):
        calls.append(("control", port))

    def fake_verify():
        calls.append(("verify",))

    monkeypatch.setattr(wps_main, "start", fake_start)
    monkeypatch.setattr(wps_main, "control_only", fake_control)
    monkeypatch.setattr(wps_main, "verify_files", fake_verify)
    monkeypatch.setattr(wps_main.sys, "argv", argv)

    assert wps_main.main() == 0
    if expected == "start":
        assert calls == [("start", wps_main.DEFAULT_PORT)]
    elif expected == "control":
        assert calls == [("control", wps_main.DEFAULT_PORT)]
    else:
        assert calls == [("verify",)]
