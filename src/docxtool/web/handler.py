"""HTTP handler implementation with dynamic access to the legacy app facade."""
# ruff: noqa: F821

from __future__ import annotations

import functools
import sys


_APP_MODULE = sys.modules["docxtool.web.app"]


def _sync_from_app() -> None:
    for name, value in vars(_APP_MODULE).items():
        if not name.startswith("__"):
            globals()[name] = value


def _dynamic_method(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        _sync_from_app()
        return function(*args, **kwargs)

    return wrapped


_sync_from_app()


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
        _handler_lifecycle_dispatch_http_method(
            self, route_path=_route_path, dispatch=_dispatch_get
        )

    def do_POST(self):
        """无需传入数据，解析当前路径并分派 POST 路由。"""
        _handler_lifecycle_dispatch_http_method(
            self, route_path=_route_path, dispatch=_dispatch_post
        )

    def do_PUT(self):
        """无需传入数据，解析当前路径并分派 PUT 路由。"""
        _handler_lifecycle_dispatch_http_method(
            self, route_path=_route_path, dispatch=_dispatch_put
        )

    def do_DELETE(self):
        """无需传入数据，解析当前路径并分派 DELETE 路由。"""
        _handler_lifecycle_dispatch_http_method(
            self, route_path=_route_path, dispatch=_dispatch_delete
        )

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
        _protected_route_handle_admin(
            parsed, require_admin=self._require_admin, action=self._handle_ip_detail
        )

    def _handle_upload_route(self):
        """无需传入数据，通过文件 API 鉴权后处理上传请求。"""
        _protected_route_handle_file_api(
            require_file_api=self._require_file_api, action=self._handle_upload_raw
        )

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
        _protected_route_handle_admin_post(
            parsed, require_admin_post=self._require_admin_post, action=self._handle_ban
        )

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

    def _json_error(
        self,
        code: str,
        message: str,
        status: int,
        *,
        field: str = "",
        reason: str = "",
        retry_after: int = 0,
    ):
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


for _method_name, _method in tuple(vars(Handler).items()):
    if callable(_method):
        setattr(Handler, _method_name, _dynamic_method(_method))
