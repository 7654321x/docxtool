"""Split regression tests from the former test_wps_app module (test_wps_control_format.py)."""

# ruff: noqa: F405



from apps.wps.tests.support.wps_app_support import *  # noqa: F401,F403,F405



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

def test_preview_binding_marks_canonical_review_range_as_preview_eligible(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph("正文\u00a0内容")
    document.save(source)

    plan = recognize_docx(source, recognition_mode="authoritative")
    events = []
    monkeypatch.setattr(
        recognition_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields)
        ),
    )
    result = bind_preview(plan, _snapshot("正文 内容"))

    assert result["binding_review_count"] >= 1
    eligible = [item for item in result["items"] if item["preview_eligible"]]
    assert eligible
    assert result["confirmed_count"] == 0
    assert result["preview_eligible_count"] == len(eligible)
    assert all(item["binding_status"] == "review" for item in eligible)
    assert all(item["recommended_action"] == "preview_only" for item in eligible)
    warning_events = [
        fields for event, fields in events if event == "binding.item.warning"
    ]
    assert warning_events
    assert all(fields["warning_code"] == "RAW_TEXT_NORMALIZED" for fields in warning_events)
    assert all(fields["physical_paragraph_index"] == 0 for fields in warning_events)
    assert all(fields["physical_occurrence_index"] == 0 for fields in warning_events)
    assert all(fields["physical_text_length_utf16"] == 5 for fields in warning_events)
    assert all(fields["segment_index"] == 0 for fields in warning_events)
    assert all(fields["segment_count"] == 1 for fields in warning_events)
    assert all(fields["locator_verified"] is True for fields in warning_events)
    assert all(fields["locator_status"] == "confirmed" for fields in warning_events)

def test_preview_binding_keeps_ambiguous_range_unresolved_and_ineligible(tmp_path):
    source = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph("重复内容")
    document.save(source)

    plan = recognize_docx(source, recognition_mode="authoritative")
    snapshot = _snapshot("重复内容")
    duplicate = dict(snapshot["paragraphs"][0])
    duplicate.update(
        host_paragraph_id="main:000001",
        host_paragraph_index=1,
        story_paragraph_index=1,
    )
    snapshot["paragraphs"].append(duplicate)
    result = bind_preview(plan, snapshot)

    assert result["unresolved_count"] >= 1
    assert result["preview_eligible_count"] == 0
    assert not any(item["preview_eligible"] for item in result["items"])

def test_preview_binding_sdk_failure_logs_exact_boundary(tmp_path, monkeypatch):
    source = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph("脱敏正文")
    document.save(source)
    plan = recognize_docx(source)
    events = []
    monkeypatch.setattr(
        recognition_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields)
        ),
    )
    monkeypatch.setattr(
        recognition_module,
        "bind_recognition_plan",
        lambda _plan, _snapshot: (_ for _ in ()).throw(
            recognition_module.DocxToolSdkError(
                "binder failed",
                code="INVALID_RECOGNITION_PLAN",
                details={"path": "$.blocks[1].block_id", "reason": "duplicate_id"},
            )
        ),
    )

    with pytest.raises(RuntimeError, match="WPS_BINDING_SDK_FAILED"):
        recognition_module.bind_preview(plan, {}, request_id="request-binding-fail")

    assert [event for event, _fields in events] == [
        "binding.start",
        "binding.sdk.failed",
    ]
    assert events[-1][1]["request_id"] == "request-binding-fail"
    assert events[-1][1]["error_code"] == "WPS_BINDING_SDK_FAILED"
    assert events[-1][1]["sdk_error_code"] == "INVALID_RECOGNITION_PLAN"
    assert events[-1][1]["sdk_error_path"] == "$.blocks[1].block_id"
    assert events[-1][1]["sdk_error_reason"] == "duplicate_id"

@pytest.mark.parametrize(
    ("case", "expected_event", "expected_code"),
    [
        ("config", "config.load.failed", "WPS_FORMAT_CONFIG_FAILED"),
        ("import", "import.failed", "WPS_FORMAT_IMPORT_FAILED"),
        ("export", "engine.export.failed", "WPS_FORMAT_EXPORT_FAILED"),
        ("integrity", "integrity.validate.failed", "WPS_FORMAT_INTEGRITY_FAILED"),
    ],
)
def test_format_pipeline_failure_logs_exact_stage(
    tmp_path, monkeypatch, case, expected_event, expected_code
):
    source = tmp_path / "source.docx"
    target = tmp_path / "output.docx"
    source.write_bytes(b"source")
    events = []

    class FakeImporter:
        def load(self, *_args, **_kwargs):
            return SimpleNamespace(
                doc_mode="NORMAL",
                paragraphs=[SimpleNamespace(type_id="body")],
            )

    def export_success(*_args, **_kwargs):
        target.write_bytes(b"output")
        return {}

    monkeypatch.setattr(
        format_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields)
        ),
    )
    monkeypatch.setattr(
        format_module,
        "load_rules_and_settings",
        lambda _config: (
            {},
            {},
            {
                "processing": {},
                "numbering": {"enabled": False},
                "punctuation": {"enabled": False},
            },
        ),
    )
    monkeypatch.setattr(format_module, "DocxImporter", FakeImporter)
    monkeypatch.setattr(format_module, "export_doc", export_success)
    monkeypatch.setattr(format_module, "validate_docx_integrity", lambda _path: None)

    if case == "config":
        monkeypatch.setattr(
            format_module,
            "load_rules_and_settings",
            lambda _config: (_ for _ in ()).throw(RuntimeError("config failed")),
        )
    elif case == "import":
        monkeypatch.setattr(
            FakeImporter,
            "load",
            lambda self, *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("import failed")
            ),
        )
    elif case == "export":
        monkeypatch.setattr(
            format_module,
            "export_doc",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("export failed")
            ),
        )
    elif case == "integrity":
        monkeypatch.setattr(
            format_module,
            "validate_docx_integrity",
            lambda _path: (_ for _ in ()).throw(RuntimeError("integrity failed")),
        )

    with pytest.raises(RuntimeError, match=expected_code):
        format_module.format_current_document(
            str(source),
            str(target),
            operation_id="operation-test",
            log_dir=tmp_path / "logs",
            request_id="request-format-fail",
        )

    failure = next(fields for event, fields in events if event == expected_event)
    assert failure["request_id"] == "request-format-fail"
    assert failure["error_code"] == expected_code

def test_wps_one_click_passes_isolated_docxtool_style_profile_to_engine(tmp_path, monkeypatch):
    source = tmp_path / "source.docx"
    target = tmp_path / "output.docx"
    source.write_bytes(b"source")
    captured = {}

    class FakeImporter:
        def load(self, *_args, **_kwargs):
            return SimpleNamespace(
                doc_mode="NORMAL",
                paragraphs=[SimpleNamespace(type_id="body")],
            )

    def fake_export(*_args, **kwargs):
        captured.update(kwargs)
        target.write_bytes(b"output")
        return {}

    monkeypatch.setattr(
        format_module,
        "load_rules_and_settings",
        lambda _config: (
            {},
            {},
            {
                "processing": {},
                "numbering": {"enabled": False},
                "punctuation": {"enabled": False},
            },
        ),
    )
    monkeypatch.setattr(format_module, "DocxImporter", FakeImporter)
    monkeypatch.setattr(format_module, "export_doc", fake_export)
    monkeypatch.setattr(format_module, "validate_docx_integrity", lambda _path: None)

    format_module.format_current_document(
        str(source),
        str(target),
        operation_id="operation-style-profile",
        log_dir=tmp_path / "logs",
        request_id="request-style-profile",
    )

    assert captured["style_profile"] == "wps_docxtool"

def test_wps_one_click_format_rebuilds_heading_numbering_by_default(tmp_path):
    source = tmp_path / "source.docx"
    target = tmp_path / "output.docx"
    document = Document()
    for text in (
        "测试材料",
        "一、第一部分",
        "（六）第二层",
        "5.第三层",
        "（6）第四层",
        "正文内容正文内容正文内容。",
    ):
        document.add_paragraph(text)
    document.save(source)

    format_module.format_current_document(
        str(source),
        str(target),
        operation_id="operation-numbering",
        log_dir=tmp_path / "logs",
        request_id="request-numbering",
    )

    headings = [
        paragraph.text
        for paragraph in Document(target).paragraphs
        if paragraph.style.style_id
        in {"DCT-Heading1", "DCT-Heading2", "DCT-Heading3", "DCT-Heading4"}
    ]
    assert headings == [
        "一、第一部分",
        "（一）第二层",
        "1.第三层",
        "（1）第四层",
    ]
    heading3 = next(
        paragraph
        for paragraph in Document(target).paragraphs
        if paragraph.style.style_id == "DCT-Heading3"
    )
    assert heading3.text == "1.第三层"
    assert all(run.font.bold is True for run in heading3.runs)

def test_wps_page_scope_recognizes_only_selected_source_paragraphs(tmp_path):
    source = tmp_path / "scoped-source.docx"
    target = tmp_path / "scoped-output.docx"
    document = Document()
    document.sections[0].top_margin = 720000
    first = document.add_paragraph("范围外首段")
    first.style = document.styles["Caption"]
    document.add_paragraph("一、范围内标题")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "范围外表格"
    last = document.add_paragraph("范围外末段")
    last.style = document.styles["Quote"]
    document.save(source)
    source_top_margin = Document(source).sections[0].top_margin

    result = format_module.format_current_document(
        str(source),
        str(target),
        operation_id="operation-page-scope",
        log_dir=tmp_path / "logs",
        request_id="request-page-scope",
        host_snapshot=_multi_paragraph_snapshot(
            ["范围外首段", "一、范围内标题", "范围外表格\r\x07", "范围外末段"]
        ),
        selected_host_paragraph_indexes=[1],
    )

    output = Document(target)
    assert result.paragraph_count == 1
    assert result.heading_count == 1
    assert [paragraph.text for paragraph in output.paragraphs] == [
        "范围外首段",
        "一、范围内标题",
        "范围外末段",
    ]
    assert output.paragraphs[0].style.name == "Caption"
    assert output.paragraphs[1].style.style_id == "DCT-Heading1"
    assert output.paragraphs[2].style.name == "Quote"
    assert output.tables[0].cell(0, 0).text == "范围外表格"
    assert output.sections[0].top_margin == source_top_margin

def test_wps_page_scope_rejects_unbound_nonempty_host_paragraph(tmp_path):
    source = tmp_path / "scope-bind-source.docx"
    target = tmp_path / "scope-bind-output.docx"
    document = Document()
    document.add_paragraph("源文档正文")
    document.save(source)

    with pytest.raises(ValueError, match="WPS_FORMAT_SCOPE_BIND_FAILED"):
        format_module.format_current_document(
            str(source),
            str(target),
            operation_id="operation-page-bind-failed",
            log_dir=tmp_path / "logs",
            request_id="request-page-bind-failed",
            host_snapshot=_multi_paragraph_snapshot(["宿主新增正文"]),
            selected_host_paragraph_indexes=[0],
        )

    assert not target.exists()

def test_wps_one_click_rebuilds_native_heading_numbering_from_server_config(tmp_path):
    source = tmp_path / "native-source.docx"
    target = tmp_path / "native-output.docx"
    document = Document()
    document.add_paragraph("测试材料", style="Title")
    document.add_paragraph("正文内容已经开始，并完整说明有关工作情况。")
    _add_native_heading2_numbering(document, "自动编号二级标题")
    document.add_paragraph("后续正文对该标题展开具体说明。")
    document.save(source)

    server_config = load_active_format_profile()["format_config"]
    assert server_config["numbering"]["enabled"] is False
    format_module.format_current_document(
        str(source),
        str(target),
        operation_id="operation-native-numbering",
        log_dir=tmp_path / "logs",
        format_config=server_config,
        request_id="request-native-numbering",
    )

    output = Document(target)
    heading = next(
        paragraph
        for paragraph in output.paragraphs
        if paragraph.style.style_id == "DCT-Heading2"
    )
    assert heading.text == "（一）自动编号二级标题"
    assert heading._p.get_or_add_pPr().find(qn("w:numPr")) is None
    assert heading.runs[0].text == "（一）"
    assert heading.runs[0].bold is True

def test_wps_one_click_format_uses_safe_punctuation_by_default(tmp_path, monkeypatch):
    source = tmp_path / "source.docx"
    target = tmp_path / "output.docx"
    captured = {}
    load_config = format_module.load_rules_and_settings

    def capture_config(config):
        rules, settings, features = load_config(config)
        captured["features"] = features
        return rules, settings, features

    monkeypatch.setattr(format_module, "load_rules_and_settings", capture_config)
    document = Document()
    document.add_paragraph("测试材料")
    document.add_paragraph(
        "请访问 https://example.com/a,b?x=1.2, 并说明:可以吗?"
    )
    document.save(source)

    format_module.format_current_document(
        str(source),
        str(target),
        operation_id="operation-punctuation",
        log_dir=tmp_path / "logs",
        request_id="request-punctuation",
    )

    body_texts = [
        paragraph.text
        for paragraph in Document(target).paragraphs
        if paragraph.style.style_id == "DCT-Body"
    ]
    assert captured["features"]["punctuation"]["enabled"] is True
    assert "请访问 https://example.com/a,b?x=1.2, 并说明：可以吗？" in body_texts

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

def test_wps_log_rejects_document_name_and_document_path():
    fields = sanitize_wps_log_fields(
        {
            "document_name": "sample.docx",
            "source_path": r"C:\\fixtures\\sample.docx",
        }
    )
    assert fields == {}

def test_wps_log_accepts_style_profile_diagnostic():
    assert sanitize_wps_log_fields({"style_profile": "wps_docxtool"}) == {
        "style_profile": "wps_docxtool"
    }
def test_wps_log_accepts_taskpane_scroll_diagnostics():
    fields = sanitize_wps_log_fields(
        {
            "stage": "load_settled",
            "root_scroll_top": 80,
            "body_scroll_top": 80,
            "content_scroll_top": 80,
            "inner_width": 390,
            "inner_height": 720,
            "header_top": -64,
            "header_height": 64,
            "header_clipped_top": True,
            "document_has_focus": True,
            "active_element_tag": "BODY",
            "top_element_id": "taskpane_header",
            "scheduled_delay_ms": 100,
            "timer_drift_ms": 4,
            "state_wait_in_flight": True,
        }
    )
    assert fields == {
        "stage": "load_settled",
        "root_scroll_top": 80,
        "body_scroll_top": 80,
        "content_scroll_top": 80,
        "inner_width": 390,
        "inner_height": 720,
        "header_top": -64,
        "header_height": 64,
        "header_clipped_top": True,
        "document_has_focus": True,
        "active_element_tag": "BODY",
        "top_element_id": "taskpane_header",
        "scheduled_delay_ms": 100,
        "timer_drift_ms": 4,
        "state_wait_in_flight": True,
    }

def test_wps_log_accepts_taskpane_host_properties():
    fields = sanitize_wps_log_fields(
        {
            "page_version": "7",
            "pane_branch": "created",
            "pane_dock_position": 2,
            "pane_expected_dock_position": 2,
            "pane_found": True,
            "pane_id": "1",
            "pane_visible": True,
            "pane_width": 390,
        }
    )
    assert fields == {
        "page_version": "7",
        "pane_branch": "created",
        "pane_dock_position": 2,
        "pane_expected_dock_position": 2,
        "pane_found": True,
        "pane_id": "1",
        "pane_visible": True,
        "pane_width": 390,
    }

def test_wps_log_accepts_taskpane_transition_diagnostics():
    fields = sanitize_wps_log_fields(
        {
            "checkpoint": "after_target_activated",
            "observed_delay_ms": 500,
            "active_document_present": True,
            "active_window_present": True,
            "document_matches_expected": True,
            "pane_width_before": 640,
            "pane_width_requested": 390,
            "pane_width_after": 325,
            "pane_width_effective": False,
            "window_screen_x": 80,
            "window_screen_y": 120,
            "screen_width": 1920,
            "screen_avail_height": 1040,
            "physical_header_height": 104,
            "window_top_is_self": True,
            "frame_element_present": False,
            "header_transform": "none",
            "source_path": r"C:\\fixtures\\sample.docx",
        }
    )
    assert fields == {
        "checkpoint": "after_target_activated",
        "observed_delay_ms": 500,
        "active_document_present": True,
        "active_window_present": True,
        "document_matches_expected": True,
        "pane_width_before": 640,
        "pane_width_requested": 390,
        "pane_width_after": 325,
        "pane_width_effective": False,
        "window_screen_x": 80,
        "window_screen_y": 120,
        "screen_width": 1920,
        "screen_avail_height": 1040,
        "physical_header_height": 104,
        "window_top_is_self": True,
        "frame_element_present": False,
        "header_transform": "none",
    }

def test_wps_log_accepts_bridge_diagnostics():
    fields = sanitize_wps_log_fields(
        {
            "bridge_ready": True,
            "command_sequence": 3,
            "generation_changed": False,
            "host_generation": 2,
            "replaced": True,
            "state_revision": 9,
            "wait_timed_out": False,
        }
    )
    assert fields == {
        "bridge_ready": True,
        "command_sequence": 3,
        "generation_changed": False,
        "host_generation": 2,
        "replaced": True,
        "state_revision": 9,
        "wait_timed_out": False,
    }
