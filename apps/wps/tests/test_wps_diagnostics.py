"""Split regression tests from the former test_wps_app module (test_wps_diagnostics.py)."""

# ruff: noqa: F405



from apps.wps.tests.support.wps_app_support import *  # noqa: F401,F403,F405



def test_ribbon_only_keeps_the_taskpane_entry():
    ribbon_path = Path(__file__).resolve().parents[1] / "ribbon.xml"
    root = ElementTree.parse(ribbon_path).getroot()
    namespace = {"ui": "http://schemas.microsoft.com/office/2006/01/customui"}
    buttons = root.findall(".//ui:button", namespace)
    assert [(button.get("id"), button.get("label")) for button in buttons] == [
        ("panel", "打开侧边栏")
    ]
    assert buttons[0].get("getImage") == "GetImage"
    icon_path = ribbon_path.parent / "images" / "taskpane.svg"
    icon_root = ElementTree.parse(icon_path).getroot()
    assert icon_root.tag == "{http://www.w3.org/2000/svg}svg"
    assert icon_root.get("viewBox") == "0 0 24 24"

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
        "runtime/config",
        "js/bootstrap-log.js",
        "host-runtime.js",
        "js/ribbon.js",
        "js/bootstrap-complete.js",
    )
    for source in expected_order:
        assert source in main_source
    positions = [main_source.index(source) for source in expected_order]
    assert positions == sorted(positions)
    assert "document.write(" not in main_source
    assert "response.json()" in main_source
    assert "document.createElement(\"script\")" in main_source
    assert "?v=" not in main_source
    assert "async " in main_source

    ribbon_source = (root / "js" / "ribbon.js").read_text(encoding="utf-8")
    for callback in ("onAddinLoad", "onAction", "getActionEnabled", "getImage"):
        assert re.search(rf"^function {callback}\(", ribbon_source, re.MULTILINE)
    assert 'return "images/taskpane.svg"' in ribbon_source
    assert "window.DocxToolHostRuntime.start()" in ribbon_source

def test_wps_logging_uses_ten_mib_rotating_file(tmp_path):
    logging_adapter.configure_wps_logging(tmp_path)
    handler = logging_adapter._WPS_FILE_HANDLER
    try:
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == 10 * 1024 * 1024
        assert handler.backupCount == 5
        assert handler.encoding.lower().replace("-", "") == "utf8"
        logging_adapter.log_event("INFO", "test", "log.info", "normal-message")
        logging_adapter.log_event("WARNING", "test", "log.warning", "warning-message")
        logging_adapter.log_event("ERROR", "test", "log.error", "error-message")
        handler.flush()
        content = Path(handler.baseFilename).read_text(encoding="utf-8")
        assert "normal-message" in content
        assert "warning-message" in content
        assert "error-message" in content
        assert "\x1b[" not in content
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

@pytest.mark.parametrize(
    ("case", "path", "body", "token", "headers", "expected_status", "expected_code", "expected_event"),
    [
        (
            "unauthorized",
            "/v1/recognize",
            b"{}",
            "wrong-token",
            {},
            401,
            "WPS_CONTROL_UNAUTHORIZED",
            "control.auth.rejected",
        ),
        (
            "invalid-content-length",
            "/v1/recognize",
            b"",
            "test-token",
            {"Content-Length": "invalid"},
            400,
            "WPS_CONTROL_INVALID_CONTENT_LENGTH",
            "control.body.length_invalid",
        ),
        (
            "negative-content-length",
            "/v1/recognize",
            b"",
            "test-token",
            {"Content-Length": "-1"},
            400,
            "WPS_CONTROL_NEGATIVE_CONTENT_LENGTH",
            "control.body.length_negative",
        ),
        (
            "body-too-large",
            "/v1/recognize",
            b"",
            "test-token",
            {"Content-Length": str(server_module.MAX_BODY_BYTES + 1)},
            400,
            "WPS_CONTROL_REQUEST_TOO_LARGE",
            "control.body.too_large",
        ),
        (
            "invalid-json",
            "/v1/recognize",
            b"{",
            "test-token",
            {},
            400,
            "WPS_CONTROL_JSON_INVALID",
            "control.body.json_invalid",
        ),
        (
            "json-object-required",
            "/v1/recognize",
            b"[]",
            "test-token",
            {},
            400,
            "WPS_CONTROL_JSON_OBJECT_REQUIRED",
            "control.body.object_required",
        ),
        (
            "route-not-found",
            "/v1/missing",
            b"{}",
            "test-token",
            {},
            404,
            "WPS_CONTROL_ROUTE_NOT_FOUND",
            "control.route.not_found",
        ),
    ],
)
def test_control_boundaries_have_distinct_events(
    monkeypatch,
    tmp_path,
    case,
    path,
    body,
    token,
    headers,
    expected_status,
    expected_code,
    expected_event,
):
    events = []
    monkeypatch.setattr(
        server_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields or {})
        ),
    )
    server = server_module.create_server(tmp_path / case, "test-token", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _control_post(
            server, path, body=body, token=token, headers=headers
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert status == expected_status
    assert payload == {"ok": False, "error_code": expected_code}
    matching = [fields for event, fields in events if event == expected_event]
    assert len(matching) == 1
    assert matching[0]["error_code"] == expected_code
    assert not any(
        event == "control.request.execution_failed" for event, _fields in events
    )

@pytest.mark.parametrize(
    ("monitor_state", "expected_code", "expected_event"),
    [
        ("busy", "WPS_COMMAND_BUSY", "control.command.busy"),
        ("stopped", "WPS_MONITOR_NOT_RUNNING", "control.monitor.unavailable"),
    ],
)
def test_control_monitor_boundaries_have_distinct_events(
    monkeypatch, tmp_path, monitor_state, expected_code, expected_event
):
    events = []
    monkeypatch.setattr(
        server_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields or {})
        ),
    )
    server = server_module.create_server(tmp_path / monitor_state, "test-token", 0)
    if monitor_state == "busy":
        with server.command_monitor._lock:
            server.command_monitor._occupied = True
    else:
        server.command_monitor.stop()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _control_post(server, "/v1/recognize")
    finally:
        if monitor_state == "busy":
            with server.command_monitor._lock:
                server.command_monitor._occupied = False
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert status == 400
    assert payload == {"ok": False, "error_code": expected_code}
    matching = [fields for event, fields in events if event == expected_event]
    assert len(matching) == 1
    assert matching[0]["error_code"] == expected_code

def test_log_route_emits_only_the_submitted_diagnostic_event(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(
        server_module,
        "log_event",
        lambda _level, component, event, _message, fields=None: events.append(
            (component, event, fields or {})
        ),
    )
    server = server_module.create_server(tmp_path, "test-token", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=5
    )
    try:
        body = json.dumps(
            {
                "level": "WARNING",
                "component": "taskpane",
                "event": "taskpane.request.blocked",
                "message": "blocked",
                "details": {
                    "request_id": "request-42",
                    "reason": "context_not_ready",
                },
            }
        )
        connection.request(
            "POST",
            "/v1/log",
            body=body,
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        response.read()
        assert response.status == 200
        submitted_events = list(events)
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert submitted_events == [
        (
            "taskpane",
            "taskpane.request.blocked",
            {"request_id": "request-42", "reason": "context_not_ready"},
        )
    ]

def test_log_detail_contract_keeps_diagnostics_and_rejects_sensitive_fields():
    details = server_module._safe_log_details(
        {
            "request_id": "request-42",
            "event_sequence": 9,
            "reason": "context_not_ready",
            "request_status": "BLOCKED",
            "host_ready": True,
            "host_instance_id_short": "host-1234abcd",
            "physical_paragraph_index": 12,
            "physical_occurrence_index": 1,
            "physical_text_length_utf16": 48,
            "segment_index": 0,
            "segment_count": 2,
            "locator_verified": True,
            "locator_status": "confirmed",
            "document_id_short": "doc-1234",
            "operation_id_short": "operation-12",
            "plan_id_short": "plan-1234",
            "characters_count": 85,
            "first_ordinal": 0,
            "end_ordinal": 86,
            "first_boundary_present": True,
            "last_boundary_present": False,
            "set_range_available": True,
            "body": "private body",
            "source_path": "C:/private/document.docx",
            "raw_text": "private body",
            "session_token": "secret",
            "sha256": "f" * 64,
            "traceback": "private traceback",
        }
    )

    assert details == {
        "request_id": "request-42",
        "event_sequence": 9,
        "reason": "context_not_ready",
        "request_status": "BLOCKED",
        "host_ready": True,
        "host_instance_id_short": "host-1234abcd",
        "physical_paragraph_index": 12,
        "physical_occurrence_index": 1,
        "physical_text_length_utf16": 48,
        "segment_index": 0,
        "segment_count": 2,
        "locator_verified": True,
        "locator_status": "confirmed",
        "document_id_short": "doc-1234",
        "operation_id_short": "operation-12",
        "plan_id_short": "plan-1234",
        "characters_count": 85,
        "first_ordinal": 0,
        "end_ordinal": 86,
        "first_boundary_present": True,
        "last_boundary_present": False,
        "set_range_available": True,
    }
    assert server_module._safe_log_details({"path": "/v1/health"}) == {
        "path": "/v1/health"
    }
    assert server_module._safe_log_details(
        {"path": "C:/private/document.docx"}
    ) == {}

def test_python_log_field_contract_rejects_sensitive_values():
    fields = logging_adapter._fields_text(
        {
            "request_id": "request-42",
            "error_code": "WPS_TEST_FAILED",
            "body": "private body",
            "source_path": "C:/private/document.docx",
            "raw_text": "private body",
            "session_token": "secret",
            "sha256": "f" * 64,
            "traceback": "private traceback",
        }
    )

    assert "request_id=request-42" in fields
    assert "error_code=WPS_TEST_FAILED" in fields
    assert "private" not in fields
    assert "secret" not in fields
    assert "traceback" not in fields

def test_python_log_field_contract_keeps_safe_sdk_validation_details():
    fields = sanitize_wps_log_fields(
        {
            "sdk_error_code": "INVALID_RECOGNITION_PLAN",
            "sdk_error_path": "$.blocks[1].block_id",
            "sdk_error_reason": "duplicate_id",
            "raw_text": "private body",
        }
    )

    assert fields == {
        "sdk_error_code": "INVALID_RECOGNITION_PLAN",
        "sdk_error_path": "$.blocks[1].block_id",
        "sdk_error_reason": "duplicate_id",
    }
    assert "C:/private" not in logging_adapter._fields_text(
        {"path": "C:/private/document.docx"}
    )
    assert "path=/v1/health" in logging_adapter._fields_text({"path": "/v1/health"})

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
        lambda _plan, _snapshot, request_id="": {
            "confirmed_count": 2,
            "unresolved_count": 1,
        },
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

def test_wps_request_context_and_preview_safety_contracts_are_present():
    root = Path(__file__).resolve().parents[1]
    host = (root / "host-runtime.js").read_text(encoding="utf-8")
    taskpane = (root / "taskpane.js").read_text(encoding="utf-8")

    assert "currentRequestId" not in host
    for token in (
        'schema_version !== "wps-command-v2"',
        "/v1/bridge/host/register",
        "/v1/bridge/host/wait",
        "/v1/bridge/state",
        "hostContextId",
    ):
        assert token in host
    for token in (
        "/v1/bridge/command",
        "/v1/bridge/state/wait",
        "hostGeneration",
        "stateRevision",
        "pendingRequestId",
        "REQUEST_ACK_TIMEOUT",
    ):
        assert token in taskpane
    for token in (
        "host.bridge.command.schema_invalid",
        "host.bridge.command.request_id_missing",
        "host.bridge.command.command_missing",
        "taskpane.request.completed",
        "host.start.rollback",
        "PREVIEW_DOCUMENT_CHANGED",
        "preview.range.revalidate.failed",
        "document.context.changed",
        "taskpane.rebuild.failed",
    ):
        assert token in host
    assert "config.sessionId" not in host
    assert "config.sessionId" not in taskpane
    for obsolete in (
        "wps-request-v2",
        "docxtool_wps_state_v1",
        "docxtool_wps_request_v1",
        "setInterval(",
    ):
        assert obsolete not in host
        assert obsolete not in taskpane
    assert host.index("range = await previewRange(document, item)") < host.index("comments.Add(range")

def test_wps_entry_registers_ribbon_bridges_before_loading_children():
    root = Path(__file__).resolve().parents[1]
    main_source = (root / "main.js").read_text(encoding="utf-8")
    ribbon_source = (root / "js" / "ribbon.js").read_text(encoding="utf-8")

    first_child_load = main_source.index('loadScript("js/bootstrap-log.js"')
    for callback in ("OnAddinLoad", "OnAction", "GetActionEnabled", "GetImage"):
        declaration = main_source.index(f"function {callback}(")
        assert declaration < first_child_load
    assert "DocxToolRibbonCallbacks" in main_source
    assert "window.DocxToolRibbonCallbacks" in ribbon_source

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
                "bootstrap.runtime_config.load.start",
                "bootstrap.runtime_config.loaded",
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
            "host.start.lazy.enter",
            "host.start.lazy.scheduled",
            "host.start.lazy.failed",
            "host.start.failed",
            "host.bridge.register.start",
            "host.bridge.register.completed",
            "host.bridge.wait.started",
            "host.bridge.wait.failed",
            "host.bridge.command.received",
            "host.bridge.state.published",
            "host.bridge.state.publish_failed",
            "host.bridge.state.flush_failed",
            "taskpane.storage_id.read_failed",
            "taskpane.storage_id.write_failed",
            "taskpane.create_call.failed",
            "taskpane.show.failed",
            "taskpane.width.failed",
            "document.format.detected",
            "document.upgrade.start",
            "document.upgrade.save_as.failed",
            "document.upgrade.verify.failed",
            "document.upgrade.publish.start",
            "document.upgrade.reopen.failed",
            "document.upgrade.completed",
            "document.upgrade.rollback.failed",
            "document.upgrade.rollback.completed",
            "preview.start",
            "preview.document_path.wait.start",
            "preview.document_path.wait.completed",
            "preview.document_path.wait.failed",
            "preview.range_selection.start",
            "preview.range_selection.completed",
            "preview.range.binding_unconfirmed",
            "preview.range.paragraph_unresolved",
            "preview.range.offset_invalid",
            "preview.range.paragraph_lookup_failed",
            "preview.range.paragraph_missing",
            "preview.range.paragraph_text_failed",
            "preview.range.paragraph_changed",
            "preview.range.fragment_mismatch",
            "preview.range.characters_unsupported",
            "preview.range.utf16_boundary_invalid",
            "preview.range.character_lookup_failed",
            "preview.range.boundary_invalid",
            "preview.range.set_failed",
            "preview.range.readback_failed",
            "preview.range.readback_mismatch",
            "preview.comment.create_call.failed",
            "preview.comment.create_result.empty",
            "preview.comment.metadata.failed",
            "preview.session.write_failed",
            "preview.comment_cleanup.item.failed",
            "preview.comments.rollback.completed",
            "preview.comments.rollback.failed",
            "preview.completed",
            "preview.failed",
            "format.start",
            "format.completed",
            "format.failed",
            "transaction.recovery.start",
            "transaction.recovery.completed",
            "transaction.recovery.failed",
            "host.command.failure_state.failed",
            "host.command.failure_panel_open.failed",
            "ribbon.invalidate.failed",
            "log.transport.unavailable",
        ),
        "taskpane": (
            "taskpane.request.prepare",
            "taskpane.request.blocked.busy",
            "taskpane.request.blocked.host_not_ready",
            "taskpane.request.claimed",
            "taskpane.request.completed",
            "taskpane.bridge.command.submit.start",
            "taskpane.bridge.command.submit.completed",
            "taskpane.bridge.command.submit.failed",
            "taskpane.bridge.state.wait.started",
            "taskpane.bridge.state.received",
            "taskpane.bridge.state.wait.failed",
            "taskpane.bridge.state.wait.stopped",
            "taskpane.bridge.host_generation.changed",
            "taskpane.load.failed",
            "log.transport.unavailable",
        ),
    }
    for source_name, events in expected.items():
        for event in events:
            assert event in sources[source_name], f"missing {event} in {source_name}"
def test_wps_python_diagnostic_event_contract_is_present():
    root = Path(__file__).resolve().parents[1]
    sources = {
        "monitor": (root / "control" / "monitor.py").read_text(encoding="utf-8"),
        "server": (
            (root / "control" / "server.py").read_text(encoding="utf-8")
            + (root / "control" / "transport" / "protocol.py").read_text(
                encoding="utf-8"
            )
        ),
        "recognition": (root / "control" / "recognize_document.py").read_text(
            encoding="utf-8"
        ),
        "format": (root / "control" / "format_current_document.py").read_text(
            encoding="utf-8"
        ),
        "transaction": (root / "control" / "document_transaction.py").read_text(
            encoding="utf-8"
        ),
        "launcher": (root / "main.py").read_text(encoding="utf-8"),
    }
    expected = {
        "monitor": (
            "monitor.thread.started",
            "monitor.thread.crashed",
            "monitor.command.received",
            "monitor.command.queued",
            "monitor.command.started",
            "monitor.command.completed",
            "monitor.command.failed",
            "monitor.command.busy",
            "monitor.command.unavailable",
        ),
        "server": (
            "bridge.host.registered",
            "bridge.host.replaced",
            "bridge.command.enqueued",
            "bridge.command.delivered",
            "bridge.state.published",
            "bridge.waiters.closed",
            "control.auth.rejected",
            "control.body.length_invalid",
            "control.body.length_negative",
            "control.body.too_large",
            "control.body.truncated",
            "control.body.json_invalid",
            "control.body.object_required",
            "control.route.not_found",
            "control.response.write_failed",
            "format.upgrade.prepare_converted.request.start",
            "format.upgrade.prepare_converted.request.failed",
            "format.upgrade.prepare_converted.request.completed",
        ),
        "recognition": (
            "recognition.input.invalid",
            "recognition.start",
            "recognition.pipeline.failed",
            "recognition.completed",
            "binding.start",
            "binding.sdk.failed",
            "binding.block_missing",
            "binding.item",
            "binding.item.warning",
            "binding.completed",
        ),
        "format": (
            "input.source.invalid",
            "input.output.invalid",
            "input.path_collision",
            "config.load.failed",
            "config.processing.invalid",
            "import.failed",
            "engine.export.failed",
            "integrity.validate.failed",
            "pipeline.completed",
        ),
        "transaction": (
            "prepare.rejected.busy",
            "prepare.source_hash.failed",
            "prepare.output_hash.failed",
            "prepare.source_changed",
            "upgrade.prepare_converted.start",
            "upgrade.prepare_converted.copy.failed",
            "upgrade.prepare_converted.completed",
            "commit.source.missing",
            "commit.source.changed",
            "commit.output.missing",
            "backup.copy.failed",
            "backup.verify.failed",
            "source.replace.failed",
            "source.replace.verify_failed",
            "finalize.cleanup.failed",
            "rollback.backup.missing",
            "rollback.backup.mismatch",
            "rollback.source.ambiguous",
            "rollback.temporary_cleanup.failed",
            "rollback.source_replace.failed",
            "rollback.backup_cleanup.failed",
            "rollback.journal_clear.failed",
            "transaction.journal.read.failed",
            "transaction.journal.parse.failed",
            "transaction.journal.schema.invalid",
            "transaction.journal.paths.invalid",
            "transaction.journal.hashes.invalid",
            "transaction.recovery.source_state.failed",
            "transaction.recovery.temporary_state.failed",
            "transaction.recovery.backup_state.failed",
            "transaction.recovery.prepared_state.invalid",
            "transaction.recovery.committed_state.invalid",
            "transaction.recovery.state.invalid",
            "transaction.recovery.temporary_cleanup.failed",
            "transaction.recovery.source_restore.failed",
            "transaction.recovery.backup_cleanup.failed",
            "transaction.recovery.journal_clear.failed",
            "transaction.recovery.failed",
        ),
        "launcher": (
            "launcher.control.create.failed",
            "launcher.runtime_config.publish.start",
            "launcher.runtime_config.publish.completed",
            "launcher.publish.parse.failed",
            "launcher.publish.schema.failed",
            "launcher.publish.write.failed",
            "launcher.web.create.failed",
            "launcher.web.previous_service.detected",
            "launcher.web.previous_service.stop.failed",
            "launcher.web.previous_service.stop.completed",
            "launcher.web.serve.failed",
            "launcher.control.thread.failed",
            "launcher.account_runtime.stop.failed",
            "launcher.web.close.failed",
            "launcher.control.shutdown.failed",
            "launcher.control.close.failed",
            "launcher.control.thread.join.failed",
            "launcher.control.thread.state_check.failed",
            "launcher.control.thread.stop_timeout",
            "launcher.runtime_config.cleanup.failed",
        ),
    }
    for source_name, events in expected.items():
        for event in events:
            assert event in sources[source_name], f"missing {event} in {source_name}"
