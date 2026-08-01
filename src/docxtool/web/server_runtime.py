"""HTTP server startup orchestration helpers."""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterable, Sequence
from typing import Any


def print_cli_help(*, printer: Callable[[str], None] = print) -> None:
    """传入可选输出函数，打印命令行启动帮助并返回 None。"""
    printer("Usage: python server.py")
    printer("   or: python -m docxtool")
    printer("Configure ADMIN_TOKEN and PROXY_SECRET before starting the service.")


def run_http_service(
    *,
    argv: Sequence[str],
    server_class: type,
    handler_class: type,
    bind_address: Callable[[], tuple[str, int]],
    startup_urls: Callable[[], dict[str, str]],
    startup_time_check_lines: Callable[[], Iterable[str]],
    validate_secrets: Callable[[], None],
    startup_cleanup: Callable[[], Any],
    init_database: Callable[[], Any],
    recover_inflight_tasks: Callable[[], Any],
    ensure_workers_started: Callable[[], Any],
    max_workers: int,
    max_queue: int,
    max_size: int,
    rate_window: int,
    printer: Callable[[str], None] = print,
) -> None:
    """传入启动依赖和运行配置，按既有顺序启动 HTTP 服务并在退出时关闭。"""
    if any(arg in {"-h", "--help"} for arg in argv[1:]):
        print_cli_help(printer=printer)
        return

    validate_secrets()
    startup_cleanup()
    init_database()
    recover_inflight_tasks()
    ensure_workers_started()

    server = server_class(bind_address(), handler_class)
    server.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    urls = startup_urls()
    printer(f"排版工具:   {urls['tool']}")
    printer(f"管理员登录: {urls['admin_login']}")
    printer(f"监控面板:   登录后访问 {urls['monitor']}")
    printer("鉴权配置:   ADMIN_TOKEN 已设置 | PROXY_SECRET 已设置")
    printer(f"线程池: {max_workers} | 队列: {max_queue} | 上限: {max_size//1048576}MB")
    printer(f"限流: {rate_window}s/IP | 文件保留: 永久")
    for line in startup_time_check_lines():
        printer(line)
    printer("外网访问:   Cloudflare Pages /api/* -> Nginx 80 -> 127.0.0.1:9527")
    printer("Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        printer("\n已停止")
        server.server_close()
