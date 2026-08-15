"""HTTP server startup orchestration helpers."""

from __future__ import annotations

import socket
from collections.abc import Callable, Sequence
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
    public_urls: Callable[[], dict[str, str]],
    validate_secrets: Callable[[], None],
    startup_cleanup: Callable[[], Any],
    init_database: Callable[[], Any],
    recover_inflight_tasks: Callable[[], Any],
    ensure_workers_started: Callable[[], Any],
    max_workers: int,
    max_queue: int,
    max_size: int,
    rate_window: int,
    production_mode: bool,
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
    local_urls = startup_urls()
    external_urls = public_urls()
    printer("访问地址:")
    printer(f"前端网站:       {external_urls['frontend']}")
    printer(f"后端网站:       {external_urls['backend']}")
    printer(f"管理后台:       {external_urls['admin_login']}")
    printer(f"本地前后端:     {local_urls['tool']}（同一服务）")
    printer(f"本地管理后台:   {local_urls['admin_login']}")
    printer(f"本地健康检查:   {local_urls['health']}")
    printer(f"本地就绪检查:   {local_urls['ready']}")
    printer(f"本地监控面板:   登录后访问 {local_urls['monitor']}")
    printer(f"运行模式:       {'生产' if production_mode else '开发'} | 监听: {local_urls['tool']}")
    printer("访问链路:")
    printer(f"用户链路:       Cloudflare Pages → {external_urls['backend']} → {local_urls['tool']}")
    printer(f"管理链路:       浏览器 → {external_urls['backend']} → {local_urls['tool']}")
    if external_urls["backend"].startswith("http://"):
        printer("安全提示:       管理后台使用 HTTP，管理员密钥和会话传输不加密。")
    printer("鉴权配置:   ADMIN_TOKEN 已设置 | PROXY_SECRET 已设置")
    printer(f"线程池: {max_workers} | 队列: {max_queue} | 上限: {max_size//1048576}MB")
    printer(f"限流: {rate_window}s/IP | 文件保留: 永久")
    printer("Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        printer("\n已停止")
        server.server_close()
