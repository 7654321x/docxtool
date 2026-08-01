from __future__ import annotations

from pathlib import Path

from docxtool.application.process_document import process_uploaded_docx_task


class _Paragraph:
    """保存段落最终类型，模拟应用层统计需要的最小段落对象。"""

    def __init__(self, type_id: str) -> None:
        self.type_id = type_id


class _DocData:
    """保存文档模式和段落列表，模拟 Importer 返回的文档数据。"""

    doc_mode = "NORMAL"
    paragraphs = [_Paragraph("heading1"), _Paragraph("body")]


class _StyleRule:
    """模拟样式规则对象，提供正文日志需要的字体和字号字段。"""

    font = "仿宋_GB2312"
    font_size_label = "三号"

    @classmethod
    def default_for_row(cls, _index: int):
        """传入配置行号，返回默认样式规则对象。"""
        return cls()


class _PageSettings:
    """模拟页面设置对象，提供任务日志需要的页边距和行距字段。"""

    margin_top_cm = 3.7
    margin_bottom_cm = 3.5
    margin_left_cm = 2.8
    margin_right_cm = 2.6
    line_spacing_value = 28


class _IntegrityError(Exception):
    """模拟 DOCX 完整性错误，携带稳定错误码和脱敏消息。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _Logger:
    """收集应用层日志消息，避免测试输出真实日志。"""

    def __init__(self) -> None:
        self.infos: list[str] = []
        self.errors: list[tuple] = []

    def info(self, message: str) -> None:
        """传入日志文本，记录 info 级别消息。"""
        self.infos.append(message)

    def error(self, *args) -> None:
        """传入日志参数，记录 error 级别消息。"""
        self.errors.append(args)


def _process_task(tmp_path: Path, **overrides):
    """传入临时目录和覆盖依赖，执行应用层任务并返回结果、状态和日志对象。"""
    output_root = tmp_path / "outputs"
    log_dir = tmp_path / "logs"
    logger = _Logger()
    state = {"reset_tokens": [], "export_calls": []}

    class _Importer:
        """模拟 Importer，记录调用参数并返回固定文档数据。"""

        def load(self, input_path, rules, **kwargs):
            state["importer_call"] = (input_path, rules, kwargs)
            return _DocData()

    def _export_doc(doc_data, rules, settings, output_path, **kwargs):
        """接收导出参数，写入最小输出文件并返回兼容提示。"""
        state["export_calls"].append((doc_data, rules, settings, output_path, kwargs))
        Path(output_path).write_bytes(b"PK output")
        return {"compatibility_warnings": ["compat"]}

    deps = {
        "log_dir": str(log_dir),
        "output_root_dir": str(output_root),
        "importer_factory": _Importer,
        "export_doc_func": _export_doc,
        "load_rules_and_settings": lambda _config: (None, None, {}),
        "style_rule_cls": _StyleRule,
        "page_settings_cls": _PageSettings,
        "core_feature_defaults": lambda: {"cleanup": {"enabled": True}},
        "make_document_log_path": lambda _kind, log_dir, suffix: str(Path(log_dir) / f"{suffix}.log"),
        "set_context_log_path": lambda path: f"token:{path}",
        "reset_context_log_path": lambda token: state["reset_tokens"].append(token),
        "task_output_dir": lambda task_id: str(output_root / task_id),
        "task_output_path": lambda task_id: str(output_root / task_id / "result.docx"),
        "ensure_path_within": lambda _base, path: path,
        "safe_file_identifier": lambda name: f"file:{name}",
        "safe_download_filename": lambda name: f"排版_{name}",
        "sanitize_error": lambda value: f"sanitized:{value}",
        "public_recognition_summary": lambda _doc_data: {"review": 0},
        "validate_docx_integrity": lambda _path: None,
        "integrity_error_cls": _IntegrityError,
        "logger": logger,
        "now": _StepClock([100.0, 101.25, 102.5]),
        "localtime": lambda _fmt: "2026-08-02 10:00:00",
    }
    deps.update(overrides)
    result = process_uploaded_docx_task(
        "task-12345678",
        str(tmp_path / "input.docx"),
        "input.docx",
        "127.0.0.1",
        "pytest",
        {"mode": "smart"},
        {"processing_strategy": "structural", "preset_name": "默认"},
        **deps,
    )
    return result, state, logger


def test_process_uploaded_docx_task_returns_done_result(tmp_path: Path) -> None:
    result, state, logger = _process_task(tmp_path)

    assert result["status"] == "done"
    assert result["output_filename"] == "排版_input.docx"
    assert result["paragraphs"] == 2
    assert result["headings"] == 1
    assert result["body"] == 1
    assert result["recognition_summary"] == {"review": 0}
    assert result["compatibility_warnings"] == ["compat"]
    assert state["importer_call"][2]["recognition_mode"] == "authoritative"
    assert state["export_calls"][0][4]["cleanup_options"] == {"enabled": True}
    assert state["reset_tokens"]
    assert logger.infos


def test_process_uploaded_docx_task_reports_integrity_failure(tmp_path: Path) -> None:
    def _validate(_path: str) -> None:
        """传入输出路径并模拟完整性校验失败。"""
        raise _IntegrityError("BROKEN", "missing media")

    result, _state, logger = _process_task(tmp_path, validate_docx_integrity=_validate)

    assert result["status"] == "error"
    assert result["error_code"] == "OUTPUT_DOCX_INVALID"
    assert result["error_message"] == "sanitized:BROKEN: missing media"
    assert result["paragraphs"] == 2
    assert logger.errors


def test_process_uploaded_docx_task_returns_sanitized_internal_error(tmp_path: Path) -> None:
    class _BrokenImporter:
        """模拟 Importer 失败，验证应用层兜底错误结果。"""

        def load(self, *_args, **_kwargs):
            raise RuntimeError("C:/secret/input.docx")

    result, state, logger = _process_task(tmp_path, importer_factory=_BrokenImporter)

    assert result["status"] == "error"
    assert result["error_code"] == "TASK_PROCESSING_ERROR"
    assert result["error_message"].startswith("sanitized:")
    assert result["recognition_summary"] == {}
    assert state["reset_tokens"]
    assert logger.errors


class _StepClock:
    """按顺序返回预设时间，模拟任务开始、成功和失败耗时。"""

    def __init__(self, values: list[float]) -> None:
        self.values = list(values)

    def __call__(self) -> float:
        """无参数调用，返回下一项预设时间。"""
        if self.values:
            return self.values.pop(0)
        return 999.0
