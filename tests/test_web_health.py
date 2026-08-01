from docxtool.web import app as server
from docxtool.web.health import (
    database_ready,
    health_payload,
    ready_payload,
    server_bind_address,
    startup_urls,
    version_payload,
)


def test_health_and_ready_payload_helpers(tmp_path) -> None:
    """健康模块传入目录和数据库检查回调后，应返回稳定 readiness 结构。"""
    output_dir = tmp_path / "outputs"
    log_dir = tmp_path / "logs"

    assert health_payload() == {"ok": True, "status": "ok"}
    ready = ready_payload(
        database_check=lambda: True,
        output_dir=str(output_dir),
        log_dir=str(log_dir),
    )

    assert ready["ok"] is True
    assert ready["checks"] == {"database": True, "output_dir": True, "log_dir": True}


def test_version_payload_helper_preserves_public_contract() -> None:
    """版本模块传入运行配置和计数回调后，应保留旧公开字段。"""
    payload = version_payload(
        app_version="2.3",
        build_version="build-1",
        git_revision="abc123",
        started_at="2026-08-01 23:00:00",
        bind_host="127.0.0.1",
        file_retention_policy="permanent",
        file_ttl=None,
        max_tasks=200,
        task_retention_hours=None,
        max_cached_tasks=500,
        cleanup_interval_minutes=30,
        max_size=10 * 1048576,
        upload_read_timeout_seconds=15,
        process_timeout=60,
        max_docx_uncompressed_bytes=100 * 1048576,
        max_docx_file_count=1000,
        max_docx_xml_bytes=20 * 1048576,
        max_docx_media_bytes=30 * 1048576,
        max_docx_compression_ratio=100,
        max_workers=4,
        max_queue=8,
        proxy_secret="secret",
        frontend_origin="https://example.pages.dev",
        queued_count=lambda: 2,
        active_count=lambda: 1,
    )

    assert payload["version"] == "2.3"
    assert payload["package_version"] == "2.3"
    assert payload["proxy_secret_required"] is True
    assert payload["proxy_secret_configured"] is True
    assert payload["queued"] == 2
    assert payload["processing"] == 1


def test_database_ready_executes_probe_and_closes_connection() -> None:
    """数据库探活模块传入连接器和锁后，应执行 SELECT 并关闭连接。"""
    lock = _NoopLock()
    conn = _ProbeConnection()

    assert database_ready(connect=lambda: conn, sql_lock=lock) is True
    assert conn.executed_sql == "SELECT 1"
    assert conn.closed is True
    assert lock.entered is True


def test_database_ready_returns_false_on_probe_error() -> None:
    """数据库探活模块遇到连接或查询异常时，应返回 False 而不抛出。"""
    assert database_ready(connect=lambda: (_ for _ in ()).throw(RuntimeError("boom")), sql_lock=_NoopLock()) is False
    assert database_ready(connect=lambda: _ProbeConnection(raise_on_execute=True), sql_lock=_NoopLock()) is False


def test_startup_helpers_match_app_facade() -> None:
    """启动地址模块传入 host 和 port 后，应与 web.app 兼容入口保持一致。"""
    assert server_bind_address(server.BIND_HOST, server.PORT) == server._server_bind_address()
    assert startup_urls(server.BIND_HOST, server.PORT) == server._startup_urls()


class _NoopLock:
    """测试锁记录进入状态，模拟应用层 SQL 锁上下文。"""

    def __init__(self) -> None:
        self.entered = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _ProbeConnection:
    """测试连接记录执行 SQL 和关闭状态，模拟 SQLite 连接对象。"""

    def __init__(self, *, raise_on_execute: bool = False) -> None:
        self.raise_on_execute = raise_on_execute
        self.executed_sql = ""
        self.closed = False

    def execute(self, sql: str):
        self.executed_sql = sql
        if self.raise_on_execute:
            raise RuntimeError("query failed")
        return self

    def fetchone(self):
        return (1,)

    def close(self) -> None:
        self.closed = True
