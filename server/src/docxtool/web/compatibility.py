"""Dynamic legacy-function facade used by ``docxtool.web.app``."""
# ruff: noqa: F821

from __future__ import annotations

import functools
import time
from docxtool.web.hooks import sync_app_namespace


def _sync_from_app() -> None:
    sync_app_namespace(globals())


def _dynamic_compatibility(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        _sync_from_app()
        return function(*args, **kwargs)

    return wrapped


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

def _now_local() -> str:
    """兼容旧私有入口，无需传入数据，返回本地时间字符串。"""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

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

def _validate_secrets_or_exit() -> None:
    """兼容旧私有入口，无需传入数据，校验当前 Web 启动密钥。"""
    _secrets_validate_required(ADMIN_TOKEN, PROXY_SECRET, _WEAK_SECRETS)

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

def _read_exact(rfile, length: int, timeout: int = 10) -> bytes:
    """兼容旧入口：从请求流读取指定字节数并返回 bytes。"""
    return _stream_read_exact(rfile, length, timeout)

def _read_exact_to_file(rfile, path: str, length: int, timeout: int = 10, chunk_size: int = 64 * 1024) -> int:
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

def _cleanup_expired_outputs(now: float = None) -> dict:
    """兼容旧入口：生成文件永久保留，不按时间清理。"""
    return _task_paths_cleanup_expired_outputs(now)

def _cleanup_expired_task_records(now: float = None) -> dict:
    """兼容旧入口：任务记录永久保留，不按时间清理。"""
    return _task_paths_cleanup_expired_task_records(now)

def _session_cookie_settings() -> str:
    """兼容旧入口：根据当前全局配置返回管理员会话 Cookie 模板。"""
    return _request_admin_session_cookie_settings(
        ADMIN_SESSION_COOKIE,
        DEFAULT_ADMIN_SESSION_TTL_SECONDS,
        secure=ADMIN_COOKIE_SECURE,
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

def _gateway_request_authorized(headers, path: str) -> bool:
    """兼容旧入口：校验请求是否经公共网关进入生产 Backend。"""
    return _route_gateway_request_authorized(
        headers,
        path,
        production_mode=PRODUCTION_MODE,
        proxy_secret=PROXY_SECRET,
        compare_secret=_compare_secret,
    )

def _decode_format_config(headers) -> dict:
    """兼容旧入口：解码请求头中的格式配置并返回已验证配置。"""
    return _format_decode_format_config(
        headers,
        max_header_bytes=MAX_FORMAT_CONFIG_HEADER_BYTES,
        max_json_bytes=MAX_FORMAT_CONFIG_JSON_BYTES,
    )

def _validate_requested_processing_mode(format_config: dict | None, request_meta: dict) -> None:
    """兼容旧入口：校验 header 处理模式与格式配置并写入 request_meta。"""
    _format_validate_requested_processing_mode(format_config, request_meta)

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

def _validate_template_config(config_obj: dict) -> dict:
    """兼容旧入口：传入模板配置对象，返回归一化后的可持久化配置。"""
    return _preset_validate_template_config(config_obj, core_feature_defaults=_core_feature_config_defaults())

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

def _client_ip(headers, client_address) -> str:
    """兼容旧入口：从可信代理头和 socket 地址解析真实客户端 IP。"""
    return _client_ip_from_headers(
        headers,
        client_address,
        trust_proxy_headers=TRUST_PROXY_HEADERS,
        trusted_proxy_ips=TRUSTED_PROXY_IPS,
    )

COMPATIBILITY_EXPORTS = (
    "cors_headers_for_request",
    "_sql",
    "_sql_init",
    "_default_preset_config",
    "_core_feature_config_defaults",
    "_seed_default_presets",
    "_now_local",
    "log_sql",
    "record_task_queued",
    "get_sql_stats",
    "_validate_secrets_or_exit",
    "_startup_cleanup",
    "_task_tmp_dir",
    "_task_upload_dir",
    "_task_upload_input_path",
    "_cleanup_incomplete_upload",
    "_cleanup_expired_tmp",
    "_prune_task_cache",
    "_recover_inflight_tasks_on_startup",
    "_read_exact",
    "_read_exact_to_file",
    "_stream_file",
    "_allow",
    "_auth_rate_allow",
    "_is_ip_banned",
    "_ban_ip",
    "_unban_ip",
    "_banned_ips",
    "_ip_activity",
    "_ip_upload_count",
    "_upload_limit_exceeded",
    "_settings_get",
    "_settings_set",
    "_limit_settings",
    "_save_limit_settings",
    "_active_count",
    "_queued_count",
    "_task_load",
    "_task_queue_info",
    "_load_public_task_from_db",
    "_public_task_state",
    "_public_recognition_summary",
    "_task_output_dir",
    "_task_output_path",
    "_ensure_path_within",
    "_cleanup_output_path",
    "_task_processing_options",
    "_mark_task_processing",
    "_mark_task_terminal",
    "_enqueue_task",
    "_task_process_body",
    "_task_process_entry",
    "_task_process_direct",
    "_task_process_subprocess",
    "_record_task_result",
    "_worker_loop",
    "_ensure_workers_started",
    "_process_task",
    "_cleanup_expired_outputs",
    "_cleanup_expired_task_records",
    "_session_cookie_settings",
    "_anonymous_user_signing_key",
    "_anonymous_user_signature",
    "_create_anonymous_user",
    "_parse_anonymous_user",
    "_anonymous_user_cookie_header",
    "_anonymous_user_cookie_clear_header",
    "_anonymous_user_from_headers",
    "_anonymous_template_origin_allowed",
    "_user_session_hash",
    "_user_cookie_header",
    "_create_user_session",
    "_user_session_from_headers",
    "_delete_user_session",
    "_principal",
    "_auth_origin_allowed",
    "_auth_csrf_allowed",
    "_migrate_anonymous_owner",
    "_migrate_anonymous_resources",
    "_now_unix",
    "_prune_expired_admin_sessions",
    "_create_admin_session",
    "_get_admin_session",
    "_delete_admin_session",
    "_legacy_admin_token_from",
    "_admin_authorized",
    "_admin_session_from_headers",
    "_admin_request_context",
    "_file_api_authorized",
    "_gateway_request_authorized",
    "_decode_format_config",
    "_validate_requested_processing_mode",
    "_admin_hidden_input",
    "_csrf_hidden_input",
    "_csrf_header_value",
    "_admin_cookie_header",
    "_validate_admin_csrf",
    "_validate_template_config",
    "_list_presets",
    "_get_preset",
    "_insert_preset",
    "_update_preset",
    "_delete_preset",
    "_health_payload",
    "_dir_writable",
    "_database_ready",
    "_ready_payload",
    "_version_payload",
    "_server_bind_address",
    "_startup_urls",
    "_monitor_url",
    "_pager_html",
    "_status_badge",
    "_monitor_html",
    "_ip_detail_html",
    "_trusted_proxy_source",
    "_compare_secret",
    "_client_ip",
)

for _export_name in COMPATIBILITY_EXPORTS:
    globals()[_export_name] = _dynamic_compatibility(globals()[_export_name])
