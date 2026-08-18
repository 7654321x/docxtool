# ruff: noqa: E402, F401
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
from docxtool.document.configuration.models import PageSettings, StyleRule
from docxtool.document.configuration.validation import load_rules_and_settings
from docxtool.document.diagnostics.logging import (
    configure_logging,
    get_logger,
    make_document_log_path,
    reset_context_log_path,
    set_context_log_path,
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
from docxtool.wps_server.config import (
    WPS_ADMIN_MUTATIONS_ENABLED as _WPS_ADMIN_MUTATIONS_ENABLED,
    require_separate_database_paths as _wps_require_separate_database_paths,
    resolve_wps_database_path as _wps_resolve_database_path,
)
from docxtool.wps_server.database import (
    connect as _wps_database_connect,
    database_ready as _wps_database_ready_check,
    initialize_database as _wps_initialize_database,
)
from docxtool.wps_server.format_config import load_active_format_profile as _wps_load_active_format_profile
from docxtool.wps_server.route_handlers import handle_wps_action as _wps_route_handle_action
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
from docxtool.web.admin_workspace_page import (
    render_admin_home_page as _admin_workspace_render_home,
    render_admin_web_ip_detail_page as _admin_workspace_render_ip_detail,
    render_admin_web_page as _admin_workspace_render_web,
    render_admin_web_task_log_page as _admin_workspace_render_task_log,
    render_wps_devices_page as _admin_workspace_render_devices,
    render_wps_overview_page as _admin_workspace_render_wps_overview,
    render_wps_tasks_page as _admin_workspace_render_tasks,
    render_wps_user_page as _admin_workspace_render_user,
    render_wps_users_page as _admin_workspace_render_users,
)
from docxtool.web.admin_workspace_routes import (
    handle_web_page as _admin_workspace_route_handle_web,
    ip_compat_target as _admin_workspace_ip_compat_target,
    log_compat_target as _admin_workspace_log_compat_target,
    monitor_compat_target as _admin_workspace_monitor_compat_target,
    task_id_from_query as _admin_workspace_task_id_from_query,
    workspace_session_target as _admin_workspace_session_target,
)
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
from docxtool.wps_server.admin_routes import (
    handle_devices as _wps_admin_route_handle_devices,
    handle_user_delete as _wps_admin_route_handle_user_delete,
    handle_user_notification as _wps_admin_route_handle_user_notification,
    handle_overview as _wps_admin_route_handle_overview,
    handle_tasks as _wps_admin_route_handle_tasks,
    handle_device_status as _wps_admin_route_handle_device_status,
    handle_user as _wps_admin_route_handle_user,
    handle_user_password_reset as _wps_admin_route_handle_user_password_reset,
    handle_user_status as _wps_admin_route_handle_user_status,
    handle_users as _wps_admin_route_handle_users,
    handle_workspace as _wps_admin_route_handle_workspace,
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
    public_startup_urls as _build_public_startup_urls,
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
    gateway_request_authorized as _route_gateway_request_authorized,
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
    WEAK_SECRETS as _SECRETS_WEAK_SECRETS,
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
from docxtool.web.bootstrap import (
    ADMIN_CSRF_HEADER,
    ADMIN_SESSION_COOKIE,
    ANONYMOUS_USER_COOKIE,
    ANONYMOUS_USER_COOKIE_MAX_AGE,
    DEFAULT_ADMIN_SESSION_TTL_SECONDS,
    DEFAULT_ADMIN_TOKEN,
    DEFAULT_PROXY_SECRET,
    USER_SESSION_COOKIE,
    USER_SESSION_REFRESH_SECONDS,
    load_environment_config as _bootstrap_load_environment_config,
    prepare_initial_runtime_paths as _bootstrap_prepare_initial_runtime_paths,
    prepare_output_dir as _bootstrap_prepare_output_dir,
    resolve_base_dir as _bootstrap_resolve_base_dir,
    resolve_database_path as _bootstrap_resolve_database_path,
)
from docxtool.web.runtime_state import (
    create_runtime_state as _runtime_state_create,
    create_sql_lock as _runtime_state_create_sql_lock,
)

_IMPORT_COMPATIBILITY = (
    os,
    json,
    time,
    shutil,
    OrderedDict,
    parse_qs,
    project_path,
    runtime_dir,
    default_database_path,
    package_version,
    parse_frontend_origin,
    resolve_cookie_secure,
    _parse_bool,
    _parse_int_env,
    DEFAULT_MONITOR_PAGE_SIZE,
)

BASE_DIR = _bootstrap_resolve_base_dir()
_SQL_LOCK = _runtime_state_create_sql_lock()
_DB_PATH = _bootstrap_resolve_database_path()
_WPS_SQL_LOCK = _runtime_state_create_sql_lock()
_WPS_DB_PATH = _wps_resolve_database_path()
_WPS_FORMAT_PROFILE = None
_RUNTIME_PATHS = _bootstrap_prepare_initial_runtime_paths(BASE_DIR, _DB_PATH)
LOG_DIR = _RUNTIME_PATHS.log_dir
RUNTIME_DIR = _RUNTIME_PATHS.runtime_dir
RUNTIME_TMP_DIR = _RUNTIME_PATHS.runtime_tmp_dir
UPLOAD_DIR = _RUNTIME_PATHS.upload_dir
USER_SESSION_MAX_AGE = 30 * 24 * 60 * 60
USER_SESSION_DAYS = 30

_WEAK_SECRETS = _SECRETS_WEAK_SECRETS







_first_query_value = _monitor_first_query_value
_clamp_int = _monitor_clamp_int


_monitor_query_from = _build_monitor_query_from
_normalize_monitor_query = _build_normalize_monitor_query
_where_sql = _monitor_where_sql
_page_count = _monitor_page_count





def _load_secret(name: str, default: str) -> str:
    """兼容旧私有入口，传入环境变量名和默认值，返回实际密钥字符串。"""
    return _secrets_load_secret(name, default)


_ENVIRONMENT = _bootstrap_load_environment_config(_load_secret)
PORT = _ENVIRONMENT.port
BIND_HOST = _ENVIRONMENT.bind_host
APP_VERSION = _ENVIRONMENT.app_version
BUILD_VERSION = _ENVIRONMENT.build_version
GIT_REVISION = _ENVIRONMENT.git_revision
STARTED_AT = _ENVIRONMENT.started_at
ADMIN_TOKEN = _ENVIRONMENT.admin_token
PROXY_SECRET = _ENVIRONMENT.proxy_secret
PRODUCTION_MODE = _ENVIRONMENT.production_mode
FRONTEND_ORIGIN = _ENVIRONMENT.frontend_origin
COOKIE_SECURE = _ENVIRONMENT.cookie_secure
ADMIN_CONSOLE_ORIGIN = _ENVIRONMENT.admin_console_origin
ADMIN_COOKIE_SECURE = _ENVIRONMENT.admin_cookie_secure
USER_SESSION_DAYS = _ENVIRONMENT.user_session_days
USER_SESSION_MAX_AGE = _ENVIRONMENT.user_session_max_age
MAX_SIZE = _ENVIRONMENT.max_size
UPLOAD_READ_TIMEOUT_SECONDS = _ENVIRONMENT.upload_read_timeout_seconds
UPLOAD_READ_CHUNK_SIZE = _ENVIRONMENT.upload_read_chunk_size
MAX_WORKERS = _ENVIRONMENT.max_workers
MAX_QUEUE = _ENVIRONMENT.max_queue
PROCESS_TIMEOUT = _ENVIRONMENT.process_timeout
RATE_WINDOW = _ENVIRONMENT.rate_window
FILE_RETENTION_POLICY = _ENVIRONMENT.file_retention_policy
FILE_TTL = _ENVIRONMENT.file_ttl
MAX_TASKS = _ENVIRONMENT.max_tasks
TASK_RETENTION_HOURS = _ENVIRONMENT.task_retention_hours
MAX_CACHED_TASKS = _ENVIRONMENT.max_cached_tasks
CLEANUP_INTERVAL_MINUTES = _ENVIRONMENT.cleanup_interval_minutes
DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS = _ENVIRONMENT.default_upload_limit_window_seconds
DEFAULT_UPLOAD_LIMIT_COUNT = _ENVIRONMENT.default_upload_limit_count
MAX_FORMAT_CONFIG_HEADER_BYTES = _ENVIRONMENT.max_format_config_header_bytes
MAX_FORMAT_CONFIG_JSON_BYTES = _ENVIRONMENT.max_format_config_json_bytes
MAX_DOCX_UNCOMPRESSED_BYTES = _ENVIRONMENT.max_docx_uncompressed_bytes
MAX_DOCX_FILE_COUNT = _ENVIRONMENT.max_docx_file_count
MAX_DOCX_XML_BYTES = _ENVIRONMENT.max_docx_xml_bytes
MAX_DOCX_MEDIA_BYTES = _ENVIRONMENT.max_docx_media_bytes
MAX_DOCX_COMPRESSION_RATIO = _ENVIRONMENT.max_docx_compression_ratio
TRUST_PROXY_HEADERS = _ENVIRONMENT.trust_proxy_headers
TRUSTED_PROXY_IPS = _ENVIRONMENT.trusted_proxy_ips


_RUNTIME_STATE = _runtime_state_create()
RATE_LIMIT = _RUNTIME_STATE.rate_limit
RATE_LOCK = _RUNTIME_STATE.rate_lock
AUTH_RATE_LIMIT = _RUNTIME_STATE.auth_rate_limit
TASKS = _RUNTIME_STATE.tasks
TASKS_LOCK = _RUNTIME_STATE.tasks_lock
TASK_QUEUE = _RUNTIME_STATE.task_queue
QUEUE_COND = _RUNTIME_STATE.queue_condition
WORKER_STATE = _RUNTIME_STATE.worker_state
WORKERS_LOCK = _RUNTIME_STATE.workers_lock
WORKER_THREADS = _RUNTIME_STATE.worker_threads

OUTPUT_DIR = _bootstrap_prepare_output_dir()










configure_logging(LOG_DIR, to_file=True)
logger = get_logger()
logging.getLogger("docx_tool").setLevel(logging.DEBUG)
for h in logging.getLogger("docx_tool").handlers:
    if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
        h.setLevel(logging.WARNING)







_is_ip = _client_is_ip




















_safe_file_identifier = _file_safe_file_identifier
_sanitize_internal_error_detail = _file_sanitize_internal_error_detail

















    # A valid upload remains available even when formatting fails, so users
    # and administrators can inspect the original document later.




def _cleaner_loop():
    """兼容旧私有入口：不传参数，运行永久保留策略下的后台维护循环。"""
    _maintenance_cleaner_loop(CLEANUP_INTERVAL_MINUTES)


threading.Thread(target=_cleaner_loop, daemon=True).start()

_error_payload = _request_error_payload
_cookie_value = _request_cookie_value









































_format_config_error = _format_config_error_impl


_upload_request_meta = _format_upload_request_meta
_processing_strategy_from_mode = _format_processing_strategy_from_mode



_admin_token_from = _request_admin_token_from_query
_admin_url = _request_admin_url






_route_path = _request_route_path
_prefixed_route_tail = _request_prefixed_route_tail
_prefixed_route_last_segment = _request_prefixed_route_last_segment
_json_dumps = _request_json_dumps
_parse_json_body = _request_parse_json_body

_normalize_template_name = _preset_normalize_template_name
_normalize_template_id = _preset_normalize_template_id


_preset_row_to_dict = _preset_row_to_dict_impl



















# ── 安全工具 ──

_is_safe_uuid = _file_is_safe_uuid
_sanitize_filename = _file_sanitize_filename
_safe_download_filename = _file_safe_download_filename
_content_disposition_filename = _file_content_disposition_filename



_html_escape = _request_html_escape
_redact_sensitive_log = _log_redact_sensitive_log

_split_ip_header = _client_split_ip_header



from docxtool.web.hooks import register_app_provider

register_app_provider(sys.modules[__name__])

from docxtool.web.compatibility import (
    cors_headers_for_request,
    _sql,
    _sql_init,
    _default_preset_config,
    _core_feature_config_defaults,
    _seed_default_presets,
    _now_local,
    log_sql,
    record_task_queued,
    get_sql_stats,
    _validate_secrets_or_exit,
    _startup_cleanup,
    _task_tmp_dir,
    _task_upload_dir,
    _task_upload_input_path,
    _cleanup_incomplete_upload,
    _cleanup_expired_tmp,
    _prune_task_cache,
    _recover_inflight_tasks_on_startup,
    _read_exact,
    _read_exact_to_file,
    _stream_file,
    _allow,
    _auth_rate_allow,
    _is_ip_banned,
    _ban_ip,
    _unban_ip,
    _banned_ips,
    _ip_activity,
    _ip_upload_count,
    _upload_limit_exceeded,
    _settings_get,
    _settings_set,
    _limit_settings,
    _save_limit_settings,
    _active_count,
    _queued_count,
    _task_load,
    _task_queue_info,
    _load_public_task_from_db,
    _public_task_state,
    _public_recognition_summary,
    _task_output_dir,
    _task_output_path,
    _ensure_path_within,
    _cleanup_output_path,
    _task_processing_options,
    _mark_task_processing,
    _mark_task_terminal,
    _enqueue_task,
    _task_process_body,
    _task_process_entry,
    _task_process_direct,
    _task_process_subprocess,
    _record_task_result,
    _worker_loop,
    _ensure_workers_started,
    _process_task,
    _cleanup_expired_outputs,
    _cleanup_expired_task_records,
    _session_cookie_settings,
    _anonymous_user_signing_key,
    _anonymous_user_signature,
    _create_anonymous_user,
    _parse_anonymous_user,
    _anonymous_user_cookie_header,
    _anonymous_user_cookie_clear_header,
    _anonymous_user_from_headers,
    _anonymous_template_origin_allowed,
    _user_session_hash,
    _user_cookie_header,
    _create_user_session,
    _user_session_from_headers,
    _delete_user_session,
    _principal,
    _auth_origin_allowed,
    _auth_csrf_allowed,
    _migrate_anonymous_owner,
    _migrate_anonymous_resources,
    _now_unix,
    _prune_expired_admin_sessions,
    _create_admin_session,
    _get_admin_session,
    _delete_admin_session,
    _legacy_admin_token_from,
    _admin_authorized,
    _admin_session_from_headers,
    _admin_request_context,
    _file_api_authorized,
    _gateway_request_authorized,
    _decode_format_config,
    _validate_requested_processing_mode,
    _admin_hidden_input,
    _csrf_hidden_input,
    _csrf_header_value,
    _admin_cookie_header,
    _validate_admin_csrf,
    _validate_template_config,
    _list_presets,
    _get_preset,
    _insert_preset,
    _update_preset,
    _delete_preset,
    _health_payload,
    _dir_writable,
    _database_ready,
    _ready_payload,
    _version_payload,
    _server_bind_address,
    _startup_urls,
    _monitor_url,
    _pager_html,
    _status_badge,
    _monitor_html,
    _ip_detail_html,
    _trusted_proxy_source,
    _compare_secret,
    _client_ip,
)

_COMPATIBILITY_FUNCTIONS = (
    cors_headers_for_request,
    _sql,
    _sql_init,
    _default_preset_config,
    _core_feature_config_defaults,
    _seed_default_presets,
    _now_local,
    log_sql,
    record_task_queued,
    get_sql_stats,
    _validate_secrets_or_exit,
    _startup_cleanup,
    _task_tmp_dir,
    _task_upload_dir,
    _task_upload_input_path,
    _cleanup_incomplete_upload,
    _cleanup_expired_tmp,
    _prune_task_cache,
    _recover_inflight_tasks_on_startup,
    _read_exact,
    _read_exact_to_file,
    _stream_file,
    _allow,
    _auth_rate_allow,
    _is_ip_banned,
    _ban_ip,
    _unban_ip,
    _banned_ips,
    _ip_activity,
    _ip_upload_count,
    _upload_limit_exceeded,
    _settings_get,
    _settings_set,
    _limit_settings,
    _save_limit_settings,
    _active_count,
    _queued_count,
    _task_load,
    _task_queue_info,
    _load_public_task_from_db,
    _public_task_state,
    _public_recognition_summary,
    _task_output_dir,
    _task_output_path,
    _ensure_path_within,
    _cleanup_output_path,
    _task_processing_options,
    _mark_task_processing,
    _mark_task_terminal,
    _enqueue_task,
    _task_process_body,
    _task_process_entry,
    _task_process_direct,
    _task_process_subprocess,
    _record_task_result,
    _worker_loop,
    _ensure_workers_started,
    _process_task,
    _cleanup_expired_outputs,
    _cleanup_expired_task_records,
    _session_cookie_settings,
    _anonymous_user_signing_key,
    _anonymous_user_signature,
    _create_anonymous_user,
    _parse_anonymous_user,
    _anonymous_user_cookie_header,
    _anonymous_user_cookie_clear_header,
    _anonymous_user_from_headers,
    _anonymous_template_origin_allowed,
    _user_session_hash,
    _user_cookie_header,
    _create_user_session,
    _user_session_from_headers,
    _delete_user_session,
    _principal,
    _auth_origin_allowed,
    _auth_csrf_allowed,
    _migrate_anonymous_owner,
    _migrate_anonymous_resources,
    _now_unix,
    _prune_expired_admin_sessions,
    _create_admin_session,
    _get_admin_session,
    _delete_admin_session,
    _legacy_admin_token_from,
    _admin_authorized,
    _admin_session_from_headers,
    _admin_request_context,
    _file_api_authorized,
    _gateway_request_authorized,
    _decode_format_config,
    _validate_requested_processing_mode,
    _admin_hidden_input,
    _csrf_hidden_input,
    _csrf_header_value,
    _admin_cookie_header,
    _validate_admin_csrf,
    _validate_template_config,
    _list_presets,
    _get_preset,
    _insert_preset,
    _update_preset,
    _delete_preset,
    _health_payload,
    _dir_writable,
    _database_ready,
    _ready_payload,
    _version_payload,
    _server_bind_address,
    _startup_urls,
    _monitor_url,
    _pager_html,
    _status_badge,
    _monitor_html,
    _ip_detail_html,
    _trusted_proxy_source,
    _compare_secret,
    _client_ip,
)


_web_sql_init = _sql_init
_web_ready_payload = _ready_payload


def _wps_sql():
    """返回 WPS 插件专用 SQLite 连接。"""
    return _wps_database_connect(_WPS_DB_PATH)


def _sql_init():
    """初始化相互隔离的网页业务库和 WPS 插件库。"""
    global _WPS_FORMAT_PROFILE
    try:
        _wps_require_separate_database_paths(_DB_PATH, _WPS_DB_PATH)
    except RuntimeError:
        logger.error(
            "wps.database.initialize.failed | error_code=WPS_DATABASE_PATH_CONFLICT"
        )
        raise
    _web_sql_init()
    try:
        _wps_initialize_database(_wps_sql, _WPS_SQL_LOCK)
    except Exception:
        logger.exception("wps.database.initialize.failed")
        raise
    logger.info(
        "wps.database.initialize.completed"
    )
    try:
        _WPS_FORMAT_PROFILE = _wps_load_active_format_profile()
    except Exception:
        logger.exception("wps.format_config.failed")
        raise
    logger.info(
        "wps.format_config.loaded | config_version=%s",
        _WPS_FORMAT_PROFILE["config_version"],
    )


def _ready_payload():
    """返回包含两个数据库状态的服务 readiness。"""
    payload = _web_ready_payload()
    checks = dict(payload.get("checks", {}))
    checks["wps_database"] = _wps_database_ready_check(_wps_sql, _WPS_SQL_LOCK)
    checks["wps_format_config"] = isinstance(_WPS_FORMAT_PROFILE, dict)
    return {"ok": all(checks.values()), "checks": checks}


from docxtool.web.handler import Handler


def _public_startup_urls() -> dict:
    """返回启动日志使用的唯一 Pages 前端和管理后台地址。"""
    return _build_public_startup_urls(FRONTEND_ORIGIN)


def main():
    """兼容旧启动入口，无需传入数据，完成 Web 服务启动编排。"""
    return _runtime_run_http_service(
        argv=sys.argv,
        server_class=ThreadingHTTPServer,
        handler_class=Handler,
        bind_address=_server_bind_address,
        startup_urls=_startup_urls,
        public_urls=_public_startup_urls,
        validate_secrets=_validate_secrets_or_exit,
        startup_cleanup=_startup_cleanup,
        init_database=_sql_init,
        recover_inflight_tasks=_recover_inflight_tasks_on_startup,
        ensure_workers_started=_ensure_workers_started,
        max_workers=MAX_WORKERS,
        max_queue=MAX_QUEUE,
        max_size=MAX_SIZE,
        rate_window=RATE_WINDOW,
        production_mode=PRODUCTION_MODE,
    )

if __name__ == "__main__":
    main()
