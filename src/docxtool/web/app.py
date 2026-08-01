"""server — 公文排版 Web 服务。

功能：上传 .docx → 自动排版 → 下载
监控：/monitor（统计面板）/stats（JSON API）
安全：SQL 参数化查询 / UUID 校验 / XSS 转义 / 安全头 / 限流 / 文件大小限制
存储：SQLite（默认 var/data/stats.db）
启动：python server.py
访问：http://localhost:9527
"""

from __future__ import annotations

import os
import sys
import json
import multiprocessing as mp
import uuid
import time
import hashlib
import hmac
import socket
import threading
import logging
import html
import ipaddress
import shutil
import re as _re
from queue import Empty
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from collections import OrderedDict
from urllib.parse import unquote, urlparse, parse_qs

from docxtool.document.importer import DocxImporter
from docxtool.document.engine import export_doc
from docxtool.security import DocxIntegrityError, validate_docx_integrity
from docxtool.security.docx_validator import DocxValidationError, detect_docx_complexity, validate_docx_upload
from docxtool.document.style_config import (
    StyleRule, PageSettings, load_rules_and_settings, configure_logging, get_logger,
    make_document_log_path, set_context_log_path, reset_context_log_path,
)
from docxtool.paths import project_path, resource_path, runtime_dir
from docxtool.storage.database import connect as _db_connect, default_database_path
from docxtool.auth import hash_password, verify_password, validate_password, validate_username
from docxtool.version import package_version
from docxtool.web.config import (
    cors_headers_for_request as _config_cors_headers_for_request,
    is_local_origin_host as _is_local_origin_host,
    parse_bool as _parse_bool,
    parse_frontend_origin,
    parse_int_env as _parse_int_env,
    resolve_cookie_secure,
)
from docxtool.web.database_schema import initialize_web_database as _schema_initialize_web_database
from docxtool.web.client_ip import (
    client_ip as _client_ip_from_headers,
    compare_secret as _client_compare_secret,
    is_ip as _client_is_ip,
    is_ipv4 as _client_is_ipv4,
    split_ip_header as _client_split_ip_header,
    trusted_proxy_source as _client_trusted_proxy_source,
)
from docxtool.web.task_cache import prune_task_cache as _task_cache_prune
from docxtool.web.anonymous_identity import (
    anonymous_template_origin_allowed as _anon_template_origin_allowed,
    anonymous_user_cookie_clear_header as _anon_cookie_clear_header,
    anonymous_user_cookie_header as _anon_cookie_header,
    anonymous_user_from_headers as _anon_user_from_headers,
    anonymous_user_signature as _anon_user_signature,
    anonymous_user_signing_key as _anon_user_signing_key,
    create_anonymous_user as _anon_create_user,
    parse_anonymous_user as _anon_parse_user,
)
from docxtool.web.admin_auth import (
    admin_authorized as _admin_auth_authorized,
    admin_request_context as _admin_auth_request_context,
    admin_session_from_headers as _admin_auth_session_from_headers,
    create_admin_session as _admin_auth_create_session,
    delete_admin_session as _admin_auth_delete_session,
    get_admin_session as _admin_auth_get_session,
    legacy_admin_token_from as _admin_auth_legacy_token_from,
    now_unix as _admin_auth_now_unix,
    prune_expired_admin_sessions as _admin_auth_prune_expired_sessions,
    validate_admin_csrf as _admin_auth_validate_csrf,
)
from docxtool.web.file_utils import (
    content_disposition_filename as _file_content_disposition_filename,
    is_safe_uuid as _file_is_safe_uuid,
    safe_download_filename as _file_safe_download_filename,
    safe_file_identifier as _file_safe_file_identifier,
    sanitize_filename as _file_sanitize_filename,
    sanitize_internal_error_detail as _file_sanitize_internal_error_detail,
)
from docxtool.web.format_request import (
    FormatConfigRequestError,
    decode_format_config as _format_decode_format_config,
    format_config_error as _format_config_error_impl,
    processing_strategy_from_mode as _format_processing_strategy_from_mode,
    upload_request_meta as _format_upload_request_meta,
    validate_requested_processing_mode as _format_validate_requested_processing_mode,
)
from docxtool.web.health import (
    dir_writable as _health_dir_writable,
    health_payload as _build_health_payload,
    ready_payload as _build_ready_payload,
    server_bind_address as _build_server_bind_address,
    startup_urls as _build_startup_urls,
    version_payload as _build_version_payload,
)
from docxtool.web.maintenance import cleaner_loop as _maintenance_cleaner_loop
from docxtool.web.monitoring import (
    DEFAULT_MONITOR_PAGE_SIZE,
    MAX_MONITOR_PAGE_SIZE,
    clamp_int as _monitor_clamp_int,
    first_query_value as _monitor_first_query_value,
    monitor_query_from as _build_monitor_query_from,
    monitor_url as _build_monitor_url,
    normalize_monitor_query as _build_normalize_monitor_query,
    page_count as _monitor_page_count,
    where_sql as _monitor_where_sql,
)
from docxtool.web.monitoring_pages import (
    render_ip_detail_html as _pages_render_ip_detail_html,
    render_banned_ip_rows as _pages_render_banned_ip_rows,
    render_health_check_items as _pages_render_health_check_items,
    render_pager_html as _pages_render_pager_html,
    render_recent_task_rows as _pages_render_recent_task_rows,
    render_task_log_html as _pages_render_task_log_html,
    render_top_ip_rows as _pages_render_top_ip_rows,
    render_trend_bars as _pages_render_trend_bars,
    status_badge as _pages_status_badge,
)
from docxtool.web.owner_migration import (
    migrate_anonymous_owner as _owner_migration_migrate_owner,
    migrate_anonymous_resources as _owner_migration_migrate_resources,
)
from docxtool.web.preset_config import (
    normalize_template_id as _preset_normalize_template_id,
    normalize_template_name as _preset_normalize_template_name,
    preset_row_to_dict as _preset_row_to_dict_impl,
    validate_template_config as _preset_validate_template_config,
)
from docxtool.web.preset_defaults import (
    core_feature_config_defaults as _preset_defaults_core_features,
    default_preset_config as _preset_defaults_config,
    seed_default_presets as _preset_defaults_seed,
)
from docxtool.web.preset_store import (
    delete_preset as _preset_store_delete,
    get_preset as _preset_store_get,
    insert_preset as _preset_store_insert,
    list_presets as _preset_store_list,
    update_preset as _preset_store_update,
)
from docxtool.web.rate_limits import (
    allow as _rate_allow,
    auth_rate_allow as _rate_auth_rate_allow,
    ban_ip as _rate_ban_ip,
    banned_ips as _rate_banned_ips,
    ip_activity as _rate_ip_activity,
    ip_upload_count as _rate_ip_upload_count,
    is_ip_banned as _rate_is_ip_banned,
    limit_settings as _rate_limit_settings,
    save_limit_settings as _rate_save_limit_settings,
    settings_get as _rate_settings_get,
    settings_set as _rate_settings_set,
    unban_ip as _rate_unban_ip,
    upload_limit_exceeded as _rate_upload_limit_exceeded,
)
from docxtool.web.request_utils import (
    admin_session_cookie_settings as _request_admin_session_cookie_settings,
    admin_token_from_query as _request_admin_token_from_query,
    admin_url as _request_admin_url,
    cookie_value as _request_cookie_value,
    csrf_header_value as _request_csrf_header_value,
    error_payload as _request_error_payload,
    hidden_input as _request_hidden_input,
    html_escape as _request_html_escape,
    json_dumps as _request_json_dumps,
    parse_json_body as _request_parse_json_body,
    route_path as _request_route_path,
)
from docxtool.web.secrets import (
    load_secret as _secrets_load_secret,
    validate_required_secrets as _secrets_validate_required,
)
from docxtool.web.stream_io import (
    read_exact as _stream_read_exact,
    read_exact_to_file as _stream_read_exact_to_file,
    stream_file as _stream_stream_file,
)
from docxtool.web.task_paths import (
    cleanup_expired_outputs as _task_paths_cleanup_expired_outputs,
    cleanup_expired_task_records as _task_paths_cleanup_expired_task_records,
    cleanup_expired_tmp as _task_paths_cleanup_expired_tmp,
    cleanup_incomplete_upload as _task_paths_cleanup_incomplete_upload,
    cleanup_output_path as _task_paths_cleanup_output_path,
    ensure_path_within as _task_paths_ensure_path_within,
    startup_cleanup as _task_paths_startup_cleanup,
    task_output_dir as _task_paths_output_dir,
    task_output_path as _task_paths_output_path,
    task_tmp_dir as _task_paths_tmp_dir,
    task_upload_dir as _task_paths_upload_dir,
    task_upload_input_path as _task_paths_upload_input_path,
)
from docxtool.web.task_records import (
    mark_task_processing as _task_records_mark_processing,
    mark_task_terminal as _task_records_mark_terminal,
    record_task_queued as _task_records_record_queued,
)
from docxtool.web.task_recovery import recover_inflight_tasks_on_startup as _task_recovery_recover_inflight
from docxtool.web.task_result import record_task_result as _task_result_record
from docxtool.web.task_worker import (
    run_task_with_execution_boundary as _task_worker_run_with_boundary,
    start_worker_threads as _task_worker_start_threads,
)
from docxtool.web.task_statistics import (
    get_task_statistics as _task_statistics_get,
    log_task_result as _task_statistics_log_result,
)
from docxtool.web.task_state import (
    active_count as _task_state_active_count,
    public_recognition_summary as _task_state_public_recognition_summary,
    public_task_state as _task_state_public_task_state,
    queued_count as _task_state_queued_count,
    task_load as _task_state_task_load,
    task_processing_options as _task_state_processing_options,
    task_queue_info as _task_state_queue_info,
)
from docxtool.web.user_auth import (
    auth_csrf_allowed as _user_auth_csrf_allowed,
    auth_origin_allowed as _user_auth_origin_allowed,
    create_user_session as _user_auth_create_session,
    delete_user_session as _user_auth_delete_session,
    principal_from_headers as _user_auth_principal_from_headers,
    user_cookie_header as _user_auth_cookie_header,
    user_session_from_headers as _user_auth_session_from_headers,
    user_session_hash as _user_auth_session_hash,
)
from docxtool.web.time_check import (
    NETWORK_TIME_URLS as _TIME_CHECK_NETWORK_TIME_URLS,
    fetch_beijing_network_time as _time_check_fetch_beijing_network_time,
    now_local as _time_check_now_local,
    parse_http_date_to_beijing as _time_check_parse_http_date_to_beijing,
    startup_time_check_lines as _time_check_startup_time_check_lines,
)

BASE_DIR = str(project_path())
_SQL_LOCK = threading.Lock()
_DB_PATH = default_database_path()
LOG_DIR = str(runtime_dir("logs", "LOG_DIR"))
RUNTIME_DIR = str(runtime_dir("runtime", "RUNTIME_DIR"))
RUNTIME_TMP_DIR = os.path.join(RUNTIME_DIR, "tmp")
UPLOAD_DIR = str(runtime_dir("uploads", "UPLOAD_DIR"))
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(RUNTIME_TMP_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
DEFAULT_ADMIN_TOKEN = "7654321xxx"
DEFAULT_PROXY_SECRET = "docxtool-proxy-20260601-9ec0d6e2443a4f5f9784f0f04bb62917"
ADMIN_SESSION_COOKIE = "docxtool_admin_session"
ANONYMOUS_USER_COOKIE = "docxtool_anon_user"
ANONYMOUS_USER_COOKIE_MAX_AGE = 2 * 365 * 24 * 60 * 60
USER_SESSION_COOKIE = "docxtool_user_session"
USER_SESSION_MAX_AGE = 30 * 24 * 60 * 60
USER_SESSION_DAYS = 30
USER_SESSION_REFRESH_SECONDS = 300
ADMIN_CSRF_HEADER = "X-CSRF-Token"
DEFAULT_ADMIN_SESSION_TTL_SECONDS = 12 * 60 * 60

_WEAK_SECRETS = {
    "",
    "123456",
    "admin",
    "change-me-admin-token",
    "change-me-proxy-secret",
    "change-me-in-production",
    DEFAULT_ADMIN_TOKEN,
    DEFAULT_PROXY_SECRET,
}

def cors_headers_for_request(origin_header: str, frontend_origin: str = None) -> dict:
    """传入请求 Origin，返回兼容旧全局 FRONTEND_ORIGIN 的 CORS 响应头。"""
    configured_origin = FRONTEND_ORIGIN if frontend_origin is None else str(frontend_origin or "").strip()
    return _config_cors_headers_for_request(origin_header, configured_origin)

def _sql():
    return _db_connect(_DB_PATH)

def _sql_init():
    """兼容旧私有入口，无需传入数据，初始化 Web SQLite 表并返回 None。"""
    _schema_initialize_web_database(_sql, _SQL_LOCK, _seed_default_presets)

def _default_preset_config() -> dict:
    """兼容旧私有入口，无需传入数据，返回默认公文模板配置。"""
    return _preset_defaults_config(
        StyleRule.from_config(),
        PageSettings.from_config(),
        StyleRule.default_for_row,
    )

def _core_feature_config_defaults() -> dict:
    """兼容旧私有入口，无需传入数据，返回默认功能开关配置。"""
    return _preset_defaults_core_features()

def _seed_default_presets(conn):
    """兼容旧私有入口，传入 SQLite 连接，缺省时插入官方默认模板。"""
    _preset_defaults_seed(conn, _default_preset_config, _now_local)

def _first_query_value(values: dict, key: str, default=""):
    """兼容旧私有入口，传入查询字典和键名，返回第一个值。"""
    return _monitor_first_query_value(values, key, default)

def _clamp_int(value, default: int, min_value: int = 1, max_value: int = MAX_MONITOR_PAGE_SIZE) -> int:
    """兼容旧私有入口，传入数值和边界，返回范围内整数。"""
    return _monitor_clamp_int(value, default, min_value, max_value)

def _now_local() -> str:
    """兼容旧私有入口，无需传入数据，返回本地时间字符串。"""
    return _time_check_now_local()

_NETWORK_TIME_URLS = _TIME_CHECK_NETWORK_TIME_URLS

def _parse_http_date_to_beijing(date_header: str):
    """兼容旧私有入口，传入 HTTP Date 头，返回北京时间 datetime。"""
    return _time_check_parse_http_date_to_beijing(date_header)

def _fetch_beijing_network_time(timeout: int = 3):
    """兼容旧私有入口，传入超时秒数，返回网络北京时间。"""
    return _time_check_fetch_beijing_network_time(timeout, _NETWORK_TIME_URLS)

def _startup_time_check_lines() -> list:
    """兼容旧私有入口，无需传入数据，返回启动时间校验日志行。"""
    return _time_check_startup_time_check_lines(
        now_func=_now_local,
        fetch_func=_fetch_beijing_network_time,
    )

def _monitor_query_from(parsed) -> dict:
    """兼容旧私有入口，传入 urlparse 结果，返回监控分页查询。"""
    return _build_monitor_query_from(parsed)

def _normalize_monitor_query(values: dict = None) -> dict:
    """兼容旧私有入口，传入查询字典，返回规范化监控分页参数。"""
    return _build_normalize_monitor_query(values)

def _where_sql(clauses) -> str:
    """兼容旧私有入口，传入 SQL 条件片段，返回 WHERE 子句。"""
    return _monitor_where_sql(clauses)

def _page_count(total: int, size: int) -> int:
    """兼容旧私有入口，传入总数和页大小，返回页数。"""
    return _monitor_page_count(total, size)

def log_sql(task_id, ip, ua, filename, file_size, doc_type,
            paragraphs, headings, body, duration_ms, status="done", error="",
            log_filename="", log_path="", output_dir="", output_filename="", output_path="",
            processing_options="", preset_id="", error_code="", error_message=""):
    """兼容旧入口：传入任务处理结果，写入任务明细和按日统计。"""
    _task_statistics_log_result(
        task_id, ip, ua, filename, file_size, doc_type, paragraphs, headings, body, duration_ms,
        status, error, log_filename, log_path, output_dir, output_filename, output_path,
        processing_options, preset_id, error_code, error_message,
        connect=_sql, sql_lock=_SQL_LOCK, now_func=_now_local,
    )

def record_task_queued(task_id: str, ip: str, ua: str, filename: str, file_size: int = 0,
                       processing_options: str = "", preset_id: str = "", owner_id: str = ""):
    """兼容旧入口：传入任务基础信息，写入或刷新 queued 任务记录。"""
    _task_records_record_queued(
        task_id,
        ip,
        ua,
        filename,
        file_size,
        processing_options,
        preset_id,
        owner_id,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        now_func=_now_local,
        safe_download_filename=_safe_download_filename,
    )

def get_sql_stats(query: dict = None):
    """兼容旧入口：传入监控查询参数，返回任务统计和分页数据。"""
    return _task_statistics_get(
        query,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        normalize_query=_normalize_monitor_query,
        page_count=_page_count,
    )

PORT = int(os.environ.get("PORT", "9527"))
BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
APP_VERSION = package_version()
BUILD_VERSION = os.environ.get("DOCXTOOL_BUILD_VERSION", "").strip()
GIT_REVISION = os.environ.get("DOCXTOOL_GIT_REVISION", "").strip()
STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S")

def _load_secret(name: str, default: str) -> str:
    """兼容旧私有入口，传入环境变量名和默认值，返回实际密钥字符串。"""
    return _secrets_load_secret(name, default)

ADMIN_TOKEN = _load_secret("ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN)
PROXY_SECRET = _load_secret("PROXY_SECRET", DEFAULT_PROXY_SECRET)
PRODUCTION_MODE = _parse_bool(os.environ.get("PRODUCTION_MODE", "false"), False)
try:
    FRONTEND_ORIGIN = parse_frontend_origin(os.environ.get("FRONTEND_ORIGIN", ""), PRODUCTION_MODE)
    COOKIE_SECURE = resolve_cookie_secure(FRONTEND_ORIGIN, os.environ.get("COOKIE_SECURE"), PRODUCTION_MODE)
except ValueError as exc:
    raise SystemExit(f"[配置错误] {exc}") from exc
USER_SESSION_DAYS = max(1, min(365, _parse_int_env("DOCXTOOL_USER_SESSION_DAYS", 30)))
USER_SESSION_MAX_AGE = USER_SESSION_DAYS * 24 * 60 * 60
MAX_SIZE = _parse_int_env("MAX_UPLOAD_SIZE_MB", 10) * 1024 * 1024
UPLOAD_READ_TIMEOUT_SECONDS = _parse_int_env("UPLOAD_READ_TIMEOUT_SECONDS", 15)
UPLOAD_READ_CHUNK_SIZE = 64 * 1024
MAX_WORKERS = 4
MAX_QUEUE = MAX_WORKERS * 2
PROCESS_TIMEOUT = _parse_int_env("PROCESS_TIMEOUT_SECONDS", 60)
RATE_WINDOW = 2
# Accepted originals, generated files, task records, and task logs are
# permanent user records. Only incomplete uploads may be discarded.
FILE_RETENTION_POLICY = "permanent"
FILE_TTL = None
MAX_TASKS = _parse_int_env("MAX_TASKS", 200)
TASK_RETENTION_HOURS = None
MAX_CACHED_TASKS = _parse_int_env("MAX_CACHED_TASKS", 500)
CLEANUP_INTERVAL_MINUTES = _parse_int_env("CLEANUP_INTERVAL_MINUTES", 30)
DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS = 3600
DEFAULT_UPLOAD_LIMIT_COUNT = 10
MAX_FORMAT_CONFIG_HEADER_BYTES = 96 * 1024
MAX_FORMAT_CONFIG_JSON_BYTES = 64 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = _parse_int_env("MAX_DOCX_UNCOMPRESSED_MB", 100) * 1024 * 1024
MAX_DOCX_FILE_COUNT = _parse_int_env("MAX_DOCX_FILE_COUNT", 1000)
MAX_DOCX_XML_BYTES = _parse_int_env("MAX_DOCX_XML_SIZE_MB", 20) * 1024 * 1024
MAX_DOCX_MEDIA_BYTES = _parse_int_env("MAX_DOCX_MEDIA_SIZE_MB", 30) * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = _parse_int_env("MAX_DOCX_COMPRESSION_RATIO", 100)
TRUST_PROXY_HEADERS = _parse_bool(os.environ.get("TRUST_PROXY_HEADERS", "true"), True)
TRUSTED_PROXY_IPS = {
    ip.strip()
    for ip in os.environ.get("TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
    if ip.strip()
}

def _validate_secrets_or_exit() -> None:
    """兼容旧私有入口，无需传入数据，校验当前 Web 启动密钥。"""
    _secrets_validate_required(ADMIN_TOKEN, PROXY_SECRET, _WEAK_SECRETS)

RATE_LIMIT = {}
RATE_LOCK = threading.Lock()
AUTH_RATE_LIMIT = OrderedDict()
TASKS = OrderedDict()
TASKS_LOCK = threading.Lock()
TASK_QUEUE = OrderedDict()
QUEUE_COND = threading.Condition()
WORKERS_STARTED = False
WORKERS_LOCK = threading.Lock()
WORKER_THREADS = []

OUTPUT_DIR = str(runtime_dir("outputs", "OUTPUT_DIR"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

def _startup_cleanup():
    """兼容旧入口：启动时不删除已接收用户文件，返回 no-op 结果。"""
    return _task_paths_startup_cleanup()

def _task_tmp_dir(task_id: str) -> str:
    """兼容旧入口：传入任务 ID，返回该任务运行时临时目录。"""
    return _task_paths_tmp_dir(RUNTIME_TMP_DIR, task_id)

def _task_upload_dir(task_id: str) -> str:
    """兼容旧入口：传入任务 ID，返回该任务原件保存目录。"""
    return _task_paths_upload_dir(UPLOAD_DIR, task_id)


def _task_upload_input_path(task_id: str, orig_name: str = "") -> str:
    """兼容旧入口：传入任务 ID 和原文件名，返回保存后的输入文件路径。"""
    return _task_paths_upload_input_path(UPLOAD_DIR, task_id, orig_name)

def _cleanup_incomplete_upload(task_id: str, extra_path: str = "") -> None:
    """兼容旧入口：删除尚未入库接收的上传半成品。"""
    _task_paths_cleanup_incomplete_upload(UPLOAD_DIR, task_id, extra_path)

def _cleanup_expired_tmp(now: float = None) -> dict:
    """兼容旧入口：输入文件永久保留，不按时间清理。"""
    return _task_paths_cleanup_expired_tmp(now)

def _prune_task_cache() -> None:
    """兼容旧私有入口，无需传入数据，裁剪内存任务缓存并返回 None。"""
    with TASKS_LOCK:
        _task_cache_prune(TASKS, MAX_TASKS, MAX_CACHED_TASKS)

def _recover_inflight_tasks_on_startup() -> int:
    """兼容旧私有入口，无需传入数据，恢复启动前未完成任务并返回数量。"""
    return _task_recovery_recover_inflight(connect=_sql, sql_lock=_SQL_LOCK, now_func=_now_local)

configure_logging(LOG_DIR, to_file=True)
logger = get_logger()
logging.getLogger("docx_tool").setLevel(logging.DEBUG)
for h in logging.getLogger("docx_tool").handlers:
    if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
        h.setLevel(logging.WARNING)

def _read_exact(rfile, length: int, timeout: int = 10) -> bytes:
    """兼容旧入口：从请求流读取指定字节数并返回 bytes。"""
    return _stream_read_exact(rfile, length, timeout)

def _read_exact_to_file(rfile, path: str, length: int, timeout: int = 10, chunk_size: int = UPLOAD_READ_CHUNK_SIZE) -> int:
    """兼容旧入口：从请求流读取指定字节数写入文件并返回写入量。"""
    return _stream_read_exact_to_file(rfile, path, length, timeout, chunk_size)

def _stream_file(path: str, writer, chunk_size: int = 1024 * 1024) -> None:
    """兼容旧入口：把文件按块写入 HTTP 响应 writer。"""
    _stream_stream_file(path, writer, chunk_size)

def _allow(ip: str) -> bool:
    """兼容旧入口：传入 IP，返回普通上传限流是否允许。"""
    return _rate_allow(ip, rate_limit=RATE_LIMIT, rate_lock=RATE_LOCK, rate_window=RATE_WINDOW)


def _auth_rate_allow(scope: str, key: str, window: int, limit: int) -> tuple[bool, int]:
    """兼容旧入口：传入作用域、键、窗口和次数，返回是否允许及等待秒数。"""
    return _rate_auth_rate_allow(
        scope,
        key,
        window,
        limit,
        auth_rate_limit=AUTH_RATE_LIMIT,
        rate_lock=RATE_LOCK,
    )

def _is_ip(value: str) -> bool:
    """兼容旧入口：传入字符串，返回是否为合法 IPv4/IPv6。"""
    return _client_is_ip(value)

def _is_ip_banned(ip: str) -> bool:
    """兼容旧入口：传入 IP，返回是否已被管理后台封禁。"""
    return _rate_is_ip_banned(ip, connect=_sql, sql_lock=_SQL_LOCK)

def _ban_ip(ip: str, reason: str = "") -> None:
    """兼容旧入口：传入 IP 和原因，写入封禁记录。"""
    _rate_ban_ip(ip, reason, connect=_sql, sql_lock=_SQL_LOCK)

def _unban_ip(ip: str) -> None:
    """兼容旧入口：传入 IP，删除封禁记录。"""
    _rate_unban_ip(ip, connect=_sql, sql_lock=_SQL_LOCK)

def _banned_ips():
    """兼容旧入口：不传参数，返回封禁 IP 字典列表。"""
    return _rate_banned_ips(connect=_sql, sql_lock=_SQL_LOCK)

def _ip_activity(ip: str, limit: int = 100):
    """兼容旧入口：传入 IP 和数量上限，返回该 IP 最近任务列表。"""
    return _rate_ip_activity(ip, limit, connect=_sql, sql_lock=_SQL_LOCK)

def _ip_upload_count(ip: str, window_seconds: int = 0) -> int:
    """兼容旧入口：传入 IP 和窗口秒数，返回窗口内上传任务数量。"""
    return _rate_ip_upload_count(ip, window_seconds, connect=_sql, sql_lock=_SQL_LOCK)

def _upload_limit_exceeded(ip: str) -> bool:
    """兼容旧入口：传入 IP，返回是否超过上传次数限制。"""
    return _rate_upload_limit_exceeded(
        ip,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        default_window_seconds=DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS,
        default_count=DEFAULT_UPLOAD_LIMIT_COUNT,
    )

def _settings_get(key: str, default: str = "") -> str:
    """兼容旧入口：传入设置键和默认值，返回 settings 表字符串值。"""
    return _rate_settings_get(key, default, connect=_sql, sql_lock=_SQL_LOCK)

def _settings_set(key: str, value: str) -> None:
    """兼容旧入口：传入设置键值，写入 settings 表。"""
    _rate_settings_set(key, value, connect=_sql, sql_lock=_SQL_LOCK)

def _limit_settings() -> dict:
    """兼容旧入口：不传参数，返回上传频率限制配置。"""
    return _rate_limit_settings(
        connect=_sql,
        sql_lock=_SQL_LOCK,
        default_window_seconds=DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS,
        default_count=DEFAULT_UPLOAD_LIMIT_COUNT,
    )

def _save_limit_settings(enabled: bool, window_seconds: int, count: int) -> None:
    """兼容旧入口：传入开关、窗口和次数，保存上传频率限制配置。"""
    _rate_save_limit_settings(enabled, window_seconds, count, connect=_sql, sql_lock=_SQL_LOCK)

def _active_count() -> int:
    """兼容旧入口：不传参数，返回当前正在处理的任务数量。"""
    return _task_state_active_count(TASKS, TASKS_LOCK)

def _queued_count() -> int:
    """兼容旧入口：不传参数，返回当前排队任务数量。"""
    return _task_state_queued_count(TASK_QUEUE, QUEUE_COND)

def _task_load() -> int:
    """兼容旧入口：不传参数，返回处理中和排队中的总任务负载。"""
    return _task_state_task_load(TASKS, TASKS_LOCK, TASK_QUEUE, QUEUE_COND)

def _task_queue_info(task_id: str) -> dict:
    """兼容旧入口：传入任务 ID，返回该任务当前队列位置。"""
    return _task_state_queue_info(task_id, TASK_QUEUE, QUEUE_COND)


def _load_public_task_from_db(task_id: str, owner_id: str = "") -> dict:
    """传入任务 ID 和所有者 ID，从数据库读取公开状态所需的任务行。"""
    with _SQL_LOCK:
        conn = _sql()
        row = conn.execute("SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner_id)).fetchone()
        conn.close()
    return dict(row) if row else {}

def _public_task_state(task_id: str, owner_id: str = "") -> dict:
    """兼容旧入口：传入任务 ID 和所有者 ID，返回脱敏后的公开任务状态。"""
    return _task_state_public_task_state(
        task_id,
        owner_id,
        tasks=TASKS,
        tasks_lock=TASKS_LOCK,
        task_queue=TASK_QUEUE,
        queue_cond=QUEUE_COND,
        load_task=_load_public_task_from_db,
    )


def _safe_file_identifier(filename: str) -> str:
    """兼容旧私有入口，传入文件名，返回日志用短标识。"""
    return _file_safe_file_identifier(filename)


def _sanitize_internal_error_detail(value: object, limit: int = 500) -> str:
    """兼容旧私有入口，传入错误对象，返回脱敏诊断文本。"""
    return _file_sanitize_internal_error_detail(value, limit)


def _public_recognition_summary(doc_data) -> dict:
    """兼容旧入口：传入文档数据对象，返回不含正文的识别摘要。"""
    return _task_state_public_recognition_summary(doc_data)

def _task_output_dir(task_id: str) -> str:
    """兼容旧入口：传入任务 ID，返回该任务输出目录。"""
    return _task_paths_output_dir(OUTPUT_DIR, task_id)

def _task_output_path(task_id: str) -> str:
    """兼容旧入口：传入任务 ID，返回该任务结果 DOCX 路径。"""
    return _task_paths_output_path(OUTPUT_DIR, task_id)

def _ensure_path_within(base_dir: str, path: str) -> str:
    """兼容旧入口：确认目标路径位于指定根目录内并返回绝对路径。"""
    return _task_paths_ensure_path_within(base_dir, path)

def _cleanup_output_path(path: str) -> None:
    """兼容旧入口：删除无效生成输出，不触碰已接收上传原件。"""
    _task_paths_cleanup_output_path(path)

def _task_processing_options(format_config: dict = None, request_meta: dict = None) -> str:
    """兼容旧入口：传入格式配置和请求元数据，返回任务处理选项 JSON。"""
    return _task_state_processing_options(format_config, request_meta)

def _mark_task_processing(task_id: str) -> None:
    """兼容旧入口：传入任务 ID，将数据库任务状态标记为处理中。"""
    _task_records_mark_processing(task_id, connect=_sql, sql_lock=_SQL_LOCK, now_func=_now_local)

def _mark_task_terminal(task_id: str, status: str, error: str = "", output_path: str = "", output_filename: str = "", log_path: str = "", log_filename: str = "") -> None:
    """兼容旧入口：传入任务 ID 和终态字段，将数据库任务状态标记为最终状态。"""
    _task_records_mark_terminal(
        task_id,
        status,
        error,
        output_path,
        output_filename,
        log_path,
        log_filename,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        now_func=_now_local,
    )

def _enqueue_task(task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                  format_config: dict = None, request_meta: dict = None,
                  compatibility_warnings: list[str] = None, owner_id: str = "") -> dict:
    """Persist a validated upload and make it visible to workers.

    入队顺序不能调整：先检查队列容量，再写数据库 queued 记录，最后写入内存
    队列并通知 worker。这样监控页、状态接口和后台线程看到的是同一个任务。
    容量不足时调用方会删除未入队的上传半成品，不会留下伪装成功的任务行。
    """
    now = time.time()
    try:
        file_size = os.path.getsize(input_path) if input_path and os.path.exists(input_path) else 0
    except OSError:
        file_size = 0
    request_meta = request_meta or {}
    processing_options = _task_processing_options(format_config, request_meta)
    preset_id = str(request_meta.get("preset_id", "") or "")
    with QUEUE_COND:
        active = _active_count()
        queued = len(TASK_QUEUE)
        if active + queued >= MAX_QUEUE:
            raise OverflowError("QUEUE_FULL: 服务器繁忙，请稍后再试")
        record_task_queued(task_id, ip, ua, orig_name, file_size, processing_options=processing_options, preset_id=preset_id, owner_id=owner_id)
        TASK_QUEUE[task_id] = (input_path, orig_name, ip, ua, format_config, request_meta or {})
        info = _task_queue_info(task_id)
        QUEUE_COND.notify()
    with TASKS_LOCK:
        TASKS[task_id] = {
            "status": "queued",
            "time": now,
            "queued_at": now,
            "uses_format_config": bool(format_config),
            "preset_name": request_meta.get("preset_name", ""),
            "preset_id": preset_id,
            "processing_mode": request_meta.get("processing_mode", ""),
            "filename": orig_name,
            "ip": ip,
            "processing_options": processing_options,
            "compatibility_warnings": list(compatibility_warnings or []),
            "owner_id": owner_id,
        }
    _prune_task_cache()
    return info

def _task_process_body(task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                       format_config: dict = None, request_meta: dict = None) -> dict:
    """Run the actual DOCX pipeline and return a structured result.

    该函数在子进程内执行时是识别和导出的进程边界：Web 线程只传入文件路径、
    格式配置和脱敏请求元数据，子进程负责 DOCX 导入、识别、导出和完整性
    校验。返回值必须是可序列化字典，且失败信息要经过脱敏，避免把正文、
    绝对路径或 traceback 暴露给普通用户。
    """
    t0 = time.time()
    request_meta = request_meta or {}
    file_id = _safe_file_identifier(orig_name)
    log_path = make_document_log_path("document", log_dir=LOG_DIR, suffix=task_id[:8])
    log_filename = os.path.basename(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [INFO ] docx_tool | [Task] {task_id[:8]} log created file_id={file_id}\n")
    token = set_context_log_path(log_path)
    try:
        rules, settings, features = load_rules_and_settings(format_config)
        rules = rules or [StyleRule.default_for_row(i) for i in range(10)]
        settings = settings or PageSettings()
        features = features or {}
        features.setdefault("numbered_bold_enabled", True)
        features.setdefault("punctuation_enabled", True)
        features.setdefault("page_number_enabled", True)
        processing_options = features.setdefault("processing", {})
        if not isinstance(processing_options, dict):
            processing_options = {}
            features["processing"] = processing_options
        # Browser smart mode is structural preservation: split only reliable
        # visual structure, then recognize and style it without rewriting the
        # source text.  Strict mode remains available to explicit callers.
        processing_options.setdefault(
            "strategy",
            str(request_meta.get("processing_strategy", "") or "structural"),
        )
        recognition_options = features.setdefault("recognition", {})
        if not isinstance(recognition_options, dict):
            recognition_options = {}
            features["recognition"] = recognition_options
        recognition_options.setdefault("mode", "authoritative")
        for key, value in _core_feature_config_defaults().items():
            features.setdefault(key, value)
        body_rule = rules[5] if len(rules) > 5 else StyleRule.default_for_row(5)
        letterhead_summary = features.get("letterhead", {})
        letterhead_agencies = letterhead_summary.get("agencies", [])
        logger.info(
            f"[Task] {task_id[:8]} start file_id={file_id} log={log_filename} "
            f"preset={request_meta.get('preset_name','')} mode={processing_options.get('strategy', 'structural')} "
            f"frontend_config={bool(format_config)} body={body_rule.font}/{body_rule.font_size_label} "
            f"margins=top{settings.margin_top_cm} bottom{settings.margin_bottom_cm} "
            f"left{settings.margin_left_cm} right{settings.margin_right_cm} "
            f"line_spacing={settings.line_spacing_value} numbered_bold_enabled={features['numbered_bold_enabled']} "
            f"letterhead_enabled={bool(letterhead_summary.get('enabled', False))} "
            f"letterhead_mode={letterhead_summary.get('issuance_mode', 'single')} "
            f"letterhead_agencies={len(letterhead_agencies) if isinstance(letterhead_agencies, list) else 0} "
            f"letterhead_scope={letterhead_summary.get('joint_mark_scope', 'all_agencies')}"
        )
        importer = DocxImporter()
        doc_data = importer.load(
            input_path,
            rules,
            features=features,
            recognition_mode=str(recognition_options.get("mode", "authoritative")),
        )
        output_dir = _ensure_path_within(OUTPUT_DIR, _task_output_dir(task_id))
        os.makedirs(output_dir, exist_ok=True)
        output_path = _ensure_path_within(output_dir, _task_output_path(task_id))
        download_name = _safe_download_filename(orig_name)
        try:
            export_stats = export_doc(
                doc_data,
                rules,
                settings,
                output_path,
                numbered_bold_enabled=features["numbered_bold_enabled"],
                page_number_enabled=features["page_number_enabled"],
                numbering_options=features.get("numbering"),
                page_number_options=features.get("page_number"),
                signature_block_options=features.get("signature_block"),
                table_format_options=features.get("table_format"),
                cleanup_options=features.get("cleanup"),
                letterhead_options=features.get("letterhead"),
            )
        except TypeError:
            export_stats = export_doc(
                doc_data,
                rules,
                settings,
                output_path,
                numbered_bold_enabled=features["numbered_bold_enabled"],
            )
        export_stats = export_stats or {}
        try:
            validate_docx_integrity(output_path)
        except DocxIntegrityError as exc:
            logger.error(
                f"[Task] {task_id[:8]} generated DOCX integrity check failed "
                f"code={exc.code} detail={exc.message}"
            )
            duration = round(time.time() - t0, 2)
            return {
                "status": "error",
                "log_filename": log_filename,
                "log_path": log_path,
                "output_dir": output_dir,
                "output_filename": "",
                "output_path": "",
                "duration_s": duration,
                "duration_ms": int(duration * 1000),
                "doc_mode": doc_data.doc_mode or "UNKNOWN",
                "paragraphs": len(doc_data.paragraphs),
                "headings": sum(1 for pd in doc_data.paragraphs if pd.type_id.startswith("heading")),
                "body": sum(1 for pd in doc_data.paragraphs if pd.type_id == "body"),
                "error": "",
                "error_code": "OUTPUT_DOCX_INVALID",
                "error_message": _sanitize_internal_error_detail(f"{exc.code}: {exc.message}"),
                "recognition_summary": _public_recognition_summary(doc_data),
            }
        duration = round(time.time() - t0, 2)
        hc = sum(1 for pd in doc_data.paragraphs if pd.type_id.startswith("heading"))
        bc = sum(1 for pd in doc_data.paragraphs if pd.type_id == "body")
        return {
            "status": "done",
            "log_filename": log_filename,
            "log_path": log_path,
            "output_dir": output_dir,
            "output_filename": download_name,
            "output_path": output_path,
            "duration_s": duration,
            "duration_ms": int(duration * 1000),
            "doc_mode": doc_data.doc_mode or "UNKNOWN",
            "paragraphs": len(doc_data.paragraphs),
            "headings": hc,
            "body": bc,
            "error": "",
            "error_code": "",
            "error_message": "",
            "recognition_summary": _public_recognition_summary(doc_data),
            "compatibility_warnings": list(export_stats.get("compatibility_warnings", []) or []),
        }
    except Exception as exc:
        logger.error("[Task] %s internal failure type=%s", task_id[:8], type(exc).__name__)
        return {
            "status": "error",
            "log_filename": log_filename,
            "log_path": log_path,
            "output_dir": "",
            "output_filename": "",
            "output_path": "",
            "duration_s": round(time.time() - t0, 2),
            "duration_ms": 0,
            "doc_mode": "",
            "paragraphs": 0,
            "headings": 0,
            "body": 0,
            "error": "",
            "error_code": "TASK_PROCESSING_ERROR",
            "error_message": _sanitize_internal_error_detail(exc),
            "recognition_summary": {},
        }
    finally:
        reset_context_log_path(token)

def _task_process_entry(result_queue, task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                        format_config: dict = None, request_meta: dict = None) -> None:
    try:
        result = _task_process_body(task_id, input_path, orig_name, ip, ua, format_config, request_meta)
    except Exception as exc:
        result = {
            "status": "error",
            "log_filename": "",
            "log_path": "",
            "output_dir": "",
            "output_filename": "",
            "output_path": "",
            "duration_s": 0,
            "duration_ms": 0,
            "doc_mode": "",
            "paragraphs": 0,
            "headings": 0,
            "body": 0,
            "error": "",
            "error_code": "TASK_PROCESSING_ERROR",
            "error_message": _sanitize_internal_error_detail(f"{type(exc).__name__}: {exc}"),
            "recognition_summary": {},
        }
    try:
        result_queue.put(result)
    except Exception:
        pass

def _task_process_direct(task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                         format_config: dict = None, request_meta: dict = None) -> dict:
    return _task_process_body(task_id, input_path, orig_name, ip, ua, format_config, request_meta)

def _task_process_subprocess(task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                             format_config: dict = None, request_meta: dict = None) -> dict:
    """Execute one task in a spawned child process with a hard timeout.

    worker 线程不能直接信任 DOCX 解析和 OOXML 导出过程；spawn 子进程隔离
    崩溃、死循环和内存污染。超时后先 terminate，再 kill，随后清理本轮输出
    目录；已接收的原始上传由永久保留策略保护，不在这里删除。
    """
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    process = ctx.Process(
        target=_task_process_entry,
        args=(result_queue, task_id, input_path, orig_name, ip, ua, format_config, request_meta),
        daemon=True,
    )
    process.start()
    process.join(PROCESS_TIMEOUT)
    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            try:
                process.kill()
            except Exception:
                pass
            process.join(5)
        _cleanup_output_path(_task_output_dir(task_id))
        return {
            "status": "timeout",
            "log_filename": "",
            "log_path": "",
            "output_dir": "",
            "output_filename": "",
            "output_path": "",
            "duration_s": PROCESS_TIMEOUT,
            "duration_ms": PROCESS_TIMEOUT * 1000,
            "doc_mode": "",
            "paragraphs": 0,
            "headings": 0,
            "body": 0,
            "error": f"排版超时：超过 {PROCESS_TIMEOUT} 秒",
            "error_code": "TASK_TIMEOUT",
            "error_message": f"排版超时：超过 {PROCESS_TIMEOUT} 秒",
        }
    try:
        result = result_queue.get(timeout=2)
    except Empty:
        result = {
            "status": "error",
            "log_filename": "",
            "log_path": "",
            "output_dir": "",
            "output_filename": "",
            "output_path": "",
            "duration_s": 0,
            "duration_ms": 0,
            "doc_mode": "",
            "paragraphs": 0,
            "headings": 0,
            "body": 0,
            "error": f"子进程未返回结果，退出码={process.exitcode}",
            "error_code": "TASK_PROCESSING_ERROR",
            "error_message": f"子进程未返回结果，退出码={process.exitcode}",
        }
    if result.get("status") != "done":
        _cleanup_output_path(_task_output_dir(task_id))
    return result

def _record_task_result(task_id: str, input_path: str, orig_name: str, ip: str, ua: str, result: dict) -> None:
    """兼容旧私有入口，传入任务结果，统一同步数据库、内存状态和日志。"""
    _task_result_record(
        task_id,
        input_path,
        orig_name,
        ip,
        ua,
        result,
        tasks=TASKS,
        tasks_lock=TASKS_LOCK,
        log_task_result=log_sql,
        cleanup_output_path=_cleanup_output_path,
        task_output_dir=_task_output_dir,
        prune_task_cache=_prune_task_cache,
        safe_file_identifier=_safe_file_identifier,
        logger=logger,
        process_timeout=PROCESS_TIMEOUT,
    )

def _worker_loop():
    """Consume queued tasks sequentially inside one daemon worker thread."""
    while True:
        with QUEUE_COND:
            while not TASK_QUEUE:
                QUEUE_COND.wait()
            task_id, payload = TASK_QUEUE.popitem(last=False)
        input_path, orig_name, ip, ua, format_config, request_meta = payload
        _mark_task_processing(task_id)
        with TASKS_LOCK:
            task = TASKS.get(task_id, {})
            task["status"] = "processing"
            task["started_at"] = time.time()
            task["queue_ahead"] = 0
            task["queue_position"] = 0
            TASKS[task_id] = task
        _process_task(task_id, input_path, orig_name, ip, ua, format_config, request_meta)

def _ensure_workers_started():
    global WORKERS_STARTED
    with WORKERS_LOCK:
        if WORKERS_STARTED:
            return
        WORKER_THREADS.extend(_task_worker_start_threads(MAX_WORKERS, _worker_loop))
        WORKERS_STARTED = True

def _process_task(task_id: str, input_path: str, orig_name: str = "upload.docx", ip: str = "", ua: str = "",
                  format_config: dict = None, request_meta: dict = None):
    """Choose the execution boundary and persist the terminal task state.

    测试或显式主线程调用走 direct 路径，真实 worker 线程走子进程路径。两条
    路径最终都必须进入 ``_record_task_result``，这是数据库、内存状态、日志
    和下载路径保持一致的唯一收口。
    """
    _task_worker_run_with_boundary(
        task_id,
        input_path,
        orig_name,
        ip,
        ua,
        format_config,
        request_meta,
        is_main_thread=threading.current_thread() is threading.main_thread(),
        direct_runner=_task_process_direct,
        subprocess_runner=_task_process_subprocess,
        record_result=_record_task_result,
    )
    # A valid upload remains available even when formatting fails, so users
    # and administrators can inspect the original document later.

def _cleanup_expired_outputs(now: float = None) -> dict:
    """兼容旧入口：生成文件永久保留，不按时间清理。"""
    return _task_paths_cleanup_expired_outputs(now)

def _cleanup_expired_task_records(now: float = None) -> dict:
    """兼容旧入口：任务记录永久保留，不按时间清理。"""
    return _task_paths_cleanup_expired_task_records(now)

def _cleaner_loop():
    """兼容旧私有入口：不传参数，运行永久保留策略下的后台维护循环。"""
    _maintenance_cleaner_loop(CLEANUP_INTERVAL_MINUTES)

threading.Thread(target=_cleaner_loop, daemon=True).start()

def _error_payload(code: str, message: str, field: str = "", reason: str = "") -> dict:
    """兼容旧入口：传入错误码和消息，返回 API 错误响应字典。"""
    return _request_error_payload(code, message, field, reason)

def _cookie_value(cookie_header: str, name: str) -> str:
    """兼容旧入口：从 Cookie 头中读取指定名称的值。"""
    return _request_cookie_value(cookie_header, name)

def _session_cookie_settings() -> str:
    """兼容旧入口：根据当前全局配置返回管理员会话 Cookie 模板。"""
    return _request_admin_session_cookie_settings(
        ADMIN_SESSION_COOKIE,
        DEFAULT_ADMIN_SESSION_TTL_SECONDS,
        secure=COOKIE_SECURE,
    )

def _anonymous_user_signing_key() -> bytes:
    """兼容旧入口：不传参数，返回匿名用户 cookie 签名派生密钥。"""
    return _anon_user_signing_key(PROXY_SECRET, DEFAULT_PROXY_SECRET)

def _anonymous_user_signature(payload: str) -> str:
    """兼容旧入口：传入 payload，返回匿名用户 cookie 的签名字符串。"""
    return _anon_user_signature(payload, proxy_secret=PROXY_SECRET, default_proxy_secret=DEFAULT_PROXY_SECRET)

def _create_anonymous_user(now: int = None) -> dict:
    """兼容旧入口：传入可选当前时间，返回新的匿名 owner 身份。"""
    return _anon_create_user(
        _now_unix() if now is None else int(now),
        max_age=ANONYMOUS_USER_COOKIE_MAX_AGE,
        proxy_secret=PROXY_SECRET,
        default_proxy_secret=DEFAULT_PROXY_SECRET,
    )

def _parse_anonymous_user(token: str, now: int = None) -> dict:
    """兼容旧入口：传入匿名 token 和可选当前时间，返回校验后的身份或空字典。"""
    return _anon_parse_user(
        token,
        _now_unix() if now is None else int(now),
        max_age=ANONYMOUS_USER_COOKIE_MAX_AGE,
        proxy_secret=PROXY_SECRET,
        default_proxy_secret=DEFAULT_PROXY_SECRET,
    )

def _anonymous_user_cookie_header(token: str) -> str:
    """兼容旧入口：传入匿名 token，返回设置匿名身份的 Set-Cookie 值。"""
    return _anon_cookie_header(
        token,
        cookie_name=ANONYMOUS_USER_COOKIE,
        max_age=ANONYMOUS_USER_COOKIE_MAX_AGE,
        secure=COOKIE_SECURE,
    )


def _anonymous_user_cookie_clear_header() -> str:
    """兼容旧入口：不传参数，返回清除匿名身份 cookie 的 Set-Cookie 值。"""
    return _anon_cookie_clear_header(cookie_name=ANONYMOUS_USER_COOKIE, secure=COOKIE_SECURE)

def _anonymous_user_from_headers(headers, cookie_header: str = "") -> tuple[dict, str]:
    """兼容旧入口：传入请求头和 Cookie 头，返回匿名身份和可能的新 Cookie。"""
    return _anon_user_from_headers(
        headers,
        cookie_header,
        cookie_name=ANONYMOUS_USER_COOKIE,
        max_age=ANONYMOUS_USER_COOKIE_MAX_AGE,
        proxy_secret=PROXY_SECRET,
        default_proxy_secret=DEFAULT_PROXY_SECRET,
        now=_now_unix,
        secure=COOKIE_SECURE,
    )

def _anonymous_template_origin_allowed(headers) -> bool:
    """兼容旧入口：传入请求头，返回匿名模板接口的 Origin 是否允许。"""
    return _anon_template_origin_allowed(
        headers,
        frontend_origin=FRONTEND_ORIGIN,
        is_local_origin_host=_is_local_origin_host,
    )


def _user_session_hash(token: str) -> str:
    """兼容旧入口：传入明文 session token，返回数据库存储用哈希。"""
    return _user_auth_session_hash(token)


def _user_cookie_header(token: str, clear: bool = False, persistent: bool = True) -> str:
    """兼容旧入口：传入 token 和清理/持久化开关，返回用户 Set-Cookie 值。"""
    return _user_auth_cookie_header(
        token,
        cookie_name=USER_SESSION_COOKIE,
        max_age=USER_SESSION_MAX_AGE,
        secure=COOKIE_SECURE,
        clear=clear,
        persistent=persistent,
    )


def _create_user_session(user_id: str, user_agent: str = "", remote_ip: str = "") -> dict:
    """兼容旧入口：传入用户 ID 和请求信息，创建用户 session 并返回 token 信息。"""
    return _user_auth_create_session(
        user_id,
        user_agent,
        remote_ip,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        max_age=USER_SESSION_MAX_AGE,
        now_func=_now_unix,
    )


def _user_session_from_headers(headers) -> dict:
    """兼容旧入口：传入请求头，返回有效用户 session 或空字典。"""
    return _user_auth_session_from_headers(
        headers,
        cookie_name=USER_SESSION_COOKIE,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        refresh_seconds=USER_SESSION_REFRESH_SECONDS,
        now_func=_now_unix,
    )


def _delete_user_session(headers) -> None:
    """兼容旧入口：传入请求头，删除当前用户 session，无返回值。"""
    _user_auth_delete_session(
        headers,
        cookie_name=USER_SESSION_COOKIE,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        refresh_seconds=USER_SESSION_REFRESH_SECONDS,
        now_func=_now_unix,
    )


def _principal(headers, client_address=None) -> dict:
    """兼容旧入口：传入请求头和可选客户端地址，返回统一用户/匿名 principal。"""
    return _user_auth_principal_from_headers(
        headers,
        user_cookie_name=USER_SESSION_COOKIE,
        anonymous_cookie_name=ANONYMOUS_USER_COOKIE,
        get_user_session=_user_session_from_headers,
        get_anonymous_user=_anonymous_user_from_headers,
    )


def _auth_origin_allowed(headers) -> bool:
    """兼容旧入口：传入请求头，返回认证接口 Origin 是否允许。"""
    return _user_auth_origin_allowed(headers, _anonymous_template_origin_allowed)


def _auth_csrf_allowed(headers, principal) -> bool:
    """兼容旧入口：传入请求头和 principal，返回用户 CSRF 是否通过。"""
    return _user_auth_csrf_allowed(headers, principal, csrf_header_name="X-CSRF-Token")


def _migrate_anonymous_owner(conn, anonymous_id: str, user_id: str) -> None:
    """兼容旧入口：传入事务连接、匿名 ID 和用户 ID，迁移匿名 owner 资源。"""
    _owner_migration_migrate_owner(conn, anonymous_id, user_id)


def _migrate_anonymous_resources(anonymous_id: str, user_id: str) -> None:
    """兼容旧入口：传入匿名 ID 和用户 ID，在独立事务中迁移匿名 owner 资源。"""
    _owner_migration_migrate_resources(anonymous_id, user_id, connect=_sql, sql_lock=_SQL_LOCK)

def _now_unix() -> int:
    """兼容旧入口：不传参数，返回当前 Unix 秒级时间戳。"""
    return _admin_auth_now_unix()

def _prune_expired_admin_sessions(conn=None) -> None:
    """兼容旧入口：传入可选数据库连接，删除过期管理员会话。"""
    own = False
    if conn is None:
        own = True
        conn = _sql()
    try:
        _admin_auth_prune_expired_sessions(conn, now=_now_unix())
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()

def _create_admin_session(user_agent: str = "", remote_ip: str = "") -> dict:
    """兼容旧入口：传入 UA 和远端 IP，创建管理员 session 并返回 token 信息。"""
    return _admin_auth_create_session(
        user_agent,
        remote_ip,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        ttl_seconds=DEFAULT_ADMIN_SESSION_TTL_SECONDS,
        now_func=_now_unix,
    )

def _get_admin_session(session_id: str) -> dict:
    """兼容旧入口：传入 session ID，返回有效管理员会话或空字典。"""
    return _admin_auth_get_session(
        session_id,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        ttl_seconds=DEFAULT_ADMIN_SESSION_TTL_SECONDS,
        now_func=_now_unix,
    )

def _delete_admin_session(session_id: str) -> None:
    """兼容旧入口：传入 session ID，删除管理员会话。"""
    _admin_auth_delete_session(session_id, connect=_sql, sql_lock=_SQL_LOCK)

def _legacy_admin_token_from(parsed, headers, cookie_header: str = "") -> str:
    """兼容旧入口：传入 URL、请求头和 Cookie，返回 legacy 管理 token。"""
    return _admin_auth_legacy_token_from(parsed, headers, cookie_header)

def _admin_authorized(parsed, headers, cookie_header: str = "") -> bool:
    """兼容旧入口：传入请求上下文，返回 legacy 管理 token 是否有效。"""
    return _admin_auth_authorized(parsed, headers, cookie_header, admin_token=ADMIN_TOKEN)

def _admin_session_from_headers(headers, cookie_header: str = "") -> dict:
    """兼容旧入口：传入请求头和 Cookie，返回当前管理员 session。"""
    return _admin_auth_session_from_headers(
        headers,
        cookie_header,
        cookie_name=ADMIN_SESSION_COOKIE,
        get_session=_get_admin_session,
    )

def _admin_request_context(parsed, headers, cookie_header: str = "") -> dict:
    """兼容旧入口：传入请求上下文，返回管理员授权上下文。"""
    return _admin_auth_request_context(
        parsed,
        headers,
        cookie_header,
        cookie_name=ADMIN_SESSION_COOKIE,
        admin_token=ADMIN_TOKEN,
        get_session=_get_admin_session,
    )

def _file_api_authorized(headers, client_address=None) -> bool:
    header_token = headers.get("X-Proxy-Secret", "") if headers else ""
    if _compare_secret(header_token, PROXY_SECRET):
        return True
    # In production, Nginx also appears as a local peer. Do not let that
    # trusted-proxy topology turn a direct public request into an authorized
    # file API call; only the Worker-injected secret is sufficient.
    if PRODUCTION_MODE:
        return False
    if not client_address:
        return False
    try:
        return ipaddress.ip_address(str(client_address[0])).is_loopback
    except ValueError:
        return False

def _format_config_error(code: str, message: str, *, field: str = "", reason: str = "") -> FormatConfigRequestError:
    """兼容旧入口：传入稳定错误码和安全消息，返回格式配置请求错误。"""
    return _format_config_error_impl(code, message, field=field, reason=reason)

def _decode_format_config(headers) -> dict:
    """兼容旧入口：解码请求头中的格式配置并返回已验证配置。"""
    return _format_decode_format_config(
        headers,
        max_header_bytes=MAX_FORMAT_CONFIG_HEADER_BYTES,
        max_json_bytes=MAX_FORMAT_CONFIG_JSON_BYTES,
    )

def _upload_request_meta(headers) -> dict:
    """兼容旧入口：从上传请求头读取处理模式、模板和预设元数据。"""
    return _format_upload_request_meta(headers)


def _processing_strategy_from_mode(value: object) -> str:
    """兼容旧入口：将外部处理模式映射为内部 processing strategy。"""
    return _format_processing_strategy_from_mode(value)


def _validate_requested_processing_mode(format_config: dict | None, request_meta: dict) -> None:
    """兼容旧入口：校验 header 处理模式与格式配置并写入 request_meta。"""
    _format_validate_requested_processing_mode(format_config, request_meta)

def _admin_token_from(parsed) -> str:
    """兼容旧入口：从 URL 查询参数中读取 legacy 管理员 token。"""
    return _request_admin_token_from_query(parsed)

def _admin_url(path: str, token: str = "") -> str:
    """兼容旧入口：返回管理页 URL，legacy token 参数不再拼接进链接。"""
    return _request_admin_url(path, token)

def _admin_hidden_input(token: str = "") -> str:
    """兼容旧入口：传入 legacy token，返回隐藏 input HTML。"""
    return _request_hidden_input("token", token)

def _csrf_hidden_input(csrf_token: str = "") -> str:
    """兼容旧入口：传入 CSRF token，返回隐藏 input HTML。"""
    return _request_hidden_input("csrf_token", csrf_token)

def _csrf_header_value(headers) -> str:
    """兼容旧入口：从请求头中读取当前配置的 CSRF token。"""
    return _request_csrf_header_value(headers, ADMIN_CSRF_HEADER)

def _admin_cookie_header(session_id: str) -> str:
    cookie = _session_cookie_settings()
    return cookie.format(session_id=session_id)

def _validate_admin_csrf(headers, cookie_header: str = "") -> bool:
    """兼容旧入口：传入请求头和 Cookie，返回管理员 CSRF 校验是否通过。"""
    return _admin_auth_validate_csrf(
        headers,
        cookie_header,
        cookie_name=ADMIN_SESSION_COOKIE,
        csrf_header_name=ADMIN_CSRF_HEADER,
        get_session=_get_admin_session,
    )

def _route_path(path: str) -> str:
    """兼容旧入口：归一化 Worker 转发路径。"""
    return _request_route_path(path)

def _json_dumps(obj: dict) -> str:
    """兼容旧入口：把响应对象序列化为紧凑 JSON 字符串。"""
    return _request_json_dumps(obj)

def _parse_json_body(body: bytes) -> dict:
    """兼容旧入口：解析 UTF-8 JSON 请求体并要求顶层为对象。"""
    return _request_parse_json_body(body)

def _normalize_template_name(name: str) -> str:
    """兼容旧入口：传入模板名称，返回压缩空白后的合法名称。"""
    return _preset_normalize_template_name(name)

def _normalize_template_id(value: str) -> str:
    """兼容旧入口：传入模板 ID，返回只含安全字符的模板 ID。"""
    return _preset_normalize_template_id(value)

def _validate_template_config(config_obj: dict) -> dict:
    """兼容旧入口：传入模板配置对象，返回归一化后的可持久化配置。"""
    return _preset_validate_template_config(config_obj, core_feature_defaults=_core_feature_config_defaults())

def _preset_row_to_dict(row, include_config: bool = False) -> dict:
    """兼容旧入口：传入数据库行和配置开关，返回 API 用模板字典。"""
    return _preset_row_to_dict_impl(row, include_config)

def _list_presets(owner_id: str = "") -> list:
    """兼容旧入口：传入 owner ID，返回该 owner 可见的模板列表。"""
    return _preset_store_list(owner_id, connect=_sql, sql_lock=_SQL_LOCK, row_to_dict=_preset_row_to_dict)

def _get_preset(preset_id: str, owner_id: str = "", public_only: bool = False) -> dict:
    """兼容旧入口：传入模板 ID 和 owner ID，返回模板详情或空字典。"""
    return _preset_store_get(
        preset_id,
        owner_id,
        public_only,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        row_to_dict=_preset_row_to_dict,
    )

def _insert_preset(name: str, description: str, config_json: dict, is_system: bool = False,
                   is_default: bool = False, preset_id: str = "", owner_id: str = "",
                   visibility: str = "public") -> dict:
    """兼容旧入口：传入模板字段，插入模板并返回详情。"""
    return _preset_store_insert(
        name,
        description,
        config_json,
        is_system,
        is_default,
        preset_id,
        owner_id,
        visibility,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        normalize_id=_normalize_template_id,
        normalize_name=_normalize_template_name,
        validate_config=_validate_template_config,
        json_dumps=_json_dumps,
        now_func=_now_local,
        get_one=_get_preset,
    )

def _update_preset(preset_id: str, name: str, description: str, config_json: dict,
                   owner_id: str = "", public_only: bool = True) -> dict:
    """兼容旧入口：传入模板 ID 和更新字段，更新模板并返回详情。"""
    return _preset_store_update(
        preset_id,
        name,
        description,
        config_json,
        owner_id,
        public_only,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        normalize_id=_normalize_template_id,
        normalize_name=_normalize_template_name,
        validate_config=_validate_template_config,
        json_dumps=_json_dumps,
        now_func=_now_local,
        get_one=_get_preset,
    )

def _delete_preset(preset_id: str, owner_id: str = "", public_only: bool = True) -> dict:
    """兼容旧入口：传入模板 ID 和 owner 限制，删除模板并返回删除结果。"""
    return _preset_store_delete(
        preset_id,
        owner_id,
        public_only,
        connect=_sql,
        sql_lock=_SQL_LOCK,
        normalize_id=_normalize_template_id,
    )

def _health_payload() -> dict:
    """兼容旧私有入口，无需传入数据，返回健康检查 payload。"""
    return _build_health_payload()

def _dir_writable(path: str) -> bool:
    """兼容旧私有入口，传入目录路径，返回是否可写。"""
    return _health_dir_writable(path)

def _database_ready() -> bool:
    """无需传入数据，返回当前 SQLite 连接是否可执行基础查询。"""
    try:
        with _SQL_LOCK:
            conn = _sql()
            conn.execute("SELECT 1").fetchone()
            conn.close()
        return True
    except Exception:
        return False

def _ready_payload() -> dict:
    """兼容旧私有入口，无需传入数据，返回服务 readiness payload。"""
    return _build_ready_payload(
        database_check=_database_ready,
        output_dir=OUTPUT_DIR,
        log_dir=LOG_DIR,
    )

def _version_payload() -> dict:
    """兼容旧私有入口，无需传入数据，返回公开运行版本信息。"""
    return _build_version_payload(
        app_version=APP_VERSION,
        build_version=BUILD_VERSION,
        git_revision=GIT_REVISION,
        started_at=STARTED_AT,
        bind_host=BIND_HOST,
        file_retention_policy=FILE_RETENTION_POLICY,
        file_ttl=FILE_TTL,
        max_tasks=MAX_TASKS,
        task_retention_hours=TASK_RETENTION_HOURS,
        max_cached_tasks=MAX_CACHED_TASKS,
        cleanup_interval_minutes=CLEANUP_INTERVAL_MINUTES,
        max_size=MAX_SIZE,
        upload_read_timeout_seconds=UPLOAD_READ_TIMEOUT_SECONDS,
        process_timeout=PROCESS_TIMEOUT,
        max_docx_uncompressed_bytes=MAX_DOCX_UNCOMPRESSED_BYTES,
        max_docx_file_count=MAX_DOCX_FILE_COUNT,
        max_docx_xml_bytes=MAX_DOCX_XML_BYTES,
        max_docx_media_bytes=MAX_DOCX_MEDIA_BYTES,
        max_docx_compression_ratio=MAX_DOCX_COMPRESSION_RATIO,
        max_workers=MAX_WORKERS,
        max_queue=MAX_QUEUE,
        proxy_secret=PROXY_SECRET,
        frontend_origin=FRONTEND_ORIGIN,
        queued_count=_queued_count,
        active_count=_active_count,
    )

def _server_bind_address() -> tuple:
    """兼容旧私有入口，无需传入数据，返回服务绑定地址。"""
    return _build_server_bind_address(BIND_HOST, PORT)

def _startup_urls() -> dict:
    """兼容旧私有入口，无需传入数据，返回启动日志 URL 集合。"""
    return _build_startup_urls(BIND_HOST, PORT)

def _monitor_url(admin_token: str, query: dict, **overrides) -> str:
    """兼容旧私有入口，传入当前查询和覆盖项，返回监控页链接。"""
    return _build_monitor_url(query, **overrides)

def _pager_html(stats: dict, admin_token: str, page_key: str, pages_key: str) -> str:
    """兼容旧私有入口，传入统计分页字段，返回监控分页 HTML。"""
    return _pages_render_pager_html(stats, admin_token, page_key, pages_key)

def _status_badge(status: str):
    """兼容旧私有入口，传入任务状态，返回中文标签和 CSS 类名。"""
    return _pages_status_badge(status)

def _monitor_html(stats: dict, admin_token: str = "") -> str:
    limit = _limit_settings()
    limit_checked = " checked" if limit["enabled"] else ""
    limit_state = "已开启" if limit["enabled"] else "已关闭"
    csrf_input = _csrf_hidden_input(admin_token)
    query = stats.get("query", _normalize_monitor_query())
    recent_pager = _pager_html(stats, admin_token, "recent_page", "recent_pages")
    ip_pager = _pager_html(stats, admin_token, "ip_page", "ip_pages")
    ready = _ready_payload()
    version = _version_payload()
    ready_state = "在线" if ready.get("ok") else "需检查"
    ready_class = "online" if ready.get("ok") else "offline"
    trend = stats.get("trend", [])
    rows = _pages_render_recent_task_rows(stats, admin_token, _admin_url)
    ips = _pages_render_top_ip_rows(stats, admin_token, csrf_input, _admin_url)
    banned_rows = _pages_render_banned_ip_rows(stats, csrf_input)
    trend_bars = _pages_render_trend_bars(trend)
    check_items = _pages_render_health_check_items(ready)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>工作台 · 公文智能排版</title>
<style>
:root{{--bg:#07101f;--panel:#0d1a2e;--panel2:#111f35;--line:rgba(160,181,215,.17);--muted:#8fa2be;--text:#edf4ff;--gold:#f6c85f;--gold-soft:rgba(246,200,95,.12);--blue:#74b9ff;--green:#55d6a0;--red:#fb7185}}
*{{margin:0;padding:0;box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{font-family:"Microsoft YaHei","Noto Sans CJK SC","WenQuanYi Micro Hei","PingFang SC",Arial,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
a{{color:inherit;text-decoration:none}}button,input{{font:inherit}}
.shell{{display:grid;grid-template-columns:224px minmax(0,1fr);min-height:100vh}}
.sidebar{{position:sticky;top:0;height:100vh;padding:24px 16px;border-right:1px solid var(--line);background:linear-gradient(180deg,#0b1729,#07101f);display:flex;flex-direction:column}}
.brand{{display:flex;align-items:center;gap:11px;padding:0 8px 25px;border-bottom:1px solid var(--line)}}
.brand-mark{{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,#f6c85f,#e89c3a);color:#152238;font-weight:900;font-size:18px}}
.brand strong{{display:block;font-size:14px;letter-spacing:.02em}}.brand small{{display:block;color:var(--muted);font-size:11px;margin-top:3px}}
.nav-label{{color:#637a9c;font-size:10px;letter-spacing:.12em;margin:24px 10px 8px;text-transform:uppercase}}
.side-nav{{display:grid;gap:5px}}.side-nav a{{display:flex;align-items:center;gap:10px;padding:11px 12px;border:1px solid transparent;border-radius:10px;color:#b8c8df;font-size:13px;transition:.18s}}
.side-nav a:hover,.side-nav a.active{{background:var(--gold-soft);border-color:rgba(246,200,95,.2);color:#ffe7a4}}
.nav-index{{width:22px;color:var(--gold);font-family:Consolas,monospace;font-size:11px}}
.side-footer{{margin-top:auto;padding:13px 10px;border-top:1px solid var(--line);color:var(--muted);font-size:11px;line-height:1.7}}
.side-footer b{{color:#cfe0f8;font-weight:600}}
.main{{min-width:0;padding:22px 30px 40px}}
.topbar{{display:flex;justify-content:space-between;align-items:center;gap:18px;padding-bottom:18px;border-bottom:1px solid var(--line)}}
.eyebrow{{color:var(--gold);font-size:11px;letter-spacing:.12em;text-transform:uppercase;margin-bottom:5px}}h1{{font-size:24px;letter-spacing:.01em}}
.top-actions{{display:flex;align-items:center;gap:9px;flex-wrap:wrap;justify-content:flex-end}}
.service-pill{{display:inline-flex;align-items:center;gap:7px;padding:8px 11px;border:1px solid rgba(85,214,160,.25);background:rgba(85,214,160,.08);border-radius:999px;color:#a7f3d0;font-size:12px}}
.service-pill.offline{{border-color:rgba(251,113,133,.3);background:rgba(251,113,133,.08);color:#fecdd3}}.service-dot{{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px rgba(85,214,160,.12)}}.offline .service-dot{{background:var(--red);box-shadow:0 0 0 4px rgba(251,113,133,.12)}}
.top-link,.top-button{{padding:8px 11px;border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.04);color:#b9c9df;font-size:12px;cursor:pointer}}.top-link:hover,.top-button:hover{{border-color:rgba(246,200,95,.4);color:#ffe7a4}}
.alert{{display:flex;gap:12px;align-items:flex-start;padding:12px 14px;margin:18px 0;border:1px solid rgba(251,113,133,.3);border-radius:10px;background:rgba(251,113,133,.09);color:#fecdd3;font-size:12px;line-height:1.6}}
.section{{scroll-margin-top:20px;margin-top:24px}}.section-heading{{display:flex;justify-content:space-between;align-items:flex-end;gap:14px;margin-bottom:12px}}.section-heading h2{{font-size:16px}}.section-heading p{{color:var(--muted);font-size:12px;margin-top:4px}}.section-meta{{color:var(--muted);font-size:12px}}
.metric-grid{{display:grid;grid-template-columns:repeat(8,minmax(100px,1fr));gap:9px}}
.metric{{min-width:0;padding:15px 14px;border:1px solid var(--line);border-radius:10px;background:linear-gradient(145deg,rgba(18,35,59,.9),rgba(10,24,42,.9))}}.metric .value{{font-size:24px;color:#f6d985;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.metric .label{{color:var(--muted);font-size:11px;margin-top:6px}}.metric.good .value{{color:var(--green)}}.metric.bad .value{{color:#ff9cab}}
.work-grid{{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(270px,.8fr);gap:14px}}.panel{{min-width:0;border:1px solid var(--line);border-radius:12px;background:linear-gradient(145deg,rgba(14,30,51,.96),rgba(9,21,37,.96));overflow:hidden}}.panel-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:17px 18px;border-bottom:1px solid var(--line)}}.panel-head h3{{font-size:14px}}.panel-head p{{color:var(--muted);font-size:11px;margin-top:4px}}.panel-body{{padding:17px 18px}}
.health-list{{display:grid;gap:9px}}.health-list li{{list-style:none;display:flex;align-items:center;gap:9px;color:#b9c9df;font-size:12px}}.health-list li span{{width:7px;height:7px;border-radius:50%;background:var(--green)}}.health-list li.check-bad span{{background:var(--red)}}.health-list li b{{margin-left:auto;font-size:11px;color:var(--green);font-weight:600}}.health-list li.check-bad b{{color:#ff9cab}}
.runtime-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px}}.runtime-item{{padding:10px;border-radius:8px;background:rgba(255,255,255,.04);border:1px solid rgba(160,181,215,.1)}}.runtime-item b{{display:block;font-size:15px;color:#e6effd}}.runtime-item span{{display:block;color:var(--muted);font-size:10px;margin-top:4px}}
.trend{{display:grid;gap:8px}}.trend-row{{display:grid;grid-template-columns:86px minmax(0,1fr) 42px;gap:10px;align-items:center}}.trend-date,.trend-count{{color:var(--muted);font-size:11px}}.trend-count{{text-align:right;color:#dce8fa}}.trend-count small{{color:var(--muted);margin-left:2px}}.trend-track{{height:12px;display:flex;gap:2px;background:rgba(255,255,255,.06);border-radius:99px;overflow:hidden}}.trend-track i{{display:block;height:100%;min-width:0}}.trend-done{{background:var(--green)}}.trend-error{{background:var(--red)}}
.legend{{display:flex;gap:14px;margin-top:15px;color:var(--muted);font-size:11px}}.legend i{{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px}}.legend .done{{background:var(--green)}}.legend .error{{background:var(--red)}}
.table-wrap{{overflow-x:auto}}table{{width:100%;min-width:840px;border-collapse:collapse}}th{{padding:10px 11px;text-align:left;color:#7890b2;font-size:10px;font-weight:600;letter-spacing:.04em;white-space:nowrap;background:rgba(4,13,25,.4)}}td{{padding:10px 11px;border-top:1px solid rgba(160,181,215,.09);color:#c8d6e9;font-size:12px;white-space:nowrap}}tr:hover td{{background:rgba(246,200,95,.045)}}.fn{{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.mono{{font-family:Consolas,"Noto Sans Mono CJK SC","WenQuanYi Micro Hei",monospace;font-size:11px}}.ok{{color:var(--green)}}.badtxt{{color:#ff9cab}}.status-tag{{display:inline-flex;padding:4px 7px;border-radius:5px;font-size:10px;font-weight:700}}.status-tag.done{{background:rgba(85,214,160,.12);color:#a7f3d0}}.status-tag.error{{background:rgba(251,113,133,.12);color:#fecdd3}}.status-tag.queued{{background:rgba(246,200,95,.12);color:#ffe7a4}}.status-tag.processing{{background:rgba(116,185,255,.12);color:#bfdbfe}}.table-action{{color:#9bc8ff;font-size:11px}}.table-action:hover{{color:#ffe7a4}}.actions{{display:flex;align-items:center;gap:10px}}.actions form{{margin:0}}.link-danger{{border:0;background:transparent;color:#ff9cab;padding:0;cursor:pointer;font-size:11px}}.link-danger:hover{{color:#fff}}
.control-grid{{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,.8fr);gap:14px}}.control-form{{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap}}.control-form label{{display:grid;gap:6px;color:#9eb1cb;font-size:11px}}.control-form input[type=number]{{width:100px;height:36px;border:1px solid var(--line);border-radius:7px;background:#081529;color:#edf4ff;padding:0 9px}}.control-form input[type=checkbox]{{accent-color:var(--gold)}}.primary-btn{{height:36px;padding:0 13px;border:1px solid rgba(246,200,95,.35);border-radius:7px;background:var(--gold-soft);color:#ffe7a4;cursor:pointer;font-size:12px}}.primary-btn:hover{{background:rgba(246,200,95,.2)}}.danger-btn{{height:36px;padding:0 13px;border:1px solid rgba(251,113,133,.3);border-radius:7px;background:rgba(251,113,133,.08);color:#fecdd3;cursor:pointer;font-size:12px}}
.empty-state{{padding:24px 10px;text-align:center;color:var(--muted);font-size:12px}}.pager{{display:flex;gap:12px;align-items:center;justify-content:flex-end;padding:12px 18px 16px;color:var(--muted);font-size:11px}}.pager a{{color:#9bc8ff}}.pager a.disabled{{pointer-events:none;color:#536985}}.hint{{color:var(--muted);font-size:11px;line-height:1.6}}
@media(max-width:1180px){{.metric-grid{{grid-template-columns:repeat(4,minmax(120px,1fr))}}}}
@media(max-width:900px){{.shell{{display:block}}.sidebar{{position:static;height:auto;padding:14px 18px;display:block;border-right:0;border-bottom:1px solid var(--line)}}.brand{{padding-bottom:12px;border-bottom:0}}.nav-label,.side-footer{{display:none}}.side-nav{{display:flex;overflow-x:auto;padding-top:8px;scrollbar-width:none}}.side-nav::-webkit-scrollbar{{display:none}}.side-nav a{{white-space:nowrap;padding:8px 10px}}.main{{padding:18px}}.work-grid,.control-grid{{grid-template-columns:1fr}}}}
@media(max-width:560px){{.main{{padding:14px}}.topbar{{align-items:flex-start;flex-direction:column}}.top-actions{{justify-content:flex-start}}h1{{font-size:21px}}.metric-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.metric .value{{font-size:21px}}.panel-head,.panel-body{{padding:14px}}.section{{margin-top:18px}}}}
</style></head>
<body>
<div class="shell">
<aside class="sidebar"><a class="brand" href="/"><span class="brand-mark">文</span><span><strong>公文智能排版</strong><small>管理员工作台</small></span></a>
<div class="nav-label">WORKSPACE</div><nav class="side-nav">
<a class="active" href="#overview"><span class="nav-index">01</span>总览</a><a href="#tasks"><span class="nav-index">02</span>任务中心</a><a href="#security"><span class="nav-index">03</span>安全与访问</a><a href="#runtime"><span class="nav-index">04</span>运行设置</a><a href="#logs"><span class="nav-index">05</span>日志查询</a>
</nav><div class="side-footer">当前服务<br><b>Python · 9527</b><br>数据目录受项目路径管理</div></aside>
<main class="main">
<header class="topbar"><div><div class="eyebrow">ADMIN WORKSPACE / {html.escape(str(version.get('version', '')))}</div><h1>运行总览</h1></div><div class="top-actions"><span class="service-pill {ready_class}"><i class="service-dot"></i>服务{ready_state}</span><button class="top-button" type="button" onclick="window.location.reload()">刷新</button><a class="top-link" href="/">返回工具</a><a class="top-link" href="/stats" target="_blank">JSON</a><form method="post" action="/admin/logout">{csrf_input}<button class="top-button" type="submit">退出</button></form></div></header>
{('<div class="alert"><strong>运行检查</strong><span>数据库、输出目录或日志目录存在异常，请先检查运行环境，再处理任务。</span></div>') if not ready.get('ok') else ''}
<section id="overview" class="section"><div class="section-heading"><div><h2>关键指标</h2><p>排版服务当前累计运行数据</p></div><span class="section-meta">自动刷新 · 15 秒</span></div><div class="metric-grid">
<div class="metric"><div class="value">{stats.get('total',0)}</div><div class="label">总任务</div></div><div class="metric good"><div class="value">{stats.get('done',0)}</div><div class="label">成功任务</div></div><div class="metric bad"><div class="value">{stats.get('error',0)}</div><div class="label">失败任务</div></div><div class="metric good"><div class="value">{stats.get('rate',0)}%</div><div class="label">成功率</div></div><div class="metric"><div class="value">{version.get('queued',0)}</div><div class="label">当前排队</div></div><div class="metric"><div class="value">{version.get('processing',0)}</div><div class="label">当前处理</div></div><div class="metric"><div class="value">{stats.get('avg_s',0)}s</div><div class="label">平均耗时</div></div><div class="metric"><div class="value">{stats.get('unique_ips',0)}</div><div class="label">独立 IP</div></div>
</div></section>
<section class="section"><div class="work-grid"><div class="panel"><div class="panel-head"><div><h3>任务趋势</h3><p>按日期统计成功与失败任务</p></div><span class="section-meta">最近 {len(trend[-14:])} 个记录日</span></div><div class="panel-body"><div class="trend">{trend_bars}</div><div class="legend"><span><i class="done"></i>成功</span><span><i class="error"></i>失败</span></div></div></div><div class="panel"><div class="panel-head"><div><h3>运行状态</h3><p>服务依赖和处理队列</p></div><span class="service-pill {ready_class}">{ready_state}</span></div><div class="panel-body"><ul class="health-list">{check_items}</ul><div class="runtime-grid"><div class="runtime-item"><b>{version.get('max_workers',0)}</b><span>工作线程</span></div><div class="runtime-item"><b>{version.get('max_queue',0)}</b><span>队列上限</span></div><div class="runtime-item"><b>{version.get('max_upload_mb',0)} MB</b><span>单文件上限</span></div><div class="runtime-item"><b>{version.get('process_timeout_seconds',0)}s</b><span>处理超时</span></div></div></div></div></div></section>
<section id="tasks" class="section"><div class="section-heading"><div><h2>任务中心</h2><p>优先处理失败任务，点击日志查看完整排版过程</p></div><span class="section-meta">{len(stats.get('recent',[]))} / {stats.get('recent_total',0)} 条</span></div><div class="panel"><div class="table-wrap"><table><thead><tr><th>时间</th><th>文件名</th><th>来源 IP</th><th>大小</th><th>类型</th><th>段数</th><th>耗时</th><th>状态</th><th>操作</th></tr></thead><tbody>{"".join(rows) or '<tr><td colspan="9"><div class="empty-state">暂无任务，用户上传 DOCX 后将在此显示。</div></td></tr>'}</tbody></table></div>{recent_pager}</div></section>
<section id="security" class="section"><div class="section-heading"><div><h2>安全与访问</h2><p>查看访问活跃度并处理异常来源</p></div><span class="section-meta">{stats.get('ip_total',0)} 个活跃 IP · {len(stats.get('banned_ips',[]))} 个封禁</span></div><div class="work-grid"><div class="panel"><div class="panel-head"><div><h3>活跃 IP</h3><p>按最近访问时间排序</p></div></div><div class="table-wrap"><table><thead><tr><th>IP</th><th>上传</th><th>成功</th><th>失败</th><th>最近活跃</th><th>最近文件</th><th>操作</th></tr></thead><tbody>{ips or '<tr><td colspan="7"><div class="empty-state">暂无访问记录。</div></td></tr>'}</tbody></table></div>{ip_pager}</div><div class="panel"><div class="panel-head"><div><h3>封禁 IP</h3><p>危险操作需要管理员确认</p></div></div><div class="table-wrap"><table><thead><tr><th>IP</th><th>原因</th><th>时间</th><th>操作</th></tr></thead><tbody>{banned_rows or '<tr><td colspan="4"><div class="empty-state">暂无封禁 IP。</div></td></tr>'}</tbody></table></div></div></div></section>
<section id="runtime" class="section"><div class="section-heading"><div><h2>运行设置</h2><p>调整访问限额、列表密度和永久保存策略</p></div><span class="section-meta">限额{limit_state}</span></div><div class="control-grid"><div class="panel"><div class="panel-head"><div><h3>上传限额</h3><p>同一 IP 在指定时间窗口内的排版次数限制</p></div></div><div class="panel-body"><form class="control-form" method="post" action="/limit">{csrf_input}<label><span>状态</span><span><input type="checkbox" name="enabled" value="1"{limit_checked}> 启用</span></label><label><span>时间窗口（秒）</span><input type="number" min="1" name="window_seconds" value="{limit['window_seconds']}"></label><label><span>允许次数</span><input type="number" min="1" name="count" value="{limit['count']}"></label><button class="primary-btn" type="submit">保存设置</button></form></div></div><div class="panel"><div class="panel-head"><div><h3>文件保存</h3><p>已接收原件、排版结果、任务日志和任务记录永久保留</p></div></div><div class="panel-body"><p class="hint">系统不按时间自动删除用户文件。请结合服务器磁盘空间自行制定归档与备份策略。</p></div></div></div><div class="panel" style="margin-top:14px"><div class="panel-head"><div><h3>显示设置</h3><p>控制任务中心和活跃 IP 每页显示数量</p></div></div><div class="panel-body"><form class="control-form" method="get" action="/monitor"><label><span>最近任务/页</span><input type="number" min="1" max="{MAX_MONITOR_PAGE_SIZE}" name="recent_size" value="{query['recent_size']}"></label><label><span>活跃 IP/页</span><input type="number" min="1" max="{MAX_MONITOR_PAGE_SIZE}" name="ip_size" value="{query['ip_size']}"></label><button class="primary-btn" type="submit">应用</button><a class="top-link" href="/monitor">恢复默认</a><span class="hint">默认每页 50 条，最多 {MAX_MONITOR_PAGE_SIZE} 条。</span></form></div></div></section>
<section id="logs" class="section"><div class="panel"><div class="panel-head"><div><h3>日志查询</h3><p>从任务中心的“查看日志”进入具体任务日志</p></div><a class="top-link" href="/stats" target="_blank">打开 JSON API</a></div><div class="panel-body"><p class="hint">日志仅保存在服务端运行目录，页面不会显示 Cookie、管理员密钥或代理密钥。失败任务优先从任务中心进入排查。</p></div></div></section>
<footer class="side-footer" style="margin-top:24px">最后生成：{_html_escape(_now_local()[:19])} · 页面每 15 秒自动刷新</footer>
</main></div>
<script>
setInterval(() => {{
  if (document.hidden) return;
  const active = document.activeElement;
  if (active && ['INPUT', 'SELECT', 'TEXTAREA'].includes(active.tagName)) return;
  window.location.reload();
}}, 15000);
</script>
</body></html>"""


def _ip_detail_html(ip: str, admin_token: str = "") -> str:
    """兼容旧私有入口，传入 IP 和 CSRF token，返回 IP 明细 HTML。"""
    return _pages_render_ip_detail_html(
        ip,
        admin_token,
        csrf_hidden_input=_csrf_hidden_input,
        ip_activity=_ip_activity,
        ip_upload_count=_ip_upload_count,
        is_ip_banned=_is_ip_banned,
        admin_url=_admin_url,
    )


# ── 安全工具 ──

def _is_safe_uuid(s: str) -> bool:
    """兼容旧私有入口，传入字符串，返回是否为安全 UUID 形态。"""
    return _file_is_safe_uuid(s)

def _sanitize_filename(name: str) -> str:
    """兼容旧私有入口，传入原始文件名，返回安全文件名。"""
    return _file_sanitize_filename(name)

def _safe_download_filename(orig_name: str) -> str:
    """兼容旧私有入口，传入原始文件名，返回排版结果下载名。"""
    return _file_safe_download_filename(orig_name)

def _content_disposition_filename(filename: str) -> str:
    """兼容旧私有入口，传入下载名，返回 Content-Disposition 头值。"""
    return _file_content_disposition_filename(filename)

def _trusted_proxy_source(client_address) -> bool:
    """兼容旧入口：判断 socket 来源是否允许提供代理 IP 头。"""
    return _client_trusted_proxy_source(
        client_address,
        trust_proxy_headers=TRUST_PROXY_HEADERS,
        trusted_proxy_ips=TRUSTED_PROXY_IPS,
    )

def _compare_secret(value: str, secret: str) -> bool:
    """兼容旧入口：常量时间比较请求密钥和配置密钥。"""
    return _client_compare_secret(value, secret)

def _html_escape(text: str) -> str:
    """兼容旧入口：转义任意文本用于 HTML 输出。"""
    return _request_html_escape(text)

def _redact_sensitive_log(text: str) -> str:
    value = str(text or "")
    for name in ("ADMIN_TOKEN", "PROXY_SECRET", "Authorization", "Proxy-Authorization", "Cookie", "Set-Cookie"):
        value = _re.sub(
            rf"(?im)^({name}\s*[:=]\s*).+$",
            r"\1[REDACTED]",
            value,
        )
    return value

def _split_ip_header(value: str):
    """兼容旧入口：拆分代理 IP 请求头为候选列表。"""
    return _client_split_ip_header(value)

def _is_ipv4(value: str) -> bool:
    """兼容旧入口：传入字符串，返回是否为合法 IPv4。"""
    return _client_is_ipv4(value)

def _client_ip(headers, client_address) -> str:
    """兼容旧入口：从可信代理头和 socket 地址解析真实客户端 IP。"""
    return _client_ip_from_headers(
        headers,
        client_address,
        trust_proxy_headers=TRUST_PROXY_HEADERS,
        trusted_proxy_ips=TRUSTED_PROXY_IPS,
    )


class Handler(BaseHTTPRequestHandler):

    def _set_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")

    def _set_cors_headers(self):
        for key, value in cors_headers_for_request(self.headers.get("Origin", "")).items():
            self.send_header(key, value)

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self._set_security_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = _route_path(parsed.path)
        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/admin/login":
            self._serve_admin_login()
        elif path == "/admin/session":
            self._handle_admin_session()
        elif path == "/health":
            self._json(_health_payload())
        elif path == "/ready":
            ready = _ready_payload()
            self._json(ready, 200 if ready.get("ok") else 503)
        elif path == "/version":
            self._json(_version_payload())
        elif path == "/auth/me":
            self._handle_auth_me()
        elif path == "/stats":
            if not self._require_admin(parsed):
                return
            self._json(get_sql_stats(_monitor_query_from(parsed)))
        elif path == "/monitor":
            if not self._require_admin(parsed):
                return
            ctx = self._admin_context_or_default()
            if ctx.get("legacy_token") and not ctx.get("session"):
                session = _create_admin_session(self.headers.get("User-Agent", ""), self.client_address[0] if self.client_address else "")
                self._redirect("/monitor", extra_headers=[("Set-Cookie", _admin_cookie_header(session["session_id"]))])
                return
            query = _monitor_query_from(parsed)
            self._text(_monitor_html(get_sql_stats(query), self._admin_csrf_token(parsed)), "text/html")
        elif path == "/ip":
            if not self._require_admin(parsed):
                return
            self._handle_ip_detail(parsed)
        elif path == "/ban":
            self.send_error(405)
        elif path == "/unban":
            self.send_error(405)
        elif path == "/limit":
            self.send_error(405)
        elif path == "/cleanup":
            self.send_error(405)
        elif path == "/presets":
            self._handle_presets_list()
        elif path.startswith("/presets/"):
            self._handle_preset_detail(path.split("/", 2)[-1])
        elif path.startswith("/status/") or path.startswith("/api/status/"):
            if not self._require_file_api():
                return
            self._handle_status(path.split("/")[-1])
        elif path.startswith("/download/") or path.startswith("/api/download/"):
            if not self._require_file_api():
                return
            self._handle_download(path.split("/")[-1])
        elif path.startswith("/log/"):
            if not self._require_admin(parsed):
                return
            self._handle_log(path.split("/")[-1])
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = _route_path(parsed.path)
        if path == "/upload":
            if not self._require_file_api():
                return
            self._handle_upload_raw()
        elif path == "/auth/register":
            self._handle_auth_register()
        elif path == "/auth/login":
            self._handle_auth_login()
        elif path == "/auth/logout":
            self._handle_auth_logout()
        elif path == "/admin/login":
            self._handle_admin_login()
        elif path == "/admin/logout":
            self._handle_admin_logout()
        elif path == "/ban":
            if not self._require_admin_post(parsed):
                return
            self._handle_ban(parsed)
        elif path == "/unban":
            if not self._require_admin_post(parsed):
                return
            self._handle_unban(parsed)
        elif path == "/limit":
            if not self._require_admin_post(parsed):
                return
            self._handle_limit(parsed)
        elif path == "/cleanup":
            if not self._require_admin_post(parsed):
                return
            self._handle_cleanup(parsed)
        elif path == "/presets":
            if not self._require_preset_mutation(parsed):
                return
            self._handle_preset_create()
        elif path.startswith("/presets/"):
            if not self._require_preset_mutation(parsed):
                return
            self._handle_preset_update(path.split("/", 2)[-1])
        else:
            self.send_error(404)

    def do_PUT(self):
        path = _route_path(urlparse(self.path).path)
        if path == "/upload":
            if not self._require_file_api():
                return
            self._handle_upload_raw()
        elif path.startswith("/presets/"):
            if not self._require_preset_mutation(urlparse(self.path)):
                return
            self._handle_preset_update(path.split("/", 2)[-1])
        else:
            self.send_error(404)

    def do_DELETE(self):
        path = _route_path(urlparse(self.path).path)
        if path.startswith("/presets/"):
            parsed = urlparse(self.path)
            if not self._require_preset_mutation(parsed):
                return
            self._handle_preset_delete(path.split("/", 2)[-1])
        else:
            self.send_error(404)

    def _serve_html(self):
        candidates = [
            str(resource_path("frontend", "pages", "index.html")),
        ]
        p = next((path for path in candidates if os.path.exists(path)), candidates[-1])
        try:
            with open(p, "r", encoding="utf-8") as f:
                self._text(f.read(), "text/html")
        except FileNotFoundError:
            self.send_error(404)

    def _serve_admin_login(self):
        body = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>管理员登录 · 公文智能排版</title>
<style>
:root{--bg:#07101f;--panel:#0d1a2e;--line:rgba(160,181,215,.18);--text:#edf4ff;--muted:#8fa2be;--gold:#f6c85f}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;font-family:"Microsoft YaHei","Noto Sans CJK SC","PingFang SC",sans-serif;background:radial-gradient(circle at 25% 20%,rgba(66,100,150,.16),transparent 32%),var(--bg);color:var(--text)}
.workspace{width:min(920px,100%);display:grid;grid-template-columns:minmax(0,1.05fr) minmax(340px,.75fr);border:1px solid var(--line);border-radius:14px;overflow:hidden;background:rgba(7,16,31,.86);box-shadow:0 28px 80px rgba(0,0,0,.35)}
.intro{padding:52px 48px;background:linear-gradient(145deg,rgba(18,36,61,.94),rgba(9,23,40,.94));border-right:1px solid var(--line)}.mark{width:46px;height:46px;display:grid;place-items:center;border-radius:11px;background:linear-gradient(135deg,#f6c85f,#e89c3a);color:#152238;font-size:22px;font-weight:900;margin-bottom:28px}.eyebrow{color:var(--gold);font-size:11px;letter-spacing:.13em;margin-bottom:10px}h1{font-size:29px;margin:0 0 13px}.intro p{max-width:38ch;color:#a9bad1;line-height:1.8;font-size:14px;margin:0}.status{display:grid;gap:10px;margin-top:34px}.status span{display:flex;align-items:center;gap:9px;color:#8fa2be;font-size:12px}.status i{width:7px;height:7px;border-radius:50%;background:#55d6a0}
.login{padding:48px 40px;background:rgba(9,21,37,.92);display:flex;flex-direction:column;justify-content:center}.login h2{font-size:18px;margin:0 0 6px}.login>p{color:var(--muted);font-size:12px;line-height:1.7;margin:0 0 24px}label{display:block;color:#b9c9df;font-size:12px;font-weight:700;margin-bottom:8px}input{width:100%;height:44px;border:1px solid var(--line);border-radius:8px;background:#071426;color:#fff;padding:0 12px;font-size:14px;outline:none}input:focus{border-color:rgba(246,200,95,.5);box-shadow:0 0 0 4px rgba(246,200,95,.08)}button{width:100%;height:44px;margin-top:15px;border:1px solid rgba(246,200,95,.42);border-radius:8px;background:rgba(246,200,95,.14);color:#ffe7a4;font-weight:800;cursor:pointer}button:hover{background:rgba(246,200,95,.22)}.hint{font-size:11px;color:#6f85a4;margin-top:14px;line-height:1.65}.back{display:inline-block;color:#9bc8ff;font-size:11px;margin-top:18px;text-decoration:none}
@media(max-width:760px){.workspace{grid-template-columns:1fr}.intro{padding:30px;border-right:0;border-bottom:1px solid var(--line)}.intro p,.status{display:none}.mark{margin-bottom:18px}.login{padding:30px}}
</style></head>
<body><main class="workspace"><section class="intro"><div class="mark">文</div><div class="eyebrow">DOCXTOOL ADMIN</div><h1>公文排版工作台</h1><p>集中查看任务状态、运行指标、访问安全和服务配置。管理员会话通过安全 Cookie 建立。</p><div class="status"><span><i></i>后端服务已连接</span><span><i></i>管理员会话受保护</span></div></section><section class="login"><h2>管理员登录</h2><p>输入服务器配置的管理员密钥，登录后进入运行工作台。</p><form method="post" action="/admin/login"><label for="admin_token">管理员密钥</label><input id="admin_token" name="admin_token" type="password" autocomplete="current-password" required autofocus><button type="submit">进入工作台</button></form><div class="hint">密钥仅用于建立当前管理员会话，不会写入页面地址。</div><a class="back" href="/">返回公文排版工具</a></section></main></body></html>"""
        self._text(body, "text/html")

    def _admin_context_or_default(self):
        return getattr(self, "_admin_context", {"authorized": False, "session": {}, "legacy_token": False})

    def _admin_csrf_token(self, parsed=None) -> str:
        ctx = self._admin_context_or_default()
        session = ctx.get("session") or {}
        if session.get("csrf_token"):
            return session["csrf_token"]
        if ctx.get("legacy_token"):
            return ""
        return ""

    def _handle_admin_session(self):
        session = _admin_session_from_headers(self.headers, self.headers.get("Cookie", ""))
        if not session:
            self._json_error("UNAUTHORIZED", "需要管理员权限", 403)
            return
        self._json({
            "ok": True,
            "csrf_token": session.get("csrf_token", ""),
            "expires_at": session.get("expires_at", 0),
        })

    def _handle_admin_login(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = _read_exact(self.rfile, length) if length > 0 else b""
        params = {}
        if body:
            try:
                params = {k: (v[-1] if isinstance(v, list) and v else v) for k, v in parse_qs(body.decode("utf-8")).items()}
            except Exception:
                params = {}
        token = str(params.get("admin_token") or params.get("token") or "").strip()
        if not token:
            self._json_error("INVALID_LOGIN", "请输入管理员密钥", 400)
            return
        if not hmac.compare_digest(token, ADMIN_TOKEN):
            self._json_error("INVALID_LOGIN", "管理员密钥错误", 403)
            return
        session = _create_admin_session(self.headers.get("User-Agent", ""), self.client_address[0] if self.client_address else "")
        cookie = _admin_cookie_header(session["session_id"])
        self._redirect("/monitor", extra_headers=[("Set-Cookie", cookie)])

    def _handle_admin_logout(self):
        session = _admin_session_from_headers(self.headers, self.headers.get("Cookie", ""))
        if session:
            _delete_admin_session(session.get("session_id", ""))
        cookie = f"{ADMIN_SESSION_COOKIE}=; HttpOnly; Path=/; SameSite=Strict; Max-Age=0"
        if COOKIE_SECURE:
            cookie += "; Secure"
        self._redirect("/admin/login", extra_headers=[("Set-Cookie", cookie)])

    def _require_admin(self, parsed) -> bool:
        ctx = _admin_request_context(parsed, self.headers, self.headers.get("Cookie", ""))
        self._admin_context = ctx
        if ctx.get("authorized"):
            return True
        self._json_error("UNAUTHORIZED", "需要管理员权限", 403)
        return False

    def _require_admin_post(self, parsed) -> bool:
        ctx = _admin_request_context(parsed, self.headers, self.headers.get("Cookie", ""))
        self._admin_context = ctx
        if not ctx.get("authorized"):
            self._json_error("UNAUTHORIZED", "需要管理员权限", 403)
            return False
        params = self._request_params(parsed)
        self._request_params_cache = params
        csrf_value = str(params.get("csrf_token") or _csrf_header_value(self.headers) or "").strip()
        session = ctx.get("session") or {}
        if not session or not csrf_value or not hmac.compare_digest(csrf_value, session.get("csrf_token", "")):
            self._json_error("CSRF_INVALID", "CSRF 校验失败", 403)
            return False
        return True

    def _require_preset_mutation(self, parsed) -> bool:
        """Authorize either an admin public-template mutation or a private one."""
        admin_context = _admin_request_context(parsed, self.headers, self.headers.get("Cookie", ""))
        if admin_context.get("authorized"):
            if not self._require_admin_post(parsed):
                return False
            self._preset_owner_id = ""
            self._preset_public_only = True
            self._preset_admin = True
            return True
        if not _anonymous_template_origin_allowed(self.headers):
            self._json_error("CSRF_INVALID", "模板请求来源校验失败", 403)
            return False
        self._request_params_cache = self._request_params(parsed)
        principal = _principal(self.headers, self.client_address)
        if principal.get("authenticated") and not _auth_csrf_allowed(self.headers, principal):
            self._json_error("CSRF_INVALID", "CSRF 校验失败", 403)
            return False
        self._preset_owner_id = principal["owner_id"]
        self._preset_cookie_header = principal.get("cookie", "")
        self._preset_public_only = False
        self._preset_admin = False
        return True

    def _require_file_api(self) -> bool:
        if _file_api_authorized(self.headers, self.client_address):
            return True
        self._json_error("PROXY_REQUIRED", "缺少或无效的代理密钥", 403)
        return False

    def _auth_json_request(self) -> dict | None:
        if not _auth_origin_allowed(self.headers):
            self._json_error("ORIGIN_INVALID", "请求来源不被允许", 403)
            return None
        content_type = (self.headers.get("Content-Type", "") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._json_error("CONTENT_TYPE_INVALID", "请求必须使用 application/json", 415)
            return None
        payload = self._request_params(urlparse(self.path))
        return payload if isinstance(payload, dict) else None

    def _handle_auth_me(self):
        principal = _principal(self.headers, self.client_address)
        data = {"authenticated": bool(principal.get("authenticated")), "user": None, "csrf_token": None}
        if principal.get("authenticated"):
            data["user"] = {"id": principal["user_id"], "username": principal["username"], "display_name": principal.get("display_name", "")}
            data["csrf_token"] = principal.get("csrf_token")
        extra = []
        if principal.get("cookie"):
            extra.append(("Set-Cookie", principal["cookie"]))
        if principal.get("invalid_user_session"):
            extra.append(("Set-Cookie", _user_cookie_header("", clear=True)))
        self._json({"ok": True, "data": data}, extra_headers=extra)

    def _handle_auth_register(self):
        payload = self._auth_json_request()
        if payload is None:
            return
        allowed, retry = _auth_rate_allow("register-ip", _client_ip(self.headers, self.client_address), 3600, 5)
        if not allowed:
            self._json_error("RATE_LIMITED", "注册请求过于频繁，请稍后再试", 429, retry_after=retry)
            return
        try:
            display, username_norm = validate_username(payload.get("username", ""))
            password = validate_password(payload.get("password", ""))
        except ValueError as exc:
            code, msg = str(exc).split(":", 1)
            self._json_error(code, msg, 400)
            return
        anonymous = _principal(self.headers, self.client_address)
        user_id = f"usr_{uuid.uuid4().hex}"
        now = _now_unix()
        conn = None
        try:
            with _SQL_LOCK:
                conn = _sql()
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("INSERT INTO users(id,username,username_norm,password_hash,display_name,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (user_id, display, username_norm, hash_password(password), display, now, now))
                _migrate_anonymous_owner(conn, anonymous.get("owner_id", ""), user_id)
                conn.commit()
                conn.close()
        except Exception as exc:
            if conn is not None:
                conn.rollback()
                conn.close()
            if "UNIQUE constraint" in str(exc):
                self._json_error("USERNAME_TAKEN", "用户名已存在", 409)
            else:
                self._json_error("REGISTER_FAILED", "注册失败", 500)
            return
        session = _create_user_session(user_id, self.headers.get("User-Agent", ""), self.client_address[0] if self.client_address else "")
        self._json({"ok": True, "data": {"user": {"id": user_id, "username": display, "display_name": display}, "csrf_token": session["csrf_token"]}}, 201, [
            ("Set-Cookie", _user_cookie_header(session["token"])),
            ("Set-Cookie", _anonymous_user_cookie_clear_header()),
        ])

    def _handle_auth_login(self):
        payload = self._auth_json_request()
        if payload is None:
            return
        try:
            _, username_norm = validate_username(payload.get("username", ""))
        except ValueError:
            self._json_error("INVALID_CREDENTIALS", "用户名或密码错误", 401)
            return
        ip = _client_ip(self.headers, self.client_address)
        ip_allowed, ip_retry = _auth_rate_allow("login-ip", ip, 600, 30)
        name_allowed, name_retry = _auth_rate_allow("login-name", username_norm, 600, 10)
        if not ip_allowed or not name_allowed:
            self._json_error("RATE_LIMITED", "登录请求过于频繁，请稍后再试", 429, retry_after=max(ip_retry, name_retry))
            return
        password = str(payload.get("password", ""))
        with _SQL_LOCK:
            conn = _sql()
            row = conn.execute("SELECT * FROM users WHERE username_norm=?", (username_norm,)).fetchone()
            conn.close()
        if not row or not verify_password(row["password_hash"], password)[0]:
            self._json_error("INVALID_CREDENTIALS", "用户名或密码错误", 401)
            return
        if row["status"] != "active":
            self._json_error("ACCOUNT_DISABLED", "账号已停用", 403)
            return
        _, needs_rehash = verify_password(row["password_hash"], password)
        with _SQL_LOCK:
            conn = _sql()
            now = _now_unix()
            if needs_rehash:
                conn.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?", (hash_password(password), now, row["id"]))
            conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now, row["id"]))
            conn.commit()
            conn.close()
        principal = _principal(self.headers, self.client_address)
        _migrate_anonymous_resources(principal.get("owner_id", ""), row["id"])
        session = _create_user_session(row["id"], self.headers.get("User-Agent", ""), self.client_address[0] if self.client_address else "")
        remember_me = _parse_bool(str(payload.get("remember_me", "true")), True)
        self._json({"ok": True, "data": {"user": {"id": row["id"], "username": row["username"], "display_name": row["display_name"]}, "csrf_token": session["csrf_token"]}}, extra_headers=[
            ("Set-Cookie", _user_cookie_header(session["token"], persistent=remember_me)),
            ("Set-Cookie", _anonymous_user_cookie_clear_header()),
        ])

    def _handle_auth_logout(self):
        if not _auth_origin_allowed(self.headers):
            self._json_error("ORIGIN_INVALID", "请求来源不被允许", 403)
            return
        principal = _principal(self.headers, self.client_address)
        if principal.get("authenticated") and not _auth_csrf_allowed(self.headers, principal):
            self._json_error("CSRF_INVALID", "CSRF 校验失败", 403)
            return
        _delete_user_session(self.headers)
        self._json({"ok": True, "data": {"logged_out": True}}, extra_headers=[("Set-Cookie", _user_cookie_header("", True))])

    def _handle_upload_raw(self):
        principal = _principal(self.headers, self.client_address)
        ip = _client_ip(self.headers, self.client_address)
        if _is_ip_banned(ip):
            logger.warning(f"[Security] banned ip blocked: {ip}")
            self._json_error("IP_BANNED", "该 IP 已被禁止访问", 403)
            return
        if _upload_limit_exceeded(ip):
            logger.warning(f"[Security] upload limit exceeded: {ip}")
            self._json_error("UPLOAD_LIMIT_EXCEEDED", "当前 IP 在该时间段内排版次数已达上限，请稍后再试", 429)
            return
        if not _allow(ip):
            self._json_error("RATE_LIMITED", "请求过于频繁，请稍后再试", 429)
            return
        try:
            try:
                format_config = _decode_format_config(self.headers)
            except FormatConfigRequestError as cfg_error:
                self._json_error(
                    cfg_error.code,
                    cfg_error.message,
                    cfg_error.status,
                    field=cfg_error.field,
                    reason=cfg_error.reason,
                )
                return
            request_meta = _upload_request_meta(self.headers)
            try:
                _validate_requested_processing_mode(format_config, request_meta)
            except FormatConfigRequestError as cfg_error:
                self._json_error(
                    cfg_error.code,
                    cfg_error.message,
                    cfg_error.status,
                    field=cfg_error.field,
                    reason=cfg_error.reason,
                )
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_SIZE:
                self._json_error("FILE_TOO_LARGE", "文件过大或无内容", 413)
                return
            task_id = str(uuid.uuid4())
            raw_name = unquote(self.headers.get("X-Filename", "upload.docx"))
            task_upload_dir = _task_upload_dir(task_id)
            os.makedirs(task_upload_dir, exist_ok=True)
            input_path = _task_upload_input_path(task_id, raw_name)
            old_timeout = None
            try:
                old_timeout = self.connection.gettimeout()
            except Exception:
                old_timeout = None
            try:
                self.connection.settimeout(UPLOAD_READ_TIMEOUT_SECONDS)
                written = _read_exact_to_file(self.rfile, input_path, length, timeout=UPLOAD_READ_TIMEOUT_SECONDS)
            except (TimeoutError, socket.timeout):
                _cleanup_incomplete_upload(task_id, input_path)
                self._json_error("UPLOAD_TIMEOUT", "文件上传超时", 408)
                return
            except Exception:
                _cleanup_incomplete_upload(task_id, input_path)
                self._json_error("UPLOAD_FAILED", "文件上传失败，请重试", 400)
                return
            finally:
                if old_timeout is not None:
                    try:
                        self.connection.settimeout(old_timeout)
                    except Exception:
                        pass
            if written != length:
                _cleanup_incomplete_upload(task_id, input_path)
                self._json_error("INCOMPLETE_UPLOAD", "读取不完整", 400)
                return
            try:
                validate_docx_upload(
                    input_path,
                    max_upload_bytes=MAX_SIZE,
                    max_uncompressed_bytes=MAX_DOCX_UNCOMPRESSED_BYTES,
                    max_file_count=MAX_DOCX_FILE_COUNT,
                    max_xml_bytes=MAX_DOCX_XML_BYTES,
                    max_media_bytes=MAX_DOCX_MEDIA_BYTES,
                    max_compression_ratio=MAX_DOCX_COMPRESSION_RATIO,
                )
            except DocxValidationError as exc:
                _cleanup_incomplete_upload(task_id, input_path)
                self._json_error(exc.code, exc.message, exc.status)
                return
            compatibility_warnings = detect_docx_complexity(input_path)
            md5 = hashlib.md5()
            with open(input_path, "rb") as fp:
                while True:
                    chunk = fp.read(1024 * 1024)
                    if not chunk:
                        break
                    md5.update(chunk)
            h = md5.hexdigest()
            logger.info(
                f"[Upload] size={written} expect={length} md5={h} task={task_id[:8]} "
                f"preset={request_meta.get('preset_name','')} mode={request_meta.get('processing_mode','smart')} "
                f"frontend_config={bool(format_config)}"
            )
            _ensure_workers_started()
            try:
                info = _enqueue_task(task_id, input_path, raw_name, ip, self.headers.get("User-Agent", ""),
                                     format_config=format_config, request_meta=request_meta,
                                     compatibility_warnings=compatibility_warnings,
                                     owner_id=principal["owner_id"])
            except OverflowError as exc:
                _cleanup_incomplete_upload(task_id, input_path)
                message = str(exc)
                text = message.split(":", 1)[1].strip() if ":" in message else "服务器繁忙，请稍后再试"
                self._json_error("QUEUE_FULL", text, 503)
                return
            payload = {"task_id": task_id, "status": "queued", **info}
            if compatibility_warnings:
                payload["compatibility_warnings"] = compatibility_warnings
            self._json(payload, extra_headers=[("Set-Cookie", principal["cookie"])] if principal.get("cookie") else None)
        except Exception:
            try:
                if 'task_id' in locals():
                    _cleanup_incomplete_upload(task_id, locals().get("input_path", ""))
            except Exception:
                pass
            self._json_error("INTERNAL_ERROR", "服务器处理失败，请稍后重试", 500)

    def _handle_status(self, task_id: str):
        if not _is_safe_uuid(task_id):
            self._json_error("INVALID_TASK_ID", "无效的任务 ID", 400)
            return
        principal = _principal(self.headers, self.client_address)
        task = _public_task_state(task_id, principal["owner_id"])
        if not task:
            self._json_error("TASK_NOT_FOUND", "任务不存在或已过期", 404)
        else:
            self._json(task)

    def _handle_download(self, task_id: str):
        if not _is_safe_uuid(task_id):
            self._json_error("INVALID_TASK_ID", "无效的任务 ID", 400)
            return
        principal = _principal(self.headers, self.client_address)
        owner_id = principal["owner_id"]
        with TASKS_LOCK:
            task = TASKS.get(task_id)
            if task and owner_id and task.get("owner_id", "") != owner_id:
                task = None
        if not task or task.get("status") != "done":
            with _SQL_LOCK:
                conn = _sql()
                row = conn.execute(
                    "SELECT status, output_path, output_filename, filename FROM tasks WHERE id=? AND owner_id=?",
                    (task_id, owner_id),
                ).fetchone()
                conn.close()
            if not row or row["status"] != "done":
                self._json_error("FILE_NOT_READY", "文件未就绪", 400)
                return
            path = row["output_path"] or ""
            download_name = row["output_filename"] or _safe_download_filename(row["filename"] or "download.docx")
        else:
            path = task.get("output_path") or task.get("output") or ""
            download_name = task.get("download_name") or _safe_download_filename(task.get("filename", "download.docx"))
        if not path or not os.path.exists(path):
            self._json_error("FILE_EXPIRED", "文件已过期", 410)
            return
        try:
            file_size = os.path.getsize(path)
        except OSError:
            self._json_error("FILE_EXPIRED", "文件已过期", 410)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.send_header("Content-Disposition", _content_disposition_filename(download_name))
        self.send_header("Content-Length", str(file_size))
        self._set_cors_headers()
        self._set_security_headers()
        self.end_headers()
        _stream_file(path, self.wfile)

    def _redirect(self, target: str, extra_headers=None):
        self.send_response(303)
        self.send_header("Location", target)
        if extra_headers:
            if isinstance(extra_headers, dict):
                items = extra_headers.items()
            else:
                items = extra_headers
            for key, value in items:
                self.send_header(key, value)
        self._set_security_headers()
        self.end_headers()

    def _request_params(self, parsed) -> dict:
        cached = getattr(self, "_request_params_cache", None)
        if cached is not None:
            return cached
        params = {k: (v[-1] if isinstance(v, list) and v else v) for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        if self.command not in ("POST", "PUT", "DELETE"):
            return params
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return params
        body = _read_exact(self.rfile, length)
        if not body:
            return params
        content_type = (self.headers.get("Content-Type", "") or "").split(";", 1)[0].strip().lower()
        try:
            if content_type == "application/json":
                body_params = _parse_json_body(body)
                for key, value in body_params.items():
                    params[key] = value
            else:
                body_params = parse_qs(body.decode("utf-8"), keep_blank_values=True)
                for key, value in body_params.items():
                    params[key] = value[-1] if isinstance(value, list) and value else value
        except Exception:
            return params
        return params

    def _query_ip(self, parsed):
        qs = parse_qs(parsed.query)
        return (qs.get("ip") or qs.get("addr") or [""])[0].strip()

    def _handle_ip_detail(self, parsed):
        ip = self._query_ip(parsed)
        if not _is_ip(ip):
            self._json_error("INVALID_IP", "无效的 IP", 400)
            return
        self._text(_ip_detail_html(ip, self._admin_csrf_token(parsed)), "text/html")

    def _handle_ban(self, parsed):
        params = self._request_params(parsed)
        ip = (params.get("ip") or params.get("addr") or "").strip()
        if not _is_ip(ip):
            self._json_error("INVALID_IP", "无效的 IP", 400)
            return
        reason = str(params.get("reason") or "monitor")[:120]
        _ban_ip(ip, reason)
        logger.warning(f"[Security] ip banned: {ip} reason={reason}")
        self._redirect("/monitor")

    def _handle_unban(self, parsed):
        params = self._request_params(parsed)
        ip = (params.get("ip") or params.get("addr") or "").strip()
        if not _is_ip(ip):
            self._json_error("INVALID_IP", "无效的 IP", 400)
            return
        _unban_ip(ip)
        logger.warning(f"[Security] ip unbanned: {ip}")
        self._redirect("/monitor")

    def _handle_limit(self, parsed):
        params = self._request_params(parsed)
        enabled = str(params.get("enabled") or "0") == "1"
        try:
            window_seconds = int(params.get("window_seconds") or DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS)
        except ValueError:
            window_seconds = DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS
        try:
            count = int(params.get("count") or DEFAULT_UPLOAD_LIMIT_COUNT)
        except ValueError:
            count = DEFAULT_UPLOAD_LIMIT_COUNT
        _save_limit_settings(enabled, window_seconds, count)
        logger.warning(
            f"[Security] upload limit settings updated: enabled={enabled} "
            f"window_seconds={max(1, window_seconds)} count={max(1, count)}"
        )
        self._redirect("/monitor")

    def _handle_cleanup(self, parsed):
        # Retain the route for older administrator bookmarks. It deliberately
        # performs no deletion under the permanent retention policy.
        logger.info("[Cleaner] manual cleanup skipped: permanent file retention is enabled")
        self._redirect("/monitor")

    def _handle_presets_list(self):
        principal = _principal(self.headers, self.client_address)
        self._json(
            {"presets": _list_presets(principal["owner_id"])},
            extra_headers=[("Set-Cookie", principal["cookie"])] if principal.get("cookie") else None,
        )

    def _handle_preset_detail(self, preset_id: str):
        preset_id = str(preset_id or "").strip()
        if not preset_id:
            self._json_error("TEMPLATE_ID_INVALID", "无效的模板 ID", 400)
            return
        principal = _principal(self.headers, self.client_address)
        preset = _get_preset(preset_id, owner_id=principal["owner_id"])
        if not preset:
            self._json_error("TEMPLATE_NOT_FOUND", "模板不存在", 404)
            return
        self._json(preset, extra_headers=[("Set-Cookie", principal["cookie"])] if principal.get("cookie") else None)

    def _handle_preset_create(self):
        payload = getattr(self, "_request_params_cache", {})
        try:
            preset = _insert_preset(
                payload.get("name", ""),
                payload.get("description", ""),
                payload.get("config_json", {}),
                preset_id=payload.get("id", ""),
                owner_id=getattr(self, "_preset_owner_id", ""),
                visibility="public" if getattr(self, "_preset_admin", False) else "private",
            )
        except ValueError as exc:
            code, message = str(exc).split(":", 1) if ":" in str(exc) else ("TEMPLATE_INVALID", str(exc))
            self._json_error(code, message.strip(), 400)
            return
        extra_headers = []
        if getattr(self, "_preset_cookie_header", ""):
            extra_headers.append(("Set-Cookie", self._preset_cookie_header))
        self._json(preset, 201, extra_headers=extra_headers or None)

    def _handle_preset_update(self, preset_id: str):
        payload = getattr(self, "_request_params_cache", {})
        try:
            preset = _update_preset(
                preset_id,
                payload.get("name", ""),
                payload.get("description", ""),
                payload.get("config_json", {}),
                owner_id=getattr(self, "_preset_owner_id", ""),
                public_only=getattr(self, "_preset_public_only", True),
            )
        except ValueError as exc:
            code, message = str(exc).split(":", 1) if ":" in str(exc) else ("TEMPLATE_INVALID", str(exc))
            status = 404 if code == "TEMPLATE_NOT_FOUND" else 400
            self._json_error(code, message.strip(), status)
            return
        extra_headers = []
        if getattr(self, "_preset_cookie_header", ""):
            extra_headers.append(("Set-Cookie", self._preset_cookie_header))
        self._json(preset, extra_headers=extra_headers or None)

    def _handle_preset_delete(self, preset_id: str):
        try:
            result = _delete_preset(
                preset_id,
                owner_id=getattr(self, "_preset_owner_id", ""),
                public_only=getattr(self, "_preset_public_only", True),
            )
        except ValueError as exc:
            code, message = str(exc).split(":", 1) if ":" in str(exc) else ("TEMPLATE_INVALID", str(exc))
            status = 404 if code == "TEMPLATE_NOT_FOUND" else 400
            self._json_error(code, message.strip(), status)
            return
        extra_headers = []
        if getattr(self, "_preset_cookie_header", ""):
            extra_headers.append(("Set-Cookie", self._preset_cookie_header))
        self._json(result, 200, extra_headers=extra_headers or None)

    def _handle_log(self, task_id: str):
        if not _is_safe_uuid(task_id):
            self._json_error("INVALID_TASK_ID", "无效的任务 ID", 400)
            return
        path = ""
        with TASKS_LOCK:
            task = TASKS.get(task_id)
            if task:
                filename = task.get("log_filename", "")
                if filename:
                    path = os.path.join(LOG_DIR, filename)
        with _SQL_LOCK:
            conn = _sql()
            row = conn.execute(
                """SELECT filename, status, duration_ms, error_code, error_message,
                          created_at, log_path
                   FROM tasks WHERE id=?""",
                (task_id,),
            ).fetchone()
            conn.close()
        if not path:
            path = row["log_path"] if row else ""
        if not path:
            self._json_error("LOG_NOT_FOUND", "日志不存在", 404)
            return
        root = os.path.abspath(LOG_DIR)
        path = os.path.abspath(path)
        if not path.startswith(root + os.sep) or not os.path.exists(path):
            self._json_error("LOG_NOT_FOUND", "日志不存在或已过期", 404)
            return
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            log_text = _redact_sensitive_log(f.read())
        body = _pages_render_task_log_html(task_id, row, log_text)
        self._text(body, "text/html")

    def _text(self, body: str, mime: str, status: int = 200, extra_headers=None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if extra_headers:
            if isinstance(extra_headers, dict):
                items = extra_headers.items()
            else:
                items = extra_headers
            for key, value in items:
                self.send_header(key, value)
        self._set_cors_headers()
        self._set_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj: dict, status: int = 200, extra_headers=None):
        data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if extra_headers:
            if isinstance(extra_headers, dict):
                items = extra_headers.items()
            else:
                items = extra_headers
            for key, value in items:
                self.send_header(key, value)
        self._set_cors_headers()
        self._set_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _json_error(self, code: str, message: str, status: int, *, field: str = "", reason: str = "", retry_after: int = 0):
        headers = [("Retry-After", str(retry_after))] if retry_after else None
        if _route_path(urlparse(self.path).path).startswith("/auth/"):
            error = {"code": code, "message": message}
            if field:
                error["field"] = field
            if reason:
                error["reason"] = reason
            self._json({"ok": False, "error": error}, status, extra_headers=headers)
            return
        self._json(_error_payload(code, message, field=field, reason=reason), status, extra_headers=headers)

    def log_message(self, fmt, *args):
        pass


def main():
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print("Usage: python server.py")
        print("   or: python -m docxtool")
        print("Configure ADMIN_TOKEN and PROXY_SECRET before starting the service.")
        return
    _validate_secrets_or_exit()
    _startup_cleanup()
    _sql_init()
    _recover_inflight_tasks_on_startup()
    _ensure_workers_started()
    server = ThreadingHTTPServer(_server_bind_address(), Handler)
    server.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    urls = _startup_urls()
    print(f"排版工具:   {urls['tool']}")
    print(f"管理员登录: {urls['admin_login']}")
    print(f"监控面板:   登录后访问 {urls['monitor']}")
    print("鉴权配置:   ADMIN_TOKEN 已设置 | PROXY_SECRET 已设置")
    print(f"线程池: {MAX_WORKERS} | 队列: {MAX_QUEUE} | 上限: {MAX_SIZE//1048576}MB")
    print(f"限流: {RATE_WINDOW}s/IP | 文件保留: 永久")
    for line in _startup_time_check_lines():
        print(line)
    print("外网访问:   Cloudflare Pages /api/* -> Nginx 80 -> 127.0.0.1:9527")
    print("Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()

if __name__ == "__main__":
    main()
