from __future__ import annotations

import io
from contextlib import nullcontext

from docxtool.web.task_route_handlers import handle_download, handle_log, handle_status


class FakeHandler:
    """测试用 handler，记录 JSON、文本、下载响应头和响应体。"""

    def __init__(self) -> None:
        self.headers = {}
        self.client_address = ("127.0.0.1", 12345)
        self.responses: list[tuple[str, object]] = []
        self.sent_headers: list[tuple[str, str]] = []
        self.wfile = io.BytesIO()

    def _json(self, obj: dict) -> None:
        """传入 JSON 对象，记录 JSON 响应。"""
        self.responses.append(("json", obj))

    def _json_error_fields(self, error: tuple[str, str, int]) -> None:
        """传入错误字段元组，记录 JSON 错误响应。"""
        self.responses.append(("json_error_fields", error))

    def _text(self, body: str, mime: str) -> None:
        """传入文本正文和 MIME，记录文本响应。"""
        self.responses.append(("text", (body, mime)))

    def send_response(self, status: int) -> None:
        """传入 HTTP 状态码，记录下载响应状态。"""
        self.responses.append(("status", status))

    def send_header(self, key: str, value: str) -> None:
        """传入响应头名和值，记录下载响应头。"""
        self.sent_headers.append((key, value))

    def _set_cors_headers(self) -> None:
        """无需传入数据，记录 CORS 头写入。"""
        self.sent_headers.append(("CORS", "1"))

    def _set_security_headers(self) -> None:
        """无需传入数据，记录安全头写入。"""
        self.sent_headers.append(("SECURITY", "1"))

    def end_headers(self) -> None:
        """无需传入数据，记录响应头结束。"""
        self.responses.append(("end_headers", ""))


class FakeRow(dict):
    """测试用数据库行，支持字典键访问。"""


class FakeConnection:
    """测试用数据库连接，返回预设行并记录 SQL 参数。"""

    def __init__(self, row=None) -> None:
        self.row = row
        self.closed = False
        self.queries: list[tuple[str, tuple]] = []

    def execute(self, sql: str, args: tuple):
        """传入 SQL 和参数，记录查询并返回自身作为 cursor。"""
        self.queries.append((sql, args))
        return self

    def fetchone(self):
        """无需传入数据，返回预设行。"""
        return self.row

    def close(self) -> None:
        """无需传入数据，标记连接关闭。"""
        self.closed = True


def _principal(_headers, _client_address) -> dict:
    """传入请求头和客户端地址，返回测试 owner。"""
    return {"owner_id": "owner-1"}


def test_handle_status_returns_task_or_stable_errors() -> None:
    """状态处理器应校验任务 ID，并返回任务状态或不存在错误。"""
    invalid = FakeHandler()
    missing = FakeHandler()
    ok = FakeHandler()

    handle_status(
        invalid,
        "bad",
        is_safe_uuid=lambda value: value == "task-1",
        invalid_task_id_error=lambda: ("INVALID_TASK_ID", "无效", 400),
        task_not_found_error=lambda: ("TASK_NOT_FOUND", "不存在", 404),
        principal=_principal,
        public_task_state=lambda *_args: {},
    )
    handle_status(
        missing,
        "task-1",
        is_safe_uuid=lambda value: value == "task-1",
        invalid_task_id_error=lambda: ("INVALID_TASK_ID", "无效", 400),
        task_not_found_error=lambda: ("TASK_NOT_FOUND", "不存在", 404),
        principal=_principal,
        public_task_state=lambda *_args: {},
    )
    handle_status(
        ok,
        "task-1",
        is_safe_uuid=lambda value: value == "task-1",
        invalid_task_id_error=lambda: ("INVALID_TASK_ID", "无效", 400),
        task_not_found_error=lambda: ("TASK_NOT_FOUND", "不存在", 404),
        principal=_principal,
        public_task_state=lambda task_id, owner_id: {"id": task_id, "owner": owner_id},
    )

    assert invalid.responses == [("json_error_fields", ("INVALID_TASK_ID", "无效", 400))]
    assert missing.responses == [("json_error_fields", ("TASK_NOT_FOUND", "不存在", 404))]
    assert ok.responses == [("json", {"id": "task-1", "owner": "owner-1"})]


def test_handle_download_streams_memory_task_file() -> None:
    """下载处理器应优先使用内存完成任务，并发送 DOCX 下载头和文件流。"""
    handler = FakeHandler()
    tasks = {"task-1": {"status": "done", "owner_id": "owner-1", "output_path": "out.docx", "download_name": "结果.docx"}}

    handle_download(
        handler,
        "task-1",
        is_safe_uuid=lambda value: value == "task-1",
        invalid_task_id_error=lambda: ("INVALID_TASK_ID", "无效", 400),
        file_not_ready_error=lambda: ("FILE_NOT_READY", "未就绪", 400),
        file_expired_error=lambda: ("FILE_EXPIRED", "过期", 410),
        principal=_principal,
        tasks=tasks,
        tasks_lock=nullcontext(),
        sql_lock=nullcontext(),
        connect=lambda: FakeConnection(),
        safe_download_filename=lambda name: f"safe-{name}",
        content_disposition_filename=lambda name: f"attachment; filename={name}",
        docx_download_headers=lambda disposition, size: [("Content-Disposition", disposition), ("Content-Length", str(size))],
        stream_file=lambda _path, writer: writer.write(b"docx"),
        path_exists=lambda path: path == "out.docx",
        path_getsize=lambda _path: 4,
    )

    assert handler.responses == [("status", 200), ("end_headers", "")]
    assert ("Content-Disposition", "attachment; filename=结果.docx") in handler.sent_headers
    assert handler.wfile.getvalue() == b"docx"


def test_handle_download_uses_database_row_when_memory_task_not_done() -> None:
    """下载处理器在内存任务未完成时应查询数据库完成记录。"""
    handler = FakeHandler()
    row = FakeRow(status="done", output_path="db.docx", output_filename="", filename="原稿.docx")

    handle_download(
        handler,
        "task-1",
        is_safe_uuid=lambda value: value == "task-1",
        invalid_task_id_error=lambda: ("INVALID_TASK_ID", "无效", 400),
        file_not_ready_error=lambda: ("FILE_NOT_READY", "未就绪", 400),
        file_expired_error=lambda: ("FILE_EXPIRED", "过期", 410),
        principal=_principal,
        tasks={},
        tasks_lock=nullcontext(),
        sql_lock=nullcontext(),
        connect=lambda: FakeConnection(row),
        safe_download_filename=lambda name: f"safe-{name}",
        content_disposition_filename=lambda name: f"attachment; filename={name}",
        docx_download_headers=lambda _disposition, _size: [],
        stream_file=lambda _path, writer: writer.write(b"docx"),
        path_exists=lambda path: path == "db.docx",
        path_getsize=lambda _path: 4,
    )

    assert handler.responses == [("status", 200), ("end_headers", "")]
    assert handler.wfile.getvalue() == b"docx"


def test_handle_download_reports_not_ready_or_expired() -> None:
    """下载处理器应区分未就绪记录和输出文件过期。"""
    not_ready = FakeHandler()
    expired = FakeHandler()
    row = FakeRow(status="done", output_path="missing.docx", output_filename="", filename="原稿.docx")

    common = {
        "is_safe_uuid": lambda value: value == "task-1",
        "invalid_task_id_error": lambda: ("INVALID_TASK_ID", "无效", 400),
        "file_not_ready_error": lambda: ("FILE_NOT_READY", "未就绪", 400),
        "file_expired_error": lambda: ("FILE_EXPIRED", "过期", 410),
        "principal": _principal,
        "tasks": {},
        "tasks_lock": nullcontext(),
        "sql_lock": nullcontext(),
        "safe_download_filename": lambda name: f"safe-{name}",
        "content_disposition_filename": lambda name: name,
        "docx_download_headers": lambda _disposition, _size: [],
        "stream_file": lambda _path, _writer: None,
    }

    handle_download(not_ready, "task-1", connect=lambda: FakeConnection(None), **common)
    handle_download(expired, "task-1", connect=lambda: FakeConnection(row), path_exists=lambda _path: False, **common)

    assert not_ready.responses == [("json_error_fields", ("FILE_NOT_READY", "未就绪", 400))]
    assert expired.responses == [("json_error_fields", ("FILE_EXPIRED", "过期", 410))]


def test_handle_log_reads_redacts_and_renders_log(tmp_path) -> None:
    """日志处理器应校验日志路径、脱敏日志文本并渲染 HTML。"""
    handler = FakeHandler()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_path = log_dir / "task.log"
    log_path.write_text("secret", encoding="utf-8")
    row = FakeRow(log_path=str(log_path), filename="a.docx")

    handle_log(
        handler,
        "task-1",
        is_safe_uuid=lambda value: value == "task-1",
        invalid_task_id_error=lambda: ("INVALID_TASK_ID", "无效", 400),
        log_not_found_error=lambda expired=False: ("LOG_NOT_FOUND", "过期" if expired else "无日志", 404),
        tasks={},
        tasks_lock=nullcontext(),
        sql_lock=nullcontext(),
        connect=lambda: FakeConnection(row),
        log_dir=str(log_dir),
        redact_sensitive_log=lambda text: text.replace("secret", "redacted"),
        render_task_log_html=lambda task_id, _row, text: f"{task_id}:{text}",
    )

    assert handler.responses == [("text", ("task-1:redacted", "text/html"))]


def test_handle_log_reports_missing_or_unsafe_path(tmp_path) -> None:
    """日志处理器应在日志缺失或路径越界时返回稳定错误。"""
    missing = FakeHandler()
    unsafe = FakeHandler()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    unsafe_path = tmp_path / "outside" / "task.log"
    unsafe_path.parent.mkdir()
    unsafe_path.write_text("outside", encoding="utf-8")
    row = FakeRow(log_path=str(unsafe_path))

    common = {
        "is_safe_uuid": lambda value: value == "task-1",
        "invalid_task_id_error": lambda: ("INVALID_TASK_ID", "无效", 400),
        "log_not_found_error": lambda expired=False: ("LOG_NOT_FOUND", "过期" if expired else "无日志", 404),
        "tasks": {},
        "tasks_lock": nullcontext(),
        "sql_lock": nullcontext(),
        "log_dir": str(log_dir),
        "redact_sensitive_log": lambda text: text,
        "render_task_log_html": lambda *_args: "",
    }

    handle_log(missing, "task-1", connect=lambda: FakeConnection(None), **common)
    handle_log(unsafe, "task-1", connect=lambda: FakeConnection(row), **common)

    assert missing.responses == [("json_error_fields", ("LOG_NOT_FOUND", "无日志", 404))]
    assert unsafe.responses == [("json_error_fields", ("LOG_NOT_FOUND", "过期", 404))]
