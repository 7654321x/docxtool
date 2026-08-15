"""Health, readiness, version, and startup URL payload builders."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from typing import Any

from docxtool.web.config import display_frontend_origin


def health_payload() -> dict[str, object]:
    """无需传入数据，返回公开健康检查 payload。"""
    return {"ok": True, "status": "ok"}


def dir_writable(path: str) -> bool:
    """传入目录路径，返回服务是否能在该目录创建并删除临时文件。"""
    try:
        os.makedirs(path, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".ready-", dir=path)
        os.close(fd)
        os.unlink(tmp)
        return True
    except Exception:
        return False


def database_ready(*, connect: Callable[[], Any], sql_lock) -> bool:
    """传入数据库连接工厂和锁，返回 SQLite 是否可执行基础查询。"""
    try:
        with sql_lock:
            conn = connect()
            try:
                conn.execute("SELECT 1").fetchone()
            finally:
                conn.close()
        return True
    except Exception:
        return False


def ready_payload(
    *,
    database_check: Callable[[], bool],
    output_dir: str,
    log_dir: str,
) -> dict[str, object]:
    """传入数据库检查回调和目录路径，返回 readiness 检查结果。"""
    checks = {
        "database": database_check(),
        "output_dir": dir_writable(output_dir),
        "log_dir": dir_writable(log_dir),
    }
    return {"ok": all(checks.values()), "checks": checks}


def version_payload(
    *,
    app_version: str,
    build_version: str,
    git_revision: str,
    started_at: str,
    bind_host: str,
    file_retention_policy: str,
    file_ttl: int | None,
    max_tasks: int,
    task_retention_hours: int | None,
    max_cached_tasks: int,
    cleanup_interval_minutes: int,
    max_size: int,
    upload_read_timeout_seconds: int,
    process_timeout: int,
    max_docx_uncompressed_bytes: int,
    max_docx_file_count: int,
    max_docx_xml_bytes: int,
    max_docx_media_bytes: int,
    max_docx_compression_ratio: int,
    max_workers: int,
    max_queue: int,
    proxy_secret: str,
    frontend_origin: str,
    queued_count: Callable[[], int],
    active_count: Callable[[], int],
) -> dict[str, Any]:
    """传入运行时配置和队列计数回调，返回公开版本信息 payload。"""
    return {
        "version": app_version,
        "package_version": app_version,
        "build_version": build_version or None,
        "git_revision": git_revision or None,
        "started_at": started_at,
        "bind_host": bind_host,
        "file_retention_policy": file_retention_policy,
        "file_ttl_seconds": file_ttl,
        "max_tasks": max_tasks,
        "task_retention_hours": task_retention_hours,
        "max_cached_tasks": max_cached_tasks,
        "cleanup_interval_minutes": cleanup_interval_minutes,
        "max_upload_mb": max_size // 1048576,
        "upload_read_timeout_seconds": upload_read_timeout_seconds,
        "process_timeout_seconds": process_timeout,
        "max_docx_uncompressed_mb": max_docx_uncompressed_bytes // 1048576,
        "max_docx_file_count": max_docx_file_count,
        "max_docx_xml_mb": max_docx_xml_bytes // 1048576,
        "max_docx_media_mb": max_docx_media_bytes // 1048576,
        "max_docx_compression_ratio": max_docx_compression_ratio,
        "max_workers": max_workers,
        "max_queue": max_queue,
        "proxy_secret_required": True,
        "proxy_secret_configured": bool(proxy_secret),
        "frontend_origin": frontend_origin,
        "queued": queued_count(),
        "processing": active_count(),
    }


def server_bind_address(bind_host: str, port: int) -> tuple[str, int]:
    """传入绑定主机和端口，返回 HTTPServer 可使用的地址元组。"""
    return (bind_host, port)


def startup_urls(bind_host: str, port: int) -> dict[str, str]:
    """传入绑定主机和端口，返回启动日志中展示的访问地址。"""
    base = f"http://{bind_host}:{port}"
    return {
        "tool": base,
        "admin_login": f"{base}/admin/login",
        "monitor": f"{base}/monitor",
        "health": f"{base}/health",
        "ready": f"{base}/ready",
        "tunnel_command": f"cloudflared tunnel --url {base}",
    }


def public_startup_urls(frontend_origin: str, backend_origin: str) -> dict[str, str]:
    """传入前端和公网后端 Origin，返回启动日志使用的公网访问地址。"""
    backend = str(backend_origin or "").strip().rstrip("/")
    if not backend:
        raise ValueError("public backend origin must not be empty")
    return {
        "frontend": display_frontend_origin(frontend_origin),
        "backend": backend,
        "admin_login": f"{backend}/admin/login",
    }
