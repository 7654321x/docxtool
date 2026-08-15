from __future__ import annotations

from docxtool.web.server_runtime import print_cli_help, run_http_service


def test_print_cli_help_writes_existing_usage_lines() -> None:
    """启动帮助输出应保持旧入口提示内容不变。"""
    lines: list[str] = []

    print_cli_help(printer=lines.append)

    assert lines == [
        "Usage: python server.py",
        "   or: python -m docxtool",
        "Configure ADMIN_TOKEN and PROXY_SECRET before starting the service.",
    ]


def test_run_http_service_help_returns_before_startup() -> None:
    """传入 --help 时只打印帮助，不执行密钥、建库或启动服务回调。"""
    calls: list[str] = []

    run_http_service(
        argv=["server.py", "--help"],
        server_class=object,
        handler_class=object,
        bind_address=lambda: ("127.0.0.1", 9527),
        startup_urls=lambda: {},
        public_urls=lambda: {},
        validate_secrets=lambda: calls.append("validate"),
        startup_cleanup=lambda: calls.append("cleanup"),
        init_database=lambda: calls.append("sql"),
        recover_inflight_tasks=lambda: calls.append("recover"),
        ensure_workers_started=lambda: calls.append("workers"),
        max_workers=4,
        max_queue=8,
        max_size=10 * 1024 * 1024,
        rate_window=2,
        production_mode=False,
        printer=calls.append,
    )

    assert calls == [
        "Usage: python server.py",
        "   or: python -m docxtool",
        "Configure ADMIN_TOKEN and PROXY_SECRET before starting the service.",
    ]


def test_run_http_service_starts_in_existing_order_and_closes_on_interrupt() -> None:
    """传入启动依赖后，应按旧顺序初始化、启动服务，并在中断时关闭服务。"""
    calls: list[str] = []

    class FakeSocket:
        def setsockopt(self, *_args) -> None:
            calls.append("setsockopt")

    class FakeServer:
        socket = FakeSocket()

        def __init__(self, address, handler) -> None:
            calls.append(f"server:{address[0]}:{address[1]}:{handler.__name__}")

        def serve_forever(self) -> None:
            calls.append("serve_forever")
            raise KeyboardInterrupt

        def server_close(self) -> None:
            calls.append("server_close")

    class FakeHandler:
        """测试用 handler 类型，只提供稳定类名供断言使用。"""

    run_http_service(
        argv=["server.py"],
        server_class=FakeServer,
        handler_class=FakeHandler,
        bind_address=lambda: ("127.0.0.1", 9527),
        startup_urls=lambda: {
            "tool": "http://127.0.0.1:9527",
            "admin_login": "http://127.0.0.1:9527/admin/login",
            "monitor": "http://127.0.0.1:9527/monitor",
            "health": "http://127.0.0.1:9527/health",
            "ready": "http://127.0.0.1:9527/ready",
        },
        public_urls=lambda: {
            "frontend": "https://docxtool.pages.dev",
            "backend": "http://43.133.167.18:8080",
            "admin_login": "http://43.133.167.18:8080/admin/login",
        },
        validate_secrets=lambda: calls.append("validate"),
        startup_cleanup=lambda: calls.append("cleanup"),
        init_database=lambda: calls.append("sql"),
        recover_inflight_tasks=lambda: calls.append("recover"),
        ensure_workers_started=lambda: calls.append("workers"),
        max_workers=4,
        max_queue=8,
        max_size=10 * 1024 * 1024,
        rate_window=2,
        production_mode=True,
        printer=lambda line: calls.append(f"print:{line}"),
    )

    assert calls[:7] == [
        "validate",
        "cleanup",
        "sql",
        "recover",
        "workers",
        "server:127.0.0.1:9527:FakeHandler",
        "setsockopt",
    ]
    assert "serve_forever" in calls
    assert "server_close" in calls
    assert "print:前端网站:       https://docxtool.pages.dev" in calls
    assert "print:后端网站:       http://43.133.167.18:8080" in calls
    assert "print:管理后台:       http://43.133.167.18:8080/admin/login" in calls
    assert "print:本地健康检查:   http://127.0.0.1:9527/health" in calls
    assert "print:运行模式:       生产 | 监听: http://127.0.0.1:9527" in calls
    assert not any("时间校验" in call for call in calls)
