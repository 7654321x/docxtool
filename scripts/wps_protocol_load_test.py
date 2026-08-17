"""Run a bounded WPS public-protocol load test through Cloudflare Pages.

The test intentionally exercises only the server-side WPS protocol:
registration, session snapshot, heartbeat, format authorization, result
reporting, idempotent retries, and logout. It does not invoke WPS itself or
claim to execute a real document-formatting operation.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import re
import secrets
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, DefaultDict, Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_VERSION = "wps-api-v1"
APP_VERSION = "loadtest-1.0"
SYNTHETIC_RESULT_ERROR_CODE = "WPS_LOAD_TEST_SYNTHETIC"
SYNTHETIC_DOCUMENT_NAME = "load-test.docx"
DEFAULT_USERS = 2
DEFAULT_FORMAT_REQUESTS_PER_USER = 1
DEFAULT_CONCURRENCY = 2
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
MAX_PUBLIC_USERS = 4
MAX_CONCURRENCY = 4
MAX_FORMAT_REQUESTS_PER_USER = 3
LOOPBACK_HOSTS = frozenset(("localhost", "127.0.0.1", "::1"))
ACCOUNT_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{3,12}$")


class WpsLoadTestConfigurationError(ValueError):
    """Raised for invalid or insufficiently authorized test settings."""


@dataclass(frozen=True)
class Target:
    """A validated WPS API origin."""

    origin: str
    is_loopback: bool

    def url(self, path: str) -> str:
        return self.origin + "/" + path.lstrip("/")


@dataclass(frozen=True)
class ScenarioSettings:
    """The intentionally bounded WPS protocol workload."""

    users: int
    format_requests_per_user: int
    concurrency: int
    request_timeout_seconds: float
    account_prefix: str


@dataclass
class HttpResponse:
    """A JSON HTTP response without raw transport or credential details."""

    status: int
    payload: Dict[str, Any]
    error_code: str = ""


@dataclass
class OperationOutcome:
    """One protocol operation's observable outcome."""

    user_index: int
    stage: str
    http_status: int
    success: bool
    duration_ms: int
    error_code: str
    config_version: str = ""


@dataclass(frozen=True)
class VirtualUser:
    """An in-memory synthetic account session; never serialize this object."""

    index: int
    username: str
    user_id: str
    token: str
    device_id: str


class _NoRedirect(HTTPRedirectHandler):
    """Do not forward bearer credentials to a redirect target."""

    def redirect_request(self, *_args, **_kwargs):  # type: ignore[override]
        return None


class WpsHttpClient:
    """Small standard-library JSON client for one WPS public API interaction."""

    def __init__(self, target: Target) -> None:
        self._target = target
        self._opener = build_opener(_NoRedirect())

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        token: str = "",
        request_id: str = "",
        timeout_seconds: float,
    ) -> HttpResponse:
        body = None
        headers = {
            "Accept": "application/json",
            "Cache-Control": "no-store",
            "User-Agent": "DocxTool-WpsProtocolLoadTest/1.0 (authorized)",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        if token:
            headers["Authorization"] = "Bearer %s" % token
        if request_id:
            headers["X-DocxTool-Request-Id"] = request_id
        request = Request(
            self._target.url(path), data=body, headers=headers, method=method
        )
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                decoded, decode_error = _decode_response(response.read())
                return HttpResponse(response.getcode(), decoded, decode_error)
        except HTTPError as error:
            decoded, decode_error = _decode_response(error.read())
            return HttpResponse(
                error.code,
                decoded,
                decode_error or _error_code(decoded, "HTTP_%s" % error.code),
            )
        except (URLError, OSError):
            return HttpResponse(0, {}, "WPS_LOAD_TEST_NETWORK_FAILED")


def _decode_response(raw: bytes) -> Tuple[Dict[str, Any], str]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, "WPS_LOAD_TEST_RESPONSE_JSON_INVALID"
    if not isinstance(value, dict):
        return {}, "WPS_LOAD_TEST_RESPONSE_JSON_INVALID"
    return value, ""


def _error_code(payload: Dict[str, Any], fallback: str) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        value = error.get("code")
        if isinstance(value, str) and value:
            return value
    for key in ("code", "error_code"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return fallback


def _success_data(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    if payload.get("ok") is not True:
        return None, _error_code(payload, "WPS_LOAD_TEST_RESPONSE_REJECTED")
    if payload.get("api_version") != API_VERSION:
        return None, "WPS_LOAD_TEST_API_VERSION_INVALID"
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, "WPS_LOAD_TEST_RESPONSE_DATA_INVALID"
    return data, ""


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_snapshot(
    data: Dict[str, Any],
    *,
    include_token: bool,
    expected_username: str = "",
    expected_user_id: str = "",
    expected_device_id: str = "",
) -> str:
    user = data.get("user")
    device = data.get("device")
    if not isinstance(user, dict) or not isinstance(device, dict):
        return "WPS_LOAD_TEST_SNAPSHOT_INVALID"
    for value in (
        user.get("id"),
        user.get("username"),
        user.get("status"),
        device.get("id"),
        device.get("status"),
        data.get("config_version"),
    ):
        if not _is_text(value):
            return "WPS_LOAD_TEST_SNAPSHOT_INVALID"
    interval = data.get("heartbeat_interval_seconds")
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        return "WPS_LOAD_TEST_SNAPSHOT_INVALID"
    if include_token:
        token = data.get("session_token")
        if not isinstance(token, str) or len(token) != 43:
            return "WPS_LOAD_TEST_SESSION_TOKEN_INVALID"
    elif "session_token" in data:
        return "WPS_LOAD_TEST_SESSION_TOKEN_LEAKED"
    if expected_username and user.get("username") != expected_username:
        return "WPS_LOAD_TEST_RESPONSE_IDENTITY_MISMATCH"
    if expected_user_id and user.get("id") != expected_user_id:
        return "WPS_LOAD_TEST_RESPONSE_IDENTITY_MISMATCH"
    if expected_device_id and device.get("id") != expected_device_id:
        return "WPS_LOAD_TEST_RESPONSE_IDENTITY_MISMATCH"
    return ""


def _validate_heartbeat(data: Dict[str, Any]) -> str:
    if data.get("account_status") != "active" or data.get("device_status") != "active":
        return "WPS_LOAD_TEST_HEARTBEAT_STATUS_INVALID"
    interval = data.get("heartbeat_interval_seconds")
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        return "WPS_LOAD_TEST_HEARTBEAT_INVALID"
    if not _is_text(data.get("config_version")):
        return "WPS_LOAD_TEST_HEARTBEAT_INVALID"
    return ""


def _validate_authorization(
    data: Dict[str, Any], request_id: str, *, expected_reused: bool
) -> str:
    if data.get("allowed") is not True:
        return "WPS_LOAD_TEST_AUTHORIZATION_REJECTED"
    if data.get("reused") is not expected_reused:
        return "WPS_LOAD_TEST_AUTHORIZATION_IDEMPOTENCY_INVALID"
    if data.get("request_id") != request_id or data.get("request_status") != "authorized":
        return "WPS_LOAD_TEST_AUTHORIZATION_RESPONSE_INVALID"
    if not _is_text(data.get("config_version")) or not isinstance(
        data.get("format_config"), dict
    ):
        return "WPS_LOAD_TEST_AUTHORIZATION_RESPONSE_INVALID"
    return ""


def _validate_result(
    data: Dict[str, Any], request_id: str, *, expected_reused: bool
) -> str:
    if data.get("request_id") != request_id or data.get("status") != "failed":
        return "WPS_LOAD_TEST_RESULT_RESPONSE_INVALID"
    if data.get("reused") is not expected_reused:
        return "WPS_LOAD_TEST_RESULT_IDEMPOTENCY_INVALID"
    return ""


def _validate_logout(data: Dict[str, Any]) -> str:
    return "" if data == {"logged_out": True} else "WPS_LOAD_TEST_LOGOUT_INVALID"


def _response_request_id_error(payload: Dict[str, Any], request_id: str) -> str:
    if payload.get("request_id") != request_id:
        return "WPS_LOAD_TEST_CORRELATION_ID_MISMATCH"
    return ""


def _set_config_version(
    outcome: OperationOutcome, data: Optional[Dict[str, Any]]
) -> None:
    if data and isinstance(data.get("config_version"), str):
        outcome.config_version = data["config_version"]


def parse_target(value: str, *, confirm_production_load: bool) -> Target:
    """Accept only a root HTTP(S) origin and require confirmation for public hosts."""
    try:
        parsed = urlsplit(value.strip())
        parsed.port
    except ValueError as error:
        raise WpsLoadTestConfigurationError("WPS 压测地址端口无效。") from error
    if not parsed.scheme or not parsed.netloc or not parsed.hostname:
        raise WpsLoadTestConfigurationError("WPS 压测地址必须是完整的 HTTP(S) 根地址。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WpsLoadTestConfigurationError(
            "WPS 压测地址不能包含账号、密码、query 或 fragment。"
        )
    if parsed.path not in ("", "/"):
        raise WpsLoadTestConfigurationError("WPS 压测地址只能填写站点根地址。")
    host = parsed.hostname.lower()
    is_loopback = host in LOOPBACK_HOSTS
    if parsed.scheme != "https" and not is_loopback:
        raise WpsLoadTestConfigurationError("公网 WPS 压测地址必须使用 HTTPS。")
    if not is_loopback and not confirm_production_load:
        raise WpsLoadTestConfigurationError(
            "公网目标需要 --confirm-production-load 明确授权。"
        )
    return Target("%s://%s" % (parsed.scheme, parsed.netloc), is_loopback)


def validate_settings(
    settings: ScenarioSettings,
    target: Target,
    *,
    confirm_test_account_creation: bool,
) -> None:
    """Keep public registration below the deployed per-IP safety threshold."""
    if settings.users < 1 or settings.users > MAX_PUBLIC_USERS:
        raise WpsLoadTestConfigurationError(
            "测试账号数必须在 1 到 %s 之间。" % MAX_PUBLIC_USERS
        )
    if (
        settings.format_requests_per_user < 1
        or settings.format_requests_per_user > MAX_FORMAT_REQUESTS_PER_USER
    ):
        raise WpsLoadTestConfigurationError(
            "每账号排版请求数必须在 1 到 %s 之间。"
            % MAX_FORMAT_REQUESTS_PER_USER
        )
    if settings.concurrency < 1 or settings.concurrency > MAX_CONCURRENCY:
        raise WpsLoadTestConfigurationError(
            "并发数必须在 1 到 %s 之间。" % MAX_CONCURRENCY
        )
    if settings.request_timeout_seconds < 1:
        raise WpsLoadTestConfigurationError("单次 HTTP 超时至少为 1 秒。")
    if not ACCOUNT_PREFIX_RE.fullmatch(settings.account_prefix):
        raise WpsLoadTestConfigurationError(
            "测试账号前缀必须以字母开头，且只能包含 4 至 13 位字母或数字。"
        )
    if not target.is_loopback and not confirm_test_account_creation:
        raise WpsLoadTestConfigurationError(
            "公网测试会创建账号，需要 --confirm-test-account-creation 明确授权。"
        )


def _operation(
    *,
    client: WpsHttpClient,
    user_index: int,
    stage: str,
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]],
    token: str,
    request_id: str,
    timeout_seconds: float,
    expected_status: int,
    validator: Callable[[Dict[str, Any]], str],
) -> Tuple[OperationOutcome, Optional[Dict[str, Any]]]:
    started_at = time.monotonic()
    response = client.request_json(
        method,
        path,
        payload=payload,
        token=token,
        request_id=request_id,
        timeout_seconds=timeout_seconds,
    )
    duration_ms = round((time.monotonic() - started_at) * 1000)
    if response.status != expected_status:
        return (
            OperationOutcome(
                user_index,
                stage,
                response.status,
                False,
                duration_ms,
                response.error_code
                or _error_code(response.payload, "WPS_LOAD_TEST_HTTP_FAILED"),
            ),
            None,
        )
    correlation_error = _response_request_id_error(response.payload, request_id)
    if correlation_error:
        return (
            OperationOutcome(
                user_index,
                stage,
                response.status,
                False,
                duration_ms,
                correlation_error,
            ),
            None,
        )
    data, envelope_error = _success_data(response.payload)
    if data is None:
        return (
            OperationOutcome(
                user_index,
                stage,
                response.status,
                False,
                duration_ms,
                envelope_error,
            ),
            None,
        )
    validation_error = validator(data)
    if validation_error:
        return (
            OperationOutcome(
                user_index,
                stage,
                response.status,
                False,
                duration_ms,
                validation_error,
            ),
            None,
        )
    return (
        OperationOutcome(
            user_index,
            stage,
            response.status,
            True,
            duration_ms,
            "",
        ),
        data,
    )


def _expected_error_operation(
    *,
    client: WpsHttpClient,
    user_index: int,
    stage: str,
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]],
    token: str,
    request_id: str,
    timeout_seconds: float,
    expected_status: int,
    expected_error_code: str,
) -> OperationOutcome:
    """Treat one required rejection as a successful protocol boundary check."""
    started_at = time.monotonic()
    response = client.request_json(
        method,
        path,
        payload=payload,
        token=token,
        request_id=request_id,
        timeout_seconds=timeout_seconds,
    )
    duration_ms = round((time.monotonic() - started_at) * 1000)
    actual_error_code = _error_code(response.payload, "WPS_LOAD_TEST_ERROR_RESPONSE_INVALID")
    if response.status != expected_status:
        return OperationOutcome(
            user_index,
            stage,
            response.status,
            False,
            duration_ms,
            actual_error_code,
        )
    correlation_error = _response_request_id_error(response.payload, request_id)
    if correlation_error:
        return OperationOutcome(
            user_index,
            stage,
            response.status,
            False,
            duration_ms,
            correlation_error,
        )
    if response.payload.get("ok") is not False or actual_error_code != expected_error_code:
        return OperationOutcome(
            user_index,
            stage,
            response.status,
            False,
            duration_ms,
            actual_error_code,
        )
    return OperationOutcome(user_index, stage, response.status, True, duration_ms, "")


def _request_id(run_label: str, user_index: int, stage: str, ordinal: int) -> str:
    return "load-%s-u%s-%s-%s-%s" % (
        run_label,
        user_index,
        stage,
        ordinal,
        secrets.token_hex(3),
    )


def _register_user(
    target: Target, settings: ScenarioSettings, run_label: str, user_index: int
) -> Tuple[Optional[VirtualUser], List[OperationOutcome]]:
    client = WpsHttpClient(target)
    username = "%s%02d" % (run_label, user_index)
    payload = {
        "username": username,
        "password": "LoadA1%s" % secrets.token_hex(12),
        "device": {
            "device_key": "wps-load-%s-%s-%s"
            % (run_label, user_index, secrets.token_hex(6)),
            "device_name": "DocxTool Load Test %s" % user_index,
            "platform": "windows",
            "app_version": APP_VERSION,
        },
    }
    request_id = _request_id(run_label, user_index, "register", 0)
    outcome, data = _operation(
        client=client,
        user_index=user_index,
        stage="register",
        method="POST",
        path="/wps-api/v1/auth/register",
        payload=payload,
        token="",
        request_id=request_id,
        timeout_seconds=settings.request_timeout_seconds,
        expected_status=201,
        validator=lambda value: _validate_snapshot(
            value, include_token=True, expected_username=username
        ),
    )
    if not outcome.success or data is None:
        return None, [outcome]
    _set_config_version(outcome, data)
    token = data.get("session_token")
    user = data.get("user")
    device = data.get("device")
    user_id = user.get("id") if isinstance(user, dict) else ""
    device_id = device.get("id") if isinstance(device, dict) else ""
    if (
        not isinstance(token, str)
        or not _is_text(user_id)
        or not _is_text(device_id)
    ):
        outcome.success = False
        outcome.error_code = "WPS_LOAD_TEST_SESSION_CONTEXT_INVALID"
        return None, [outcome]
    return (
        VirtualUser(
            user_index,
            username,
            str(user_id),
            token,
            str(device_id),
        ),
        [outcome],
    )


def _run_format_sequence(
    client: WpsHttpClient,
    user: VirtualUser,
    settings: ScenarioSettings,
    run_label: str,
    ordinal: int,
) -> List[OperationOutcome]:
    outcomes: List[OperationOutcome] = []
    request_id = _request_id(run_label, user.index, "format", ordinal)
    authorize_payload = {
        "request_id": request_id,
        "command": "apply",
        "app_version": APP_VERSION,
    }
    authorize, data = _operation(
        client=client,
        user_index=user.index,
        stage="format_authorize",
        method="POST",
        path="/wps-api/v1/format/authorize",
        payload=authorize_payload,
        token=user.token,
        request_id=request_id,
        timeout_seconds=settings.request_timeout_seconds,
        expected_status=200,
        validator=lambda value: _validate_authorization(
            value, request_id, expected_reused=False
        ),
    )
    _set_config_version(authorize, data)
    outcomes.append(authorize)
    if not authorize.success:
        return outcomes
    authorize_retry, retry_data = _operation(
        client=client,
        user_index=user.index,
        stage="format_authorize_retry",
        method="POST",
        path="/wps-api/v1/format/authorize",
        payload=authorize_payload,
        token=user.token,
        request_id=request_id,
        timeout_seconds=settings.request_timeout_seconds,
        expected_status=200,
        validator=lambda value: _validate_authorization(
            value, request_id, expected_reused=True
        ),
    )
    _set_config_version(authorize_retry, retry_data)
    outcomes.append(authorize_retry)
    if not authorize_retry.success:
        return outcomes

    result_payload = {
        "request_id": request_id,
        "status": "failed",
        "duration_ms": 1,
        "error_code": SYNTHETIC_RESULT_ERROR_CODE,
        "document_name": SYNTHETIC_DOCUMENT_NAME,
        "app_version": APP_VERSION,
    }
    result, _ = _operation(
        client=client,
        user_index=user.index,
        stage="format_result",
        method="POST",
        path="/wps-api/v1/format/result",
        payload=result_payload,
        token=user.token,
        request_id=request_id,
        timeout_seconds=settings.request_timeout_seconds,
        expected_status=200,
        validator=lambda value: _validate_result(
            value, request_id, expected_reused=False
        ),
    )
    outcomes.append(result)
    if not result.success:
        return outcomes
    result_retry, _ = _operation(
        client=client,
        user_index=user.index,
        stage="format_result_retry",
        method="POST",
        path="/wps-api/v1/format/result",
        payload=result_payload,
        token=user.token,
        request_id=request_id,
        timeout_seconds=settings.request_timeout_seconds,
        expected_status=200,
        validator=lambda value: _validate_result(
            value, request_id, expected_reused=True
        ),
    )
    outcomes.append(result_retry)
    return outcomes


def _run_user_workflow(
    target: Target, settings: ScenarioSettings, run_label: str, user: VirtualUser
) -> List[OperationOutcome]:
    """Run one active user through session checks and bounded format writes."""
    client = WpsHttpClient(target)
    outcomes: List[OperationOutcome] = []
    me, data = _operation(
        client=client,
        user_index=user.index,
        stage="auth_me",
        method="GET",
        path="/wps-api/v1/auth/me",
        payload=None,
        token=user.token,
        request_id=_request_id(run_label, user.index, "me", 0),
        timeout_seconds=settings.request_timeout_seconds,
        expected_status=200,
        validator=lambda value: _validate_snapshot(
            value,
            include_token=False,
            expected_username=user.username,
            expected_user_id=user.user_id,
            expected_device_id=user.device_id,
        ),
    )
    _set_config_version(me, data)
    outcomes.append(me)
    if not me.success:
        return outcomes
    heartbeat, data = _operation(
        client=client,
        user_index=user.index,
        stage="heartbeat",
        method="POST",
        path="/wps-api/v1/heartbeat",
        payload={"device_id": user.device_id, "app_version": APP_VERSION},
        token=user.token,
        request_id=_request_id(run_label, user.index, "heartbeat", 0),
        timeout_seconds=settings.request_timeout_seconds,
        expected_status=200,
        validator=_validate_heartbeat,
    )
    _set_config_version(heartbeat, data)
    outcomes.append(heartbeat)
    if not heartbeat.success:
        return outcomes
    for ordinal in range(1, settings.format_requests_per_user + 1):
        sequence = _run_format_sequence(client, user, settings, run_label, ordinal)
        outcomes.extend(sequence)
        if not all(item.success for item in sequence):
            return outcomes
    return outcomes


def _run_cross_account_request_isolation(
    target: Target,
    settings: ScenarioSettings,
    run_label: str,
    owner: VirtualUser,
    other: VirtualUser,
) -> List[OperationOutcome]:
    """Verify that another account cannot reuse the owner's format request ID."""
    client = WpsHttpClient(target)
    outcomes: List[OperationOutcome] = []
    request_id = _request_id(run_label, 0, "cross-account", 0)
    authorize_payload = {
        "request_id": request_id,
        "command": "apply",
        "app_version": APP_VERSION,
    }
    owner_authorize, data = _operation(
        client=client,
        user_index=owner.index,
        stage="cross_account_authorize",
        method="POST",
        path="/wps-api/v1/format/authorize",
        payload=authorize_payload,
        token=owner.token,
        request_id=request_id,
        timeout_seconds=settings.request_timeout_seconds,
        expected_status=200,
        validator=lambda value: _validate_authorization(
            value, request_id, expected_reused=False
        ),
    )
    _set_config_version(owner_authorize, data)
    outcomes.append(owner_authorize)
    if not owner_authorize.success:
        return outcomes
    rejected = _expected_error_operation(
        client=client,
        user_index=other.index,
        stage="cross_account_request_isolation",
        method="POST",
        path="/wps-api/v1/format/authorize",
        payload=authorize_payload,
        token=other.token,
        request_id=request_id,
        timeout_seconds=settings.request_timeout_seconds,
        expected_status=409,
        expected_error_code="REQUEST_ID_CONFLICT",
    )
    outcomes.append(rejected)
    if not rejected.success:
        return outcomes
    result_payload = {
        "request_id": request_id,
        "status": "failed",
        "duration_ms": 1,
        "error_code": SYNTHETIC_RESULT_ERROR_CODE,
        "document_name": SYNTHETIC_DOCUMENT_NAME,
        "app_version": APP_VERSION,
    }
    cleanup, _ = _operation(
        client=client,
        user_index=owner.index,
        stage="cross_account_result_cleanup",
        method="POST",
        path="/wps-api/v1/format/result",
        payload=result_payload,
        token=owner.token,
        request_id=request_id,
        timeout_seconds=settings.request_timeout_seconds,
        expected_status=200,
        validator=lambda value: _validate_result(
            value, request_id, expected_reused=False
        ),
    )
    outcomes.append(cleanup)
    return outcomes


def _run_logout_sequence(
    target: Target, settings: ScenarioSettings, run_label: str, user: VirtualUser
) -> List[OperationOutcome]:
    """Log out one test user and prove the revoked token can no longer be used."""
    client = WpsHttpClient(target)
    outcomes: List[OperationOutcome] = []
    logout, _ = _operation(
        client=client,
        user_index=user.index,
        stage="logout",
        method="POST",
        path="/wps-api/v1/auth/logout",
        payload={},
        token=user.token,
        request_id=_request_id(run_label, user.index, "logout", 0),
        timeout_seconds=settings.request_timeout_seconds,
        expected_status=200,
        validator=_validate_logout,
    )
    outcomes.append(logout)
    if not logout.success:
        return outcomes
    revoked = _expected_error_operation(
        client=client,
        user_index=user.index,
        stage="session_revoked",
        method="GET",
        path="/wps-api/v1/auth/me",
        payload=None,
        token=user.token,
        request_id=_request_id(run_label, user.index, "session-revoked", 0),
        timeout_seconds=settings.request_timeout_seconds,
        expected_status=401,
        expected_error_code="SESSION_INVALID",
    )
    outcomes.append(revoked)
    return outcomes


def _parallel_results(
    items: Sequence[Any], concurrency: int, callback: Callable[[Any], Any]
) -> List[Any]:
    results: List[Any] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(callback, item) for item in items]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception:
                results.append(None)
    return results


def run_scenario(
    target: Target, settings: ScenarioSettings, run_label: Optional[str] = None
) -> Tuple[str, List[OperationOutcome]]:
    """Run concurrent synthetic accounts and return only non-sensitive facts."""
    label = run_label or "%s%s" % (settings.account_prefix, secrets.token_hex(5))
    registration_items = list(range(1, settings.users + 1))
    registration_results = _parallel_results(
        registration_items,
        settings.concurrency,
        lambda index: _register_user(target, settings, label, index),
    )
    outcomes: List[OperationOutcome] = []
    users: List[VirtualUser] = []
    for result in registration_results:
        if result is None:
            outcomes.append(
                OperationOutcome(
                    0,
                    "register",
                    0,
                    False,
                    0,
                    "WPS_LOAD_TEST_CLIENT_EXCEPTION",
                )
            )
            continue
        user, registration_outcomes = result
        outcomes.extend(registration_outcomes)
        if user is not None:
            users.append(user)
    users.sort(key=lambda user: user.index)

    workflow_results = _parallel_results(
        users,
        settings.concurrency,
        lambda user: _run_user_workflow(target, settings, label, user),
    )
    for result in workflow_results:
        if result is None:
            outcomes.append(
                OperationOutcome(
                    0,
                    "workflow",
                    0,
                    False,
                    0,
                    "WPS_LOAD_TEST_CLIENT_EXCEPTION",
                )
            )
        else:
            outcomes.extend(result)
    if len(users) >= 2 and not any(not item.success for item in outcomes):
        outcomes.extend(
            _run_cross_account_request_isolation(
                target, settings, label, users[0], users[1]
            )
        )

    logout_results = _parallel_results(
        users,
        settings.concurrency,
        lambda user: _run_logout_sequence(target, settings, label, user),
    )
    for result in logout_results:
        if result is None:
            outcomes.append(
                OperationOutcome(
                    0,
                    "logout",
                    0,
                    False,
                    0,
                    "WPS_LOAD_TEST_CLIENT_EXCEPTION",
                )
            )
        else:
            outcomes.extend(result)
    return label, sorted(outcomes, key=lambda item: (item.user_index, item.stage))


def _percentile(values: Sequence[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percentile) - 1)]


def summarize(outcomes: Sequence[OperationOutcome]) -> Dict[str, Any]:
    """Summarize stage timing, protocol errors, and format-config consistency."""
    by_stage: DefaultDict[str, List[OperationOutcome]] = defaultdict(list)
    for outcome in outcomes:
        by_stage[outcome.stage].append(outcome)
    stages: Dict[str, Any] = {}
    for stage, stage_outcomes in sorted(by_stage.items()):
        durations = [float(item.duration_ms) for item in stage_outcomes if item.success]
        stages[stage] = {
            "total": len(stage_outcomes),
            "success": sum(1 for item in stage_outcomes if item.success),
            "failed": sum(1 for item in stage_outcomes if not item.success),
            "p50_ms": _percentile(durations, 0.50),
            "p95_ms": _percentile(durations, 0.95),
            "max_ms": max(durations) if durations else None,
        }
    errors = Counter(item.error_code for item in outcomes if item.error_code)
    config_versions = sorted(
        {item.config_version for item in outcomes if item.config_version}
    )
    if any(code == "RATE_LIMITED" for code in errors):
        conclusion = "RATE_LIMITED"
    elif errors:
        conclusion = "FAIL"
    elif len(config_versions) > 1:
        conclusion = "CONFIG_VERSION_CHANGED"
    else:
        conclusion = "PASS"
    return {
        "conclusion": conclusion,
        "operations": len(outcomes),
        "success": sum(1 for item in outcomes if item.success),
        "failed": sum(1 for item in outcomes if not item.success),
        "error_codes": dict(errors),
        "config_versions": config_versions,
        "stages": stages,
    }


def _format_ms(value: Optional[float]) -> str:
    return "-" if value is None else "%s ms" % round(value, 1)


def print_summary(summary: Dict[str, Any]) -> None:
    """Print a compact human-readable summary without tokens or usernames."""
    print("WPS 协议压测结果：%s" % summary["conclusion"])
    print(
        "操作：%s；成功：%s；失败：%s"
        % (summary["operations"], summary["success"], summary["failed"])
    )
    for stage, details in summary["stages"].items():
        print(
            "- %s：%s/%s 成功，P50 %s，P95 %s"
            % (
                stage,
                details["success"],
                details["total"],
                _format_ms(details["p50_ms"]),
                _format_ms(details["p95_ms"]),
            )
        )
    if summary["error_codes"]:
        print("错误分布：%s" % json.dumps(summary["error_codes"], ensure_ascii=False))
    if summary["conclusion"] == "RATE_LIMITED":
        print("结论：已触发 WPS 限流，本次不能用于判断正常并发承载能力。")
    elif summary["conclusion"] == "CONFIG_VERSION_CHANGED":
        print("结论：测试期间格式配置版本发生变化，应在配置稳定后重新验证。")


def build_report(
    target: Target,
    settings: ScenarioSettings,
    run_label: str,
    outcomes: Sequence[OperationOutcome],
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Produce a local report deliberately excluding session tokens and passwords."""
    return {
        "target": target.origin,
        "test_account_prefix": run_label,
        "settings": asdict(settings),
        "summary": summary,
        "operations": [asdict(item) for item in outcomes],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="通过 Cloudflare Pages 对 WPS 注册与排版协议执行受控并发验证。"
    )
    parser.add_argument("--base-url", required=True, help="根地址，例如 https://docxtool.pages.dev")
    parser.add_argument("--users", type=int, default=DEFAULT_USERS, help="并发测试账号数，默认 2，公网最多 4")
    parser.add_argument("--format-requests-per-user", type=int, default=DEFAULT_FORMAT_REQUESTS_PER_USER, help="每个账号的授权/结果事务数，默认 1，最多 3")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="并发虚拟用户数，默认 2，最多 4")
    parser.add_argument("--request-timeout-seconds", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS, help="单次 HTTP 超时，默认 30 秒")
    parser.add_argument("--account-prefix", default="LoadT", help="创建的测试账号统一前缀，默认 LoadT")
    parser.add_argument("--report-json", type=Path, help="可选的本地 JSON 报告路径")
    parser.add_argument("--confirm-production-load", action="store_true", help="明确授权对公网 HTTPS 地址执行测试")
    parser.add_argument("--confirm-test-account-creation", action="store_true", help="确认本次会在目标服务创建可清理的测试账号")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        target = parse_target(
            args.base_url, confirm_production_load=args.confirm_production_load
        )
        settings = ScenarioSettings(
            users=args.users,
            format_requests_per_user=args.format_requests_per_user,
            concurrency=args.concurrency,
            request_timeout_seconds=args.request_timeout_seconds,
            account_prefix=args.account_prefix,
        )
        validate_settings(
            settings,
            target,
            confirm_test_account_creation=args.confirm_test_account_creation,
        )
    except WpsLoadTestConfigurationError as error:
        parser.error(str(error))

    print("即将测试 WPS 公网协议：%s" % target.origin)
    print(
        "计划：%s 个测试账号、每账号 %s 个格式请求、并发 %s。"
        % (
            settings.users,
            settings.format_requests_per_user,
            settings.concurrency,
        )
    )
    print(
        "注意：测试会创建账号、设备和标记为 WPS_LOAD_TEST_SYNTHETIC 的格式请求。"
    )
    run_label, outcomes = run_scenario(target, settings)
    summary = summarize(outcomes)
    print("测试账号前缀：%s（请在管理后台按此前缀清理测试账号）" % run_label)
    print_summary(summary)
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        report = build_report(target, settings, run_label, outcomes, summary)
        args.report_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("本地 JSON 报告已写入。")
    return 0 if summary["conclusion"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
