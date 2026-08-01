from __future__ import annotations

import io
from pathlib import Path

from docxtool.web.upload_route_handlers import handle_upload_raw


class FakeConnection:
    """测试用连接对象，记录和返回上传读取超时设置。"""

    def __init__(self) -> None:
        self.timeout = 30
        self.timeouts: list[int] = []

    def gettimeout(self) -> int:
        """无需传入数据，返回当前测试连接超时秒数。"""
        return self.timeout

    def settimeout(self, value: int) -> None:
        """传入超时秒数，记录并更新当前测试连接超时。"""
        self.timeouts.append(value)
        self.timeout = value


class FakeHandler:
    """测试用 handler，保存请求头、请求体、连接和响应记录。"""

    def __init__(self, body: bytes = b"docx", headers: dict[str, str] | None = None) -> None:
        self.headers = {"Content-Length": str(len(body)), "X-Filename": "a.docx", "User-Agent": "pytest"}
        if headers:
            self.headers.update(headers)
        self.client_address = ("127.0.0.1", 9527)
        self.rfile = io.BytesIO(body)
        self.connection = FakeConnection()
        self.responses: list[tuple[str, object]] = []

    def _json_error_fields(self, error: tuple) -> None:
        """传入错误元组，记录字段错误响应。"""
        self.responses.append(("json_error_fields", error))

    def _json_error(self, code: str, message: str, status: int, *, field: str = "", reason: str = "") -> None:
        """传入错误字段，记录 JSON 错误响应。"""
        self.responses.append(("json_error", (code, message, status, field, reason)))

    def _json(self, payload: dict, extra_headers=None) -> None:
        """传入 JSON payload 和可选响应头，记录成功响应。"""
        self.responses.append(("json", (payload, extra_headers or [])))


class FakeLogger:
    """测试用 logger，记录上传处理日志。"""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def warning(self, message: str) -> None:
        """传入 warning 文本，记录日志并返回 None。"""
        self.messages.append(("warning", message))

    def info(self, message: str) -> None:
        """传入 info 文本，记录日志并返回 None。"""
        self.messages.append(("info", message))


class FakeFormatConfigError(Exception):
    """测试用格式配置异常，模拟生产异常字段。"""

    def __init__(self) -> None:
        self.code = "BAD_CONFIG"
        self.message = "配置错误"
        self.status = 400
        self.field = "X-Format-Config"
        self.reason = "invalid"


class FakeDocxValidationError(Exception):
    """测试用 DOCX 校验异常，模拟生产异常字段。"""

    def __init__(self) -> None:
        self.code = "BAD_DOCX"
        self.message = "文档错误"
        self.status = 400


def _default_kwargs(tmp_path: Path, logger: FakeLogger) -> dict:
    """传入临时目录和 logger，返回上传处理器测试所需的默认依赖。"""
    return {
        "principal": lambda _headers, _client: {"owner_id": "owner-1", "cookie": "anon=1"},
        "client_ip": lambda _headers, _client: "127.0.0.1",
        "is_ip_banned": lambda _ip: False,
        "upload_limit_exceeded": lambda _ip: False,
        "allow_upload": lambda _ip: True,
        "logger": logger,
        "upload_ip_banned_error": lambda: ("IP_BANNED", "IP 已封禁", 403),
        "upload_limit_exceeded_error": lambda: ("UPLOAD_LIMIT", "次数超限", 429),
        "upload_rate_limited_error": lambda: ("RATE_LIMIT", "太快", 429),
        "decode_format_config": lambda _headers: {"style": "ok"},
        "format_config_error_type": FakeFormatConfigError,
        "upload_request_meta": lambda _headers: {"preset_name": "默认", "processing_mode": "smart"},
        "validate_requested_processing_mode": lambda _config, _meta: None,
        "max_size": 1024,
        "new_task_id": lambda: "task-1",
        "task_upload_dir": lambda task_id: str(tmp_path / task_id),
        "task_upload_input_path": lambda task_id, raw_name: str(tmp_path / task_id / raw_name),
        "upload_read_timeout_seconds": 5,
        "read_exact_to_file": _write_exact_to_file,
        "timeout_errors": (TimeoutError,),
        "cleanup_incomplete_upload": lambda task_id, path: Path(path).unlink(missing_ok=True),
        "upload_timeout_error": lambda: ("TIMEOUT", "超时", 408),
        "upload_failed_error": lambda: ("UPLOAD_FAILED", "上传失败", 400),
        "incomplete_upload_error": lambda: ("INCOMPLETE", "不完整", 400),
        "validate_docx_upload": lambda *_args, **_kwargs: None,
        "docx_validation_error_type": FakeDocxValidationError,
        "docx_validation_limits": {"max_uncompressed_bytes": 1024},
        "detect_docx_complexity": lambda _path: [{"code": "compat"}],
        "ensure_workers_started": lambda: None,
        "enqueue_task": lambda *args, **kwargs: {"queue_position": 1, "owner": kwargs["owner_id"]},
        "queue_full_error": lambda error: ("QUEUE_FULL", str(error), 503),
        "queued_upload_body": lambda task_id, info, warnings: {"task_id": task_id, "info": info, "warnings": warnings},
        "optional_set_cookie_headers": lambda cookie: [("Set-Cookie", cookie)] if cookie else [],
        "file_too_large_error": lambda: ("FILE_TOO_LARGE", "文件过大", 413),
        "internal_server_error": lambda: ("INTERNAL", "内部错误", 500),
    }


def _write_exact_to_file(stream, path: str, length: int, *, timeout: int) -> int:
    """传入输入流、路径、长度和超时，写出指定字节并返回写入长度。"""
    del timeout
    data = stream.read(length)
    Path(path).write_bytes(data)
    return len(data)


def test_handle_upload_raw_rejects_banned_ip(tmp_path: Path) -> None:
    """上传处理器应在 IP 封禁时直接返回错误，不读取请求体。"""
    logger = FakeLogger()
    kwargs = _default_kwargs(tmp_path, logger)
    kwargs["is_ip_banned"] = lambda _ip: True
    handler = FakeHandler()

    handle_upload_raw(handler, **kwargs)

    assert handler.responses == [("json_error_fields", ("IP_BANNED", "IP 已封禁", 403))]
    assert logger.messages == [("warning", "[Security] banned ip blocked: 127.0.0.1")]


def test_handle_upload_raw_returns_format_config_error(tmp_path: Path) -> None:
    """格式配置解析失败时，上传处理器应返回稳定字段错误。"""
    logger = FakeLogger()
    kwargs = _default_kwargs(tmp_path, logger)
    kwargs["decode_format_config"] = lambda _headers: (_ for _ in ()).throw(FakeFormatConfigError())
    handler = FakeHandler()

    handle_upload_raw(handler, **kwargs)

    assert handler.responses == [
        ("json_error", ("BAD_CONFIG", "配置错误", 400, "X-Format-Config", "invalid"))
    ]


def test_handle_upload_raw_cleans_incomplete_upload(tmp_path: Path) -> None:
    """写入长度不一致时，上传处理器应清理未完成文件并返回不完整错误。"""
    logger = FakeLogger()
    cleaned: list[tuple[str, str]] = []
    kwargs = _default_kwargs(tmp_path, logger)
    kwargs["read_exact_to_file"] = lambda _stream, path, _length, *, timeout: Path(path).write_bytes(b"x") or 1
    kwargs["cleanup_incomplete_upload"] = lambda task_id, path: cleaned.append((task_id, path)) or Path(path).unlink(
        missing_ok=True
    )
    handler = FakeHandler(b"abcd")

    handle_upload_raw(handler, **kwargs)

    assert handler.responses == [("json_error_fields", ("INCOMPLETE", "不完整", 400))]
    assert cleaned == [("task-1", str(tmp_path / "task-1" / "a.docx"))]
    assert not (tmp_path / "task-1" / "a.docx").exists()


def test_handle_upload_raw_enqueues_successful_upload(tmp_path: Path) -> None:
    """上传成功时，处理器应校验 DOCX、启动 worker、入队并返回任务 payload。"""
    logger = FakeLogger()
    calls: list[str] = []
    kwargs = _default_kwargs(tmp_path, logger)
    kwargs["ensure_workers_started"] = lambda: calls.append("workers")
    handler = FakeHandler(b"abcd")

    handle_upload_raw(handler, **kwargs)

    assert calls == ["workers"]
    assert handler.responses == [
        (
            "json",
            (
                {
                    "task_id": "task-1",
                    "info": {"queue_position": 1, "owner": "owner-1"},
                    "warnings": [{"code": "compat"}],
                },
                [("Set-Cookie", "anon=1")],
            ),
        )
    ]
    assert (tmp_path / "task-1" / "a.docx").read_bytes() == b"abcd"
    assert any(level == "info" and "md5=" in message for level, message in logger.messages)
