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
import uuid
import time
import socket
import threading
import logging
import shutil
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from collections import OrderedDict
from urllib.parse import urlparse, parse_qs

from docxtool.document.importer import DocxImporter
from docxtool.document.engine import export_doc
from docxtool.application.process_document import process_uploaded_docx_task as _application_process_uploaded_docx_task
from docxtool.security import DocxIntegrityError, validate_docx_integrity
from docxtool.security.docx_validator import DocxValidationError, detect_docx_complexity, validate_docx_upload
from docxtool.document.style_config import (
    StyleRule, PageSettings, load_rules_and_settings, configure_logging, get_logger,
    make_document_log_path, set_context_log_path, reset_context_log_path,
)
from docxtool.paths import project_path, runtime_dir
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
from docxtool.web.auth_payloads import (
    auth_account_disabled_error as _auth_payloads_account_disabled_error,
    auth_invalid_credentials_error as _auth_payloads_invalid_credentials_error,
    auth_json_request_error as _auth_payloads_json_request_error,
    auth_login_rate_limit_error as _auth_payloads_login_rate_limit_error,
    auth_me_data as _auth_payloads_me_data,
    auth_me_extra_headers as _auth_payloads_me_extra_headers,
    auth_logout_extra_headers as _auth_payloads_logout_extra_headers,
    auth_logout_request_error as _auth_payloads_logout_request_error,
    auth_logout_response as _auth_payloads_logout_response,
    auth_register_error_from_exception as _auth_payloads_register_error_from_exception,
    auth_register_rate_limit_error as _auth_payloads_register_rate_limit_error,
    auth_session_extra_headers as _auth_payloads_session_extra_headers,
    auth_success_response as _auth_payloads_success_response,
    auth_validation_error_from_exception as _auth_payloads_validation_error_from_exception,
    ok_data_response as _auth_payloads_ok_data_response,
)
from docxtool.web.auth_route_handlers import (
    handle_auth_login as _auth_route_handle_login,
    handle_auth_logout as _auth_route_handle_logout,
    handle_auth_me as _auth_route_handle_me,
    handle_auth_register as _auth_route_handle_register,
    read_auth_json_request as _auth_route_read_json_request,
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
from docxtool.web.admin_access import (
    admin_csrf_invalid_error as _admin_access_csrf_invalid_error,
    admin_context_or_default as _admin_access_context_or_default,
    admin_login_error as _admin_access_login_error,
    admin_logout_cookie_header as _admin_access_logout_cookie_header,
    admin_post_csrf_allowed as _admin_access_post_csrf_allowed,
    admin_session_payload as _admin_access_session_payload,
    admin_unauthorized_error as _admin_access_unauthorized_error,
    csrf_token_from_admin_context as _admin_access_csrf_token,
)
from docxtool.web.admin_actions import (
    query_ip_from_parsed_url as _admin_actions_query_ip,
)
from docxtool.web.admin_forms import parse_admin_login_token as _admin_forms_parse_login_token
from docxtool.web.admin_pages import render_admin_login_html as _admin_pages_render_login_html
from docxtool.web.admin_route_handlers import (
    handle_ban as _admin_route_handle_ban,
    handle_cleanup as _admin_route_handle_cleanup,
    handle_ip_detail as _admin_route_handle_ip_detail,
    handle_limit as _admin_route_handle_limit,
    handle_unban as _admin_route_handle_unban,
)
from docxtool.web.admin_session_routes import (
    handle_admin_login as _admin_session_route_handle_login,
    handle_admin_logout as _admin_session_route_handle_logout,
    handle_admin_session as _admin_session_route_handle_session,
)
from docxtool.web.file_utils import (
    content_disposition_filename as _file_content_disposition_filename,
    is_safe_uuid as _file_is_safe_uuid,
    safe_download_filename as _file_safe_download_filename,
    safe_file_identifier as _file_safe_file_identifier,
    sanitize_filename as _file_sanitize_filename,
    sanitize_internal_error_detail as _file_sanitize_internal_error_detail,
)
from docxtool.web.file_api_auth import file_api_authorized as _file_auth_authorized
from docxtool.web.format_request import (
    FormatConfigRequestError,
    decode_format_config as _format_decode_format_config,
    format_config_error as _format_config_error_impl,
    processing_strategy_from_mode as _format_processing_strategy_from_mode,
    upload_request_meta as _format_upload_request_meta,
    validate_requested_processing_mode as _format_validate_requested_processing_mode,
)
from docxtool.web.frontend_pages import load_frontend_index_html as _frontend_load_index_html
from docxtool.web.health_route_handlers import (
    handle_health as _health_route_handle_health,
    handle_ready as _health_route_handle_ready,
    handle_version as _health_route_handle_version,
)
from docxtool.web.handler_dispatch import (
    dispatch_delete as _dispatch_delete,
    dispatch_get as _dispatch_get,
    dispatch_post as _dispatch_post,
    dispatch_put as _dispatch_put,
)
from docxtool.web.handler_lifecycle import (
    dispatch_http_method as _handler_lifecycle_dispatch_http_method,
    handle_options as _handler_lifecycle_handle_options,
    send_cors_headers as _handler_lifecycle_send_cors_headers,
    send_security_headers as _handler_lifecycle_send_security_headers,
)
from docxtool.web.handler_responses import (
    send_json_error_response as _handler_send_json_error_response,
    send_json_response as _handler_send_json_response,
    send_redirect_response as _handler_send_redirect_response,
    send_text_response as _handler_send_text_response,
)
from docxtool.web.health import (
    database_ready as _health_database_ready,
    dir_writable as _health_dir_writable,
    health_payload as _build_health_payload,
    ready_payload as _build_ready_payload,
    server_bind_address as _build_server_bind_address,
    startup_urls as _build_startup_urls,
    version_payload as _build_version_payload,
)
from docxtool.web.maintenance import cleaner_loop as _maintenance_cleaner_loop
from docxtool.web.log_redaction import redact_sensitive_log as _log_redact_sensitive_log
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
from docxtool.web.monitor_dashboard_page import render_monitor_dashboard_html as _monitor_dashboard_render_html
from docxtool.web.monitor_route_handlers import (
    handle_monitor as _monitor_route_handle_monitor,
    handle_stats as _monitor_route_handle_stats,
)
from docxtool.web.owner_migration import (
    migrate_anonymous_owner as _owner_migration_migrate_owner,
    migrate_anonymous_resources as _owner_migration_migrate_resources,
)
from docxtool.web.page_route_handlers import (
    handle_admin_login_page as _page_route_handle_admin_login_page,
    handle_frontend_index as _page_route_handle_frontend_index,
)
from docxtool.web.preset_config import (
    preset_error_from_exception as _preset_error_from_exception,
    preset_mutation_context as _preset_mutation_context,
    preset_template_origin_error as _preset_template_origin_error,
    preset_user_csrf_error as _preset_user_csrf_error,
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
from docxtool.web.preset_route_handlers import (
    handle_preset_create as _preset_route_handle_create,
    handle_preset_delete as _preset_route_handle_delete,
    handle_preset_detail as _preset_route_handle_detail,
    handle_preset_update as _preset_route_handle_update,
    handle_presets_list as _preset_route_handle_list,
)
from docxtool.web.protected_route_handlers import (
    handle_admin_post_route as _protected_route_handle_admin_post,
    handle_admin_resource_route as _protected_route_handle_admin_resource,
    handle_admin_route as _protected_route_handle_admin,
    handle_file_api_resource_route as _protected_route_handle_file_api_resource,
    handle_file_api_route as _protected_route_handle_file_api,
    handle_preset_mutation_route as _protected_route_handle_preset_mutation,
    handle_preset_resource_mutation_route as _protected_route_handle_preset_resource_mutation,
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
    prefixed_route_last_segment as _request_prefixed_route_last_segment,
    prefixed_route_tail as _request_prefixed_route_tail,
    route_path as _request_route_path,
)
from docxtool.web.request_params import request_params as _request_params_from_parts
from docxtool.web.route_authorization import (
    require_admin as _route_auth_require_admin,
    require_admin_post as _route_auth_require_admin_post,
    require_file_api as _route_auth_require_file_api,
    require_preset_mutation as _route_auth_require_preset_mutation,
    set_preset_mutation_context as _route_auth_set_preset_mutation_context,
)
from docxtool.web.responses import (
    docx_download_headers as _responses_docx_download_headers,
    file_expired_error as _responses_file_expired_error,
    file_not_ready_error as _responses_file_not_ready_error,
    incomplete_upload_error as _responses_incomplete_upload_error,
    internal_server_error as _responses_internal_server_error,
    invalid_task_id_error as _responses_invalid_task_id_error,
    log_not_found_error as _responses_log_not_found_error,
    optional_set_cookie_headers as _responses_optional_set_cookie_headers,
    queue_full_error as _responses_queue_full_error,
    queued_upload_body as _responses_queued_upload_body,
    security_headers as _responses_security_headers,
    task_not_found_error as _responses_task_not_found_error,
    upload_failed_error as _responses_upload_failed_error,
    upload_file_too_large_error as _responses_upload_file_too_large_error,
    upload_ip_banned_error as _responses_upload_ip_banned_error,
    upload_limit_exceeded_error as _responses_upload_limit_exceeded_error,
    upload_rate_limited_error as _responses_upload_rate_limited_error,
    upload_timeout_error as _responses_upload_timeout_error,
)
from docxtool.web.server_runtime import run_http_service as _runtime_run_http_service
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
from docxtool.web.task_queue import enqueue_task as _task_queue_enqueue_task
from docxtool.web.task_records import (
    mark_task_processing as _task_records_mark_processing,
    mark_task_terminal as _task_records_mark_terminal,
    record_task_queued as _task_records_record_queued,
)
from docxtool.web.task_recovery import recover_inflight_tasks_on_startup as _task_recovery_recover_inflight
from docxtool.web.task_route_handlers import (
    handle_download as _task_route_handle_download,
    handle_log as _task_route_handle_log,
    handle_status as _task_route_handle_status,
)
from docxtool.web.task_result import record_task_result as _task_result_record
from docxtool.web.task_worker import (
    ensure_worker_threads_started as _task_worker_ensure_threads_started,
    run_task_process_entry as _task_worker_run_process_entry,
    run_task_in_subprocess as _task_worker_run_in_subprocess,
    run_worker_loop as _task_worker_run_loop,
    run_task_with_execution_boundary as _task_worker_run_with_boundary,
    start_worker_threads as _task_worker_start_threads,
)
from docxtool.web.upload_route_handlers import handle_upload_raw as _upload_route_handle_raw
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

_first_query_value = _monitor_first_query_value
_clamp_int = _monitor_clamp_int

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

_monitor_query_from = _build_monitor_query_from
_normalize_monitor_query = _build_normalize_monitor_query
_where_sql = _monitor_where_sql
_page_count = _monitor_page_count

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
WORKER_STATE = {"started": False}
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

_is_ip = _client_is_ip

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


_safe_file_identifier = _file_safe_file_identifier
_sanitize_internal_error_detail = _file_sanitize_internal_error_detail


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
    """兼容旧入口：传入已校验任务信息，写入 queued 记录和内存队列。"""
    return _task_queue_enqueue_task(
        task_id,
        input_path,
        orig_name,
        ip,
        ua,
        format_config=format_config,
        request_meta=request_meta,
        compatibility_warnings=compatibility_warnings,
        owner_id=owner_id,
        task_queue=TASK_QUEUE,
        queue_cond=QUEUE_COND,
        tasks=TASKS,
        tasks_lock=TASKS_LOCK,
        max_queue=MAX_QUEUE,
        active_count=_active_count,
        record_task_queued=record_task_queued,
        task_queue_info=_task_queue_info,
        task_processing_options=_task_processing_options,
        prune_task_cache=_prune_task_cache,
    )
def _task_process_body(task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                       format_config: dict = None, request_meta: dict = None) -> dict:
    """兼容旧私有入口，传入任务参数并返回应用层 DOCX 处理结果字典。"""
    return _application_process_uploaded_docx_task(
        task_id,
        input_path,
        orig_name,
        ip,
        ua,
        format_config,
        request_meta,
        log_dir=LOG_DIR,
        output_root_dir=OUTPUT_DIR,
        importer_factory=DocxImporter,
        export_doc_func=export_doc,
        load_rules_and_settings=load_rules_and_settings,
        style_rule_cls=StyleRule,
        page_settings_cls=PageSettings,
        core_feature_defaults=_core_feature_config_defaults,
        make_document_log_path=make_document_log_path,
        set_context_log_path=set_context_log_path,
        reset_context_log_path=reset_context_log_path,
        task_output_dir=_task_output_dir,
        task_output_path=_task_output_path,
        ensure_path_within=_ensure_path_within,
        safe_file_identifier=_safe_file_identifier,
        safe_download_filename=_safe_download_filename,
        sanitize_error=_sanitize_internal_error_detail,
        public_recognition_summary=_public_recognition_summary,
        validate_docx_integrity=validate_docx_integrity,
        integrity_error_cls=DocxIntegrityError,
        logger=logger,
    )

def _task_process_entry(result_queue, task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                        format_config: dict = None, request_meta: dict = None) -> None:
    """兼容旧 spawn target，传入结果队列和任务参数，执行子进程任务并写回结果。"""
    _task_worker_run_process_entry(
        result_queue,
        task_id,
        input_path,
        orig_name,
        ip,
        ua,
        format_config,
        request_meta,
        process_task_body=_task_process_body,
        sanitize_error=_sanitize_internal_error_detail,
    )

def _task_process_direct(task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                         format_config: dict = None, request_meta: dict = None) -> dict:
    return _task_process_body(task_id, input_path, orig_name, ip, ua, format_config, request_meta)

def _task_process_subprocess(task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                             format_config: dict = None, request_meta: dict = None) -> dict:
    """兼容旧私有入口，传入任务参数后在 spawn 子进程内执行并返回结果字典。"""
    import multiprocessing as mp

    return _task_worker_run_in_subprocess(
        task_id,
        input_path,
        orig_name,
        ip,
        ua,
        format_config,
        request_meta,
        process_timeout=PROCESS_TIMEOUT,
        context_factory=mp.get_context,
        process_target=_task_process_entry,
        cleanup_output_path=_cleanup_output_path,
        task_output_dir=_task_output_dir,
    )

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
    """兼容旧私有入口，传入全局队列和回调后持续消费后台任务。"""
    _task_worker_run_loop(
        TASK_QUEUE,
        QUEUE_COND,
        TASKS,
        TASKS_LOCK,
        mark_task_processing=_mark_task_processing,
        process_task=_process_task,
    )

def _ensure_workers_started():
    """兼容旧私有入口，传入 worker 状态和启动回调，确保后台线程只启动一次。"""
    _task_worker_ensure_threads_started(
        WORKER_THREADS,
        WORKERS_LOCK,
        WORKER_STATE,
        max_workers=MAX_WORKERS,
        worker_target=_worker_loop,
        start_threads=_task_worker_start_threads,
    )

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

_error_payload = _request_error_payload
_cookie_value = _request_cookie_value

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
    """兼容旧入口：传入请求头和客户端地址，返回文件 API 是否授权。"""
    return _file_auth_authorized(
        headers,
        client_address,
        proxy_secret=PROXY_SECRET,
        production_mode=PRODUCTION_MODE,
        compare_secret=_compare_secret,
    )

_format_config_error = _format_config_error_impl

def _decode_format_config(headers) -> dict:
    """兼容旧入口：解码请求头中的格式配置并返回已验证配置。"""
    return _format_decode_format_config(
        headers,
        max_header_bytes=MAX_FORMAT_CONFIG_HEADER_BYTES,
        max_json_bytes=MAX_FORMAT_CONFIG_JSON_BYTES,
    )

_upload_request_meta = _format_upload_request_meta
_processing_strategy_from_mode = _format_processing_strategy_from_mode


def _validate_requested_processing_mode(format_config: dict | None, request_meta: dict) -> None:
    """兼容旧入口：校验 header 处理模式与格式配置并写入 request_meta。"""
    _format_validate_requested_processing_mode(format_config, request_meta)

_admin_token_from = _request_admin_token_from_query
_admin_url = _request_admin_url

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

_route_path = _request_route_path
_prefixed_route_tail = _request_prefixed_route_tail
_prefixed_route_last_segment = _request_prefixed_route_last_segment
_json_dumps = _request_json_dumps
_parse_json_body = _request_parse_json_body

_normalize_template_name = _preset_normalize_template_name
_normalize_template_id = _preset_normalize_template_id

def _validate_template_config(config_obj: dict) -> dict:
    """兼容旧入口：传入模板配置对象，返回归一化后的可持久化配置。"""
    return _preset_validate_template_config(config_obj, core_feature_defaults=_core_feature_config_defaults())

_preset_row_to_dict = _preset_row_to_dict_impl

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
    return _health_database_ready(connect=_sql, sql_lock=_SQL_LOCK)

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
    """兼容旧私有入口，传入监控统计和 CSRF token，返回管理员仪表盘 HTML。"""
    return _monitor_dashboard_render_html(
        stats,
        admin_token,
        limit_settings=_limit_settings,
        csrf_hidden_input=_csrf_hidden_input,
        normalize_monitor_query=_normalize_monitor_query,
        pager_html=_pager_html,
        ready_payload=_ready_payload,
        version_payload=_version_payload,
        render_recent_task_rows=_pages_render_recent_task_rows,
        render_top_ip_rows=_pages_render_top_ip_rows,
        render_banned_ip_rows=_pages_render_banned_ip_rows,
        render_trend_bars=_pages_render_trend_bars,
        render_health_check_items=_pages_render_health_check_items,
        admin_url=_admin_url,
        html_escape=_html_escape,
        now_local=_now_local,
        max_monitor_page_size=MAX_MONITOR_PAGE_SIZE,
    )

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

_is_safe_uuid = _file_is_safe_uuid
_sanitize_filename = _file_sanitize_filename
_safe_download_filename = _file_safe_download_filename
_content_disposition_filename = _file_content_disposition_filename

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

_html_escape = _request_html_escape
_redact_sensitive_log = _log_redact_sensitive_log

_split_ip_header = _client_split_ip_header
_is_ipv4 = _client_is_ipv4

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
        """无需传入数据，发送所有安全响应头并返回 None。"""
        _handler_lifecycle_send_security_headers(self, security_headers=_responses_security_headers)

    def _set_cors_headers(self):
        """无需传入数据，根据请求 Origin 发送 CORS 响应头。"""
        _handler_lifecycle_send_cors_headers(self, cors_headers_for_origin=cors_headers_for_request)

    def do_OPTIONS(self):
        """无需传入数据，发送 OPTIONS 预检响应并返回 None。"""
        _handler_lifecycle_handle_options(
            self,
            cors_headers=self._set_cors_headers,
            security_headers=self._set_security_headers,
        )

    def do_GET(self):
        """无需传入数据，解析当前路径并分派 GET 路由。"""
        _handler_lifecycle_dispatch_http_method(self, route_path=_route_path, dispatch=_dispatch_get)

    def do_POST(self):
        """无需传入数据，解析当前路径并分派 POST 路由。"""
        _handler_lifecycle_dispatch_http_method(self, route_path=_route_path, dispatch=_dispatch_post)

    def do_PUT(self):
        """无需传入数据，解析当前路径并分派 PUT 路由。"""
        _handler_lifecycle_dispatch_http_method(self, route_path=_route_path, dispatch=_dispatch_put)

    def do_DELETE(self):
        """无需传入数据，解析当前路径并分派 DELETE 路由。"""
        _handler_lifecycle_dispatch_http_method(self, route_path=_route_path, dispatch=_dispatch_delete)

    def _serve_html(self):
        """无需传入数据，发送前端首页 HTML；页面缺失时返回 404。"""
        _page_route_handle_frontend_index(self, load_index_html=_frontend_load_index_html)

    def _serve_admin_login(self):
        """无需传入数据，发送管理员登录页面 HTML。"""
        _page_route_handle_admin_login_page(self, render_login_html=_admin_pages_render_login_html)

    def _handle_health(self):
        """无需传入数据，发送健康检查 JSON 响应并返回 None。"""
        _health_route_handle_health(self, health_payload=_health_payload)

    def _handle_ready(self):
        """无需传入数据，发送 readiness JSON 响应并返回 None。"""
        _health_route_handle_ready(self, ready_payload=_ready_payload)

    def _handle_version(self):
        """无需传入数据，发送版本信息 JSON 响应并返回 None。"""
        _health_route_handle_version(self, version_payload=_version_payload)

    def _handle_stats(self, parsed):
        """传入已解析 URL，通过管理员鉴权后发送监控统计 JSON。"""
        _monitor_route_handle_stats(
            self,
            parsed,
            require_admin=self._require_admin,
            monitor_query_from=_monitor_query_from,
            get_sql_stats=get_sql_stats,
        )

    def _handle_monitor(self, parsed):
        """传入已解析 URL，通过管理员鉴权后发送监控 HTML 或刷新 session。"""
        _monitor_route_handle_monitor(
            self,
            parsed,
            require_admin=self._require_admin,
            admin_context_or_default=self._admin_context_or_default,
            create_admin_session=_create_admin_session,
            admin_cookie_header=_admin_cookie_header,
            monitor_query_from=_monitor_query_from,
            get_sql_stats=get_sql_stats,
            monitor_html=_monitor_html,
            admin_csrf_token=self._admin_csrf_token,
        )

    def _handle_ip_detail_route(self, parsed):
        """传入已解析 URL，通过管理员鉴权后发送 IP 详情 HTML。"""
        _protected_route_handle_admin(parsed, require_admin=self._require_admin, action=self._handle_ip_detail)

    def _handle_upload_route(self):
        """无需传入数据，通过文件 API 鉴权后处理上传请求。"""
        _protected_route_handle_file_api(require_file_api=self._require_file_api, action=self._handle_upload_raw)

    def _handle_status_route(self, task_id: str):
        """传入任务 ID，通过文件 API 鉴权后发送任务状态响应。"""
        _protected_route_handle_file_api_resource(
            task_id,
            require_file_api=self._require_file_api,
            action=self._handle_status,
        )

    def _handle_download_route(self, file_id: str):
        """传入任务或文件 ID，通过文件 API 鉴权后发送 DOCX 下载响应。"""
        _protected_route_handle_file_api_resource(
            file_id,
            require_file_api=self._require_file_api,
            action=self._handle_download,
        )

    def _handle_log_route(self, parsed, task_id: str):
        """传入已解析 URL 和任务 ID，通过管理员鉴权后发送任务日志页面。"""
        _protected_route_handle_admin_resource(
            parsed,
            task_id,
            require_admin=self._require_admin,
            action=self._handle_log,
        )

    def _handle_ban_route(self, parsed):
        """传入已解析 URL，通过管理员 POST 鉴权后执行封禁动作。"""
        _protected_route_handle_admin_post(parsed, require_admin_post=self._require_admin_post, action=self._handle_ban)

    def _handle_unban_route(self, parsed):
        """传入已解析 URL，通过管理员 POST 鉴权后执行解封动作。"""
        _protected_route_handle_admin_post(
            parsed,
            require_admin_post=self._require_admin_post,
            action=self._handle_unban,
        )

    def _handle_limit_route(self, parsed):
        """传入已解析 URL，通过管理员 POST 鉴权后更新上传限制。"""
        _protected_route_handle_admin_post(
            parsed,
            require_admin_post=self._require_admin_post,
            action=self._handle_limit,
        )

    def _handle_cleanup_route(self, parsed):
        """传入已解析 URL，通过管理员 POST 鉴权后执行兼容清理入口。"""
        _protected_route_handle_admin_post(
            parsed,
            require_admin_post=self._require_admin_post,
            action=self._handle_cleanup,
        )

    def _handle_preset_create_route(self, parsed):
        """传入已解析 URL，通过模板变更鉴权后创建 preset。"""
        _protected_route_handle_preset_mutation(
            parsed,
            require_preset_mutation=self._require_preset_mutation,
            action=self._handle_preset_create,
        )

    def _handle_preset_update_route(self, parsed, preset_id: str):
        """传入已解析 URL 和模板 ID，通过模板变更鉴权后更新 preset。"""
        _protected_route_handle_preset_resource_mutation(
            parsed,
            preset_id,
            require_preset_mutation=self._require_preset_mutation,
            action=self._handle_preset_update,
        )

    def _handle_preset_delete_route(self, parsed, preset_id: str):
        """传入已解析 URL 和模板 ID，通过模板变更鉴权后删除 preset。"""
        _protected_route_handle_preset_resource_mutation(
            parsed,
            preset_id,
            require_preset_mutation=self._require_preset_mutation,
            action=self._handle_preset_delete,
        )

    def _admin_context_or_default(self):
        return _admin_access_context_or_default(getattr(self, "_admin_context", None))

    def _admin_csrf_token(self, parsed=None) -> str:
        return _admin_access_csrf_token(self._admin_context_or_default())

    def _handle_admin_session(self):
        """无需传入数据，发送管理员 session JSON 或未授权错误。"""
        _admin_session_route_handle_session(
            self,
            session_from_headers=_admin_session_from_headers,
            session_payload=_admin_access_session_payload,
        )

    def _handle_admin_login(self):
        """无需传入数据，读取管理员登录表单并建立 session。"""
        _admin_session_route_handle_login(
            self,
            admin_token=ADMIN_TOKEN,
            read_exact=_read_exact,
            parse_login_token=_admin_forms_parse_login_token,
            login_error=_admin_access_login_error,
            create_admin_session=_create_admin_session,
            admin_cookie_header=_admin_cookie_header,
        )

    def _handle_admin_logout(self):
        """无需传入数据，删除管理员 session 并跳转登录页。"""
        _admin_session_route_handle_logout(
            self,
            session_from_headers=_admin_session_from_headers,
            delete_admin_session=_delete_admin_session,
            logout_cookie_header=_admin_access_logout_cookie_header,
            cookie_name=ADMIN_SESSION_COOKIE,
            secure=COOKIE_SECURE,
        )

    def _require_admin(self, parsed) -> bool:
        """传入已解析 URL，校验管理员权限；成功返回 True，失败发送错误。"""
        return _route_auth_require_admin(
            self,
            parsed,
            admin_request_context=_admin_request_context,
            unauthorized_error=_admin_access_unauthorized_error,
        )

    def _require_admin_post(self, parsed) -> bool:
        """传入已解析 URL，校验管理员 POST 和 CSRF；成功返回 True。"""
        return _route_auth_require_admin_post(
            self,
            parsed,
            admin_request_context=_admin_request_context,
            unauthorized_error=_admin_access_unauthorized_error,
            request_params=self._request_params,
            admin_post_csrf_allowed=lambda ctx, params, headers: _admin_access_post_csrf_allowed(
                ctx,
                params,
                headers,
                csrf_header_name=ADMIN_CSRF_HEADER,
            ),
            csrf_invalid_error=_admin_access_csrf_invalid_error,
        )

    def _set_preset_mutation_context(self, context: dict) -> None:
        """传入 preset 变更上下文字典，写入当前请求处理器的兼容状态属性。"""
        _route_auth_set_preset_mutation_context(self, context)

    def _require_preset_mutation(self, parsed) -> bool:
        """传入已解析 URL，校验管理员或私人 preset 修改权限；成功返回 True。"""
        return _route_auth_require_preset_mutation(
            self,
            parsed,
            admin_request_context=_admin_request_context,
            require_admin_post=self._require_admin_post,
            anonymous_template_origin_allowed=_anonymous_template_origin_allowed,
            template_origin_error=_preset_template_origin_error,
            request_params=self._request_params,
            principal=_principal,
            auth_csrf_allowed=_auth_csrf_allowed,
            user_csrf_error=_preset_user_csrf_error,
            preset_mutation_context=_preset_mutation_context,
        )

    def _require_file_api(self) -> bool:
        """无需传入数据，校验文件 API 访问权限；失败时发送代理密钥错误。"""
        return _route_auth_require_file_api(self, file_api_authorized=_file_api_authorized)

    def _parsed_url(self):
        """无需传入数据，返回当前请求路径解析后的 URL 对象。"""
        return urlparse(self.path)

    def _auth_json_request(self) -> dict | None:
        """无需传入数据，校验并返回认证 JSON 请求参数；失败时发送错误。"""
        return _auth_route_read_json_request(
            self,
            origin_allowed=_auth_origin_allowed,
            json_request_error=_auth_payloads_json_request_error,
        )

    def _handle_auth_me(self):
        """无需传入数据，发送当前用户登录状态 JSON。"""
        _auth_route_handle_me(
            self,
            principal=_principal,
            me_data=_auth_payloads_me_data,
            me_extra_headers=_auth_payloads_me_extra_headers,
            ok_data_response=_auth_payloads_ok_data_response,
            user_cookie_header=_user_cookie_header,
        )

    def _handle_auth_register(self):
        """无需传入数据，注册普通用户并发送认证 JSON 响应。"""
        _auth_route_handle_register(
            self,
            read_json_request=self._auth_json_request,
            auth_rate_allow=_auth_rate_allow,
            client_ip=_client_ip,
            register_rate_limit_error=_auth_payloads_register_rate_limit_error,
            validate_username=validate_username,
            validate_password=validate_password,
            validation_error_from_exception=_auth_payloads_validation_error_from_exception,
            principal=_principal,
            new_user_id=lambda: f"usr_{uuid.uuid4().hex}",
            now_unix=_now_unix,
            sql_lock=_SQL_LOCK,
            connect=_sql,
            hash_password=hash_password,
            migrate_anonymous_owner=_migrate_anonymous_owner,
            register_error_from_exception=_auth_payloads_register_error_from_exception,
            create_user_session=_create_user_session,
            success_response=_auth_payloads_success_response,
            session_extra_headers=_auth_payloads_session_extra_headers,
            user_cookie_header=_user_cookie_header,
            anonymous_clear_cookie_header=_anonymous_user_cookie_clear_header,
        )

    def _handle_auth_login(self):
        """无需传入数据，登录普通用户并发送认证 JSON 响应。"""
        _auth_route_handle_login(
            self,
            read_json_request=self._auth_json_request,
            validate_username=validate_username,
            invalid_credentials_error=_auth_payloads_invalid_credentials_error,
            client_ip=_client_ip,
            auth_rate_allow=_auth_rate_allow,
            login_rate_limit_error=_auth_payloads_login_rate_limit_error,
            sql_lock=_SQL_LOCK,
            connect=_sql,
            verify_password=verify_password,
            account_disabled_error=_auth_payloads_account_disabled_error,
            hash_password=hash_password,
            now_unix=_now_unix,
            principal=_principal,
            migrate_anonymous_resources=_migrate_anonymous_resources,
            create_user_session=_create_user_session,
            parse_bool=_parse_bool,
            success_response=_auth_payloads_success_response,
            session_extra_headers=_auth_payloads_session_extra_headers,
            user_cookie_header=_user_cookie_header,
            anonymous_clear_cookie_header=_anonymous_user_cookie_clear_header,
        )

    def _handle_auth_logout(self):
        """无需传入数据，退出普通用户登录并发送 JSON 响应。"""
        _auth_route_handle_logout(
            self,
            origin_allowed=_auth_origin_allowed,
            logout_request_error=_auth_payloads_logout_request_error,
            principal=_principal,
            auth_csrf_allowed=_auth_csrf_allowed,
            delete_user_session=_delete_user_session,
            logout_response=_auth_payloads_logout_response,
            logout_extra_headers=_auth_payloads_logout_extra_headers,
            user_cookie_header=_user_cookie_header,
        )

    def _handle_upload_raw(self):
        """无需传入数据，处理 DOCX 上传、校验和任务入队，并发送 JSON 响应。"""
        _upload_route_handle_raw(
            self,
            principal=_principal,
            client_ip=_client_ip,
            is_ip_banned=_is_ip_banned,
            upload_limit_exceeded=_upload_limit_exceeded,
            allow_upload=_allow,
            logger=logger,
            upload_ip_banned_error=_responses_upload_ip_banned_error,
            upload_limit_exceeded_error=_responses_upload_limit_exceeded_error,
            upload_rate_limited_error=_responses_upload_rate_limited_error,
            decode_format_config=_decode_format_config,
            format_config_error_type=FormatConfigRequestError,
            upload_request_meta=_upload_request_meta,
            validate_requested_processing_mode=_validate_requested_processing_mode,
            max_size=MAX_SIZE,
            new_task_id=lambda: str(uuid.uuid4()),
            task_upload_dir=_task_upload_dir,
            task_upload_input_path=_task_upload_input_path,
            upload_read_timeout_seconds=UPLOAD_READ_TIMEOUT_SECONDS,
            read_exact_to_file=_read_exact_to_file,
            timeout_errors=(TimeoutError, socket.timeout),
            cleanup_incomplete_upload=_cleanup_incomplete_upload,
            upload_timeout_error=_responses_upload_timeout_error,
            upload_failed_error=_responses_upload_failed_error,
            incomplete_upload_error=_responses_incomplete_upload_error,
            validate_docx_upload=validate_docx_upload,
            docx_validation_error_type=DocxValidationError,
            docx_validation_limits={
                "max_uncompressed_bytes": MAX_DOCX_UNCOMPRESSED_BYTES,
                "max_file_count": MAX_DOCX_FILE_COUNT,
                "max_xml_bytes": MAX_DOCX_XML_BYTES,
                "max_media_bytes": MAX_DOCX_MEDIA_BYTES,
                "max_compression_ratio": MAX_DOCX_COMPRESSION_RATIO,
            },
            detect_docx_complexity=detect_docx_complexity,
            ensure_workers_started=_ensure_workers_started,
            enqueue_task=_enqueue_task,
            queue_full_error=_responses_queue_full_error,
            queued_upload_body=_responses_queued_upload_body,
            optional_set_cookie_headers=_responses_optional_set_cookie_headers,
            file_too_large_error=_responses_upload_file_too_large_error,
            internal_server_error=_responses_internal_server_error,
        )

    def _handle_status(self, task_id: str):
        """传入任务 ID，发送公开任务状态或稳定错误响应。"""
        _task_route_handle_status(
            self,
            task_id,
            is_safe_uuid=_is_safe_uuid,
            invalid_task_id_error=_responses_invalid_task_id_error,
            task_not_found_error=_responses_task_not_found_error,
            principal=_principal,
            public_task_state=_public_task_state,
        )

    def _handle_download(self, task_id: str):
        """传入任务 ID，发送 DOCX 下载响应或稳定错误响应。"""
        _task_route_handle_download(
            self,
            task_id,
            is_safe_uuid=_is_safe_uuid,
            invalid_task_id_error=_responses_invalid_task_id_error,
            file_not_ready_error=_responses_file_not_ready_error,
            file_expired_error=_responses_file_expired_error,
            principal=_principal,
            tasks=TASKS,
            tasks_lock=TASKS_LOCK,
            sql_lock=_SQL_LOCK,
            connect=_sql,
            safe_download_filename=_safe_download_filename,
            content_disposition_filename=_content_disposition_filename,
            docx_download_headers=_responses_docx_download_headers,
            stream_file=_stream_file,
        )

    def _redirect(self, target: str, extra_headers=None):
        """传入目标地址和可选响应头，按旧行为发送 303 跳转响应。"""
        _handler_send_redirect_response(
            self,
            target=target,
            security_headers=self._set_security_headers,
            extra_headers=extra_headers,
        )

    def _request_params(self, parsed) -> dict:
        cached = getattr(self, "_request_params_cache", None)
        if cached is not None:
            return cached
        return _request_params_from_parts(
            parsed,
            self.command,
            self.headers,
            lambda length: _read_exact(self.rfile, length),
        )

    def _query_ip(self, parsed):
        return _admin_actions_query_ip(parsed)

    def _handle_ip_detail(self, parsed):
        """传入已解析 URL，发送 IP 详情页面或无效 IP 错误。"""
        _admin_route_handle_ip_detail(
            self,
            parsed,
            is_ip=_is_ip,
            render_ip_detail_html=_ip_detail_html,
        )

    def _handle_ban(self, parsed):
        """传入已解析 URL，执行 IP 封禁动作并跳转监控页。"""
        _admin_route_handle_ban(self, parsed, is_ip=_is_ip, ban_ip=_ban_ip, logger=logger)

    def _handle_unban(self, parsed):
        """传入已解析 URL，执行 IP 解封动作并跳转监控页。"""
        _admin_route_handle_unban(self, parsed, is_ip=_is_ip, unban_ip=_unban_ip, logger=logger)

    def _handle_limit(self, parsed):
        """传入已解析 URL，更新上传限额配置并跳转监控页。"""
        _admin_route_handle_limit(
            self,
            parsed,
            default_window_seconds=DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS,
            default_count=DEFAULT_UPLOAD_LIMIT_COUNT,
            save_limit_settings=_save_limit_settings,
            logger=logger,
        )

    def _handle_cleanup(self, parsed):
        """传入已解析 URL，执行永久保留策略下的兼容清理入口。"""
        _admin_route_handle_cleanup(self, logger=logger)

    def _handle_presets_list(self):
        """无需传入数据，发送当前 owner 可见 preset 列表。"""
        _preset_route_handle_list(
            self,
            principal=_principal,
            list_presets=_list_presets,
            optional_set_cookie_headers=_responses_optional_set_cookie_headers,
        )

    def _handle_preset_detail(self, preset_id: str):
        """传入模板 ID，发送单个 preset 或稳定错误响应。"""
        _preset_route_handle_detail(
            self,
            preset_id,
            principal=_principal,
            get_preset=_get_preset,
            optional_set_cookie_headers=_responses_optional_set_cookie_headers,
        )

    def _handle_preset_create(self):
        """无需传入数据，根据缓存请求参数创建 preset 并发送 JSON。"""
        _preset_route_handle_create(
            self,
            insert_preset=_insert_preset,
            preset_error_from_exception=_preset_error_from_exception,
            optional_set_cookie_headers=_responses_optional_set_cookie_headers,
        )

    def _handle_preset_update(self, preset_id: str):
        """传入模板 ID，根据缓存请求参数更新 preset 并发送 JSON。"""
        _preset_route_handle_update(
            self,
            preset_id,
            update_preset=_update_preset,
            preset_error_from_exception=_preset_error_from_exception,
            optional_set_cookie_headers=_responses_optional_set_cookie_headers,
        )

    def _handle_preset_delete(self, preset_id: str):
        """传入模板 ID，删除 preset 并发送 JSON 结果。"""
        _preset_route_handle_delete(
            self,
            preset_id,
            delete_preset=_delete_preset,
            preset_error_from_exception=_preset_error_from_exception,
            optional_set_cookie_headers=_responses_optional_set_cookie_headers,
        )

    def _handle_log(self, task_id: str):
        """传入任务 ID，发送脱敏任务日志页面或稳定错误响应。"""
        _task_route_handle_log(
            self,
            task_id,
            is_safe_uuid=_is_safe_uuid,
            invalid_task_id_error=_responses_invalid_task_id_error,
            log_not_found_error=_responses_log_not_found_error,
            tasks=TASKS,
            tasks_lock=TASKS_LOCK,
            sql_lock=_SQL_LOCK,
            connect=_sql,
            log_dir=LOG_DIR,
            redact_sensitive_log=_redact_sensitive_log,
            render_task_log_html=_pages_render_task_log_html,
        )

    def _text(self, body: str, mime: str, status: int = 200, extra_headers=None):
        """传入文本、MIME 和状态码，按旧行为发送文本响应。"""
        _handler_send_text_response(
            self,
            body=body,
            mime=mime,
            status=status,
            cors_headers=self._set_cors_headers,
            security_headers=self._set_security_headers,
            extra_headers=extra_headers,
        )

    def _json(self, obj: dict, status: int = 200, extra_headers=None):
        """传入 JSON 对象和状态码，按旧行为发送 JSON 响应。"""
        _handler_send_json_response(
            self,
            obj=obj,
            status=status,
            cors_headers=self._set_cors_headers,
            security_headers=self._set_security_headers,
            extra_headers=extra_headers,
        )

    def _json_error_fields(self, error: tuple[str, str, int] | tuple[str, str, int, int]):
        """传入错误码、提示、状态码和可选重试秒数，按现有 JSON 错误格式发送响应。"""
        code, message, status, *retry = error
        retry_after = retry[0] if retry else 0
        self._json_error(code, message, status, retry_after=retry_after)

    def _json_error(self, code: str, message: str, status: int, *, field: str = "", reason: str = "", retry_after: int = 0):
        """传入错误字段和状态码，按当前路由类型发送兼容 JSON 错误响应。"""
        _handler_send_json_error_response(
            self,
            auth_route=_route_path(urlparse(self.path).path).startswith("/auth/"),
            code=code,
            message=message,
            status=status,
            cors_headers=self._set_cors_headers,
            security_headers=self._set_security_headers,
            field=field,
            reason=reason,
            retry_after=retry_after,
            legacy_error_body=_error_payload,
        )

    def log_message(self, fmt, *args):
        pass


def main():
    """兼容旧启动入口，无需传入数据，完成 Web 服务启动编排。"""
    return _runtime_run_http_service(
        argv=sys.argv,
        server_class=ThreadingHTTPServer,
        handler_class=Handler,
        bind_address=_server_bind_address,
        startup_urls=_startup_urls,
        startup_time_check_lines=_startup_time_check_lines,
        validate_secrets=_validate_secrets_or_exit,
        startup_cleanup=_startup_cleanup,
        init_database=_sql_init,
        recover_inflight_tasks=_recover_inflight_tasks_on_startup,
        ensure_workers_started=_ensure_workers_started,
        max_workers=MAX_WORKERS,
        max_queue=MAX_QUEUE,
        max_size=MAX_SIZE,
        rate_window=RATE_WINDOW,
    )

if __name__ == "__main__":
    main()
