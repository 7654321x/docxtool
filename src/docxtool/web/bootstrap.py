"""Import-time path and environment assembly for the Web compatibility app."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Callable

from docxtool.paths import project_path, runtime_dir
from docxtool.storage.database import default_database_path
from docxtool.version import package_version
from docxtool.web.config import (
    parse_admin_console_origin,
    parse_bool,
    parse_frontend_origin,
    parse_int_env,
    resolve_admin_cookie_secure,
    resolve_cookie_secure,
)


DEFAULT_ADMIN_TOKEN = "7654321xxx"
DEFAULT_PROXY_SECRET = "docxtool-proxy-20260601-9ec0d6e2443a4f5f9784f0f04bb62917"
ADMIN_SESSION_COOKIE = "docxtool_admin_session"
ANONYMOUS_USER_COOKIE = "docxtool_anon_user"
ANONYMOUS_USER_COOKIE_MAX_AGE = 2 * 365 * 24 * 60 * 60
USER_SESSION_COOKIE = "docxtool_user_session"
USER_SESSION_REFRESH_SECONDS = 300
ADMIN_CSRF_HEADER = "X-CSRF-Token"
DEFAULT_ADMIN_SESSION_TTL_SECONDS = 12 * 60 * 60


@dataclass(frozen=True)
class RuntimePaths:
    base_dir: str
    database_path: str
    log_dir: str
    runtime_dir: str
    runtime_tmp_dir: str
    upload_dir: str


@dataclass(frozen=True)
class EnvironmentConfig:
    port: int
    bind_host: str
    app_version: str
    build_version: str
    git_revision: str
    started_at: str
    admin_token: str
    proxy_secret: str
    production_mode: bool
    frontend_origin: str
    cookie_secure: bool
    admin_console_origin: str
    admin_cookie_secure: bool
    user_session_days: int
    user_session_max_age: int
    max_size: int
    upload_read_timeout_seconds: int
    upload_read_chunk_size: int
    max_workers: int
    max_queue: int
    process_timeout: int
    rate_window: int
    file_retention_policy: str
    file_ttl: None
    max_tasks: int
    task_retention_hours: None
    max_cached_tasks: int
    cleanup_interval_minutes: int
    default_upload_limit_window_seconds: int
    default_upload_limit_count: int
    max_format_config_header_bytes: int
    max_format_config_json_bytes: int
    max_docx_uncompressed_bytes: int
    max_docx_file_count: int
    max_docx_xml_bytes: int
    max_docx_media_bytes: int
    max_docx_compression_ratio: int
    trust_proxy_headers: bool
    trusted_proxy_ips: set[str]


def resolve_base_dir() -> str:
    return str(project_path())


def resolve_database_path() -> str:
    return default_database_path()


def prepare_initial_runtime_paths(base_dir: str, database_path: str) -> RuntimePaths:
    log_dir = str(runtime_dir("logs", "LOG_DIR"))
    runtime_root = str(runtime_dir("runtime", "RUNTIME_DIR"))
    runtime_tmp_dir = os.path.join(runtime_root, "tmp")
    upload_dir = str(runtime_dir("uploads", "UPLOAD_DIR"))
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(runtime_tmp_dir, exist_ok=True)
    os.makedirs(upload_dir, exist_ok=True)
    return RuntimePaths(
        base_dir,
        database_path,
        log_dir,
        runtime_root,
        runtime_tmp_dir,
        upload_dir,
    )


def load_environment_config(load_secret: Callable[[str, str], str]) -> EnvironmentConfig:
    port = int(os.environ.get("PORT", "9527"))
    bind_host = os.environ.get("BIND_HOST", "127.0.0.1")
    app_version = package_version()
    build_version = os.environ.get("DOCXTOOL_BUILD_VERSION", "").strip()
    git_revision = os.environ.get("DOCXTOOL_GIT_REVISION", "").strip()
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    admin_token = load_secret("ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN)
    proxy_secret = load_secret("PROXY_SECRET", DEFAULT_PROXY_SECRET)
    production_mode = parse_bool(os.environ.get("PRODUCTION_MODE", "false"), False)
    try:
        frontend_origin = parse_frontend_origin(
            os.environ.get("FRONTEND_ORIGIN", ""),
            production_mode,
        )
        cookie_secure = resolve_cookie_secure(
            frontend_origin,
            os.environ.get("COOKIE_SECURE"),
            production_mode,
        )
        admin_console_origin_raw = os.environ.get("ADMIN_CONSOLE_ORIGIN", "")
        admin_cookie_secure_raw = os.environ.get("ADMIN_COOKIE_SECURE")
        admin_console_origin = parse_admin_console_origin(admin_console_origin_raw)
        if str(admin_console_origin_raw).strip() or str(admin_cookie_secure_raw or "").strip():
            admin_cookie_secure = resolve_admin_cookie_secure(
                admin_console_origin,
                admin_cookie_secure_raw,
                cookie_secure,
                production_mode,
            )
        else:
            admin_cookie_secure = cookie_secure
    except ValueError as exc:
        raise SystemExit(f"[配置错误] {exc}") from exc
    user_session_days = max(1, min(365, parse_int_env("DOCXTOOL_USER_SESSION_DAYS", 30)))
    max_workers = 4
    return EnvironmentConfig(
        port=port,
        bind_host=bind_host,
        app_version=app_version,
        build_version=build_version,
        git_revision=git_revision,
        started_at=started_at,
        admin_token=admin_token,
        proxy_secret=proxy_secret,
        production_mode=production_mode,
        frontend_origin=frontend_origin,
        cookie_secure=cookie_secure,
        admin_console_origin=admin_console_origin,
        admin_cookie_secure=admin_cookie_secure,
        user_session_days=user_session_days,
        user_session_max_age=user_session_days * 24 * 60 * 60,
        max_size=parse_int_env("MAX_UPLOAD_SIZE_MB", 10) * 1024 * 1024,
        upload_read_timeout_seconds=parse_int_env("UPLOAD_READ_TIMEOUT_SECONDS", 15),
        upload_read_chunk_size=64 * 1024,
        max_workers=max_workers,
        max_queue=max_workers * 2,
        process_timeout=parse_int_env("PROCESS_TIMEOUT_SECONDS", 60),
        rate_window=2,
        file_retention_policy="permanent",
        file_ttl=None,
        max_tasks=parse_int_env("MAX_TASKS", 200),
        task_retention_hours=None,
        max_cached_tasks=parse_int_env("MAX_CACHED_TASKS", 500),
        cleanup_interval_minutes=parse_int_env("CLEANUP_INTERVAL_MINUTES", 30),
        default_upload_limit_window_seconds=3600,
        default_upload_limit_count=10,
        max_format_config_header_bytes=96 * 1024,
        max_format_config_json_bytes=64 * 1024,
        max_docx_uncompressed_bytes=parse_int_env("MAX_DOCX_UNCOMPRESSED_MB", 100) * 1024 * 1024,
        max_docx_file_count=parse_int_env("MAX_DOCX_FILE_COUNT", 1000),
        max_docx_xml_bytes=parse_int_env("MAX_DOCX_XML_SIZE_MB", 20) * 1024 * 1024,
        max_docx_media_bytes=parse_int_env("MAX_DOCX_MEDIA_SIZE_MB", 30) * 1024 * 1024,
        max_docx_compression_ratio=parse_int_env("MAX_DOCX_COMPRESSION_RATIO", 100),
        trust_proxy_headers=parse_bool(os.environ.get("TRUST_PROXY_HEADERS", "true"), True),
        trusted_proxy_ips={
            ip.strip()
            for ip in os.environ.get("TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
            if ip.strip()
        },
    )


def prepare_output_dir() -> str:
    output_dir = str(runtime_dir("outputs", "OUTPUT_DIR"))
    os.makedirs(output_dir, exist_ok=True)
    return output_dir
