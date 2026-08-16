"""Runtime account state, session refresh, heartbeat, and controlled authorization."""

from __future__ import annotations

import socket
import threading
import time

from docxtool.version import package_version
from docxtool.wps_server.validation import (
    WPS_NOTIFICATION_BATCH_MAX,
    WPS_NOTIFICATION_BODY_MAX_CHARS,
    WPS_NOTIFICATION_LEVELS,
    WPS_NOTIFICATION_TITLE_MAX_CHARS,
    WpsValidationError,
    validate_notification_ids,
)

from . import account_store
from .control.logging_adapter import log_event
from .public_api import PublicApiError


def device_payload(device_key: str) -> dict:
    return {
        "device_key": device_key,
        "device_name": socket.gethostname() or "Windows 设备",
        "platform": "windows",
        "app_version": package_version(),
    }


def account_from_response(
    response: dict,
    *,
    origin: str,
    username: str,
    password: str,
    device_key: str,
    remember_password: bool = True,
    auto_login: bool = False,
) -> dict:
    """Build a full local account from one successful authentication response."""
    snapshot = account_snapshot_from_response(response)
    token = _required_text(response.get("session_token"), "session_token")
    account = {
        "server_origin": origin,
        **snapshot,
        "password": password,
        "session_token": token,
        "device_key": device_key,
        "remember_password": bool(remember_password),
        "auto_login": bool(auto_login),
    }
    notifications = notification_summaries_from_response(response)
    if notifications:
        # This field is deliberately transient: account_store ignores it and the
        # runtime consumes it immediately after the login UI returns.
        account["_runtime_notifications"] = notifications
    return account


def _snapshot_error(field: str) -> PublicApiError:
    """Return one stable error for malformed public account bootstrap fields."""
    return PublicApiError(
        "WPS_PUBLIC_RESPONSE_INVALID",
        f"WPS 服务返回无效账号快照字段：{field}",
    )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _snapshot_error(field)
    return value


def _required_int(value: object, field: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise _snapshot_error(field)
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise _snapshot_error(field) from exc
    if normalized < minimum:
        raise _snapshot_error(field)
    return normalized


def notification_summaries_from_response(response: dict) -> list[dict]:
    """Parse the optional, additive notification field without persisting it."""
    if not isinstance(response, dict):
        raise _snapshot_error("response")
    if "notifications" not in response:
        return []
    value = response["notifications"]
    if not isinstance(value, list) or len(value) > WPS_NOTIFICATION_BATCH_MAX:
        raise _snapshot_error("notifications")
    notifications: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        field = f"notifications[{index}]"
        if not isinstance(item, dict):
            raise _snapshot_error(field)
        notification_id = item.get("notification_id")
        try:
            validated_ids = validate_notification_ids([notification_id])
        except WpsValidationError as exc:
            raise _snapshot_error(f"{field}.notification_id") from exc
        title = item.get("title")
        body = item.get("body")
        level = item.get("level")
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > WPS_NOTIFICATION_TITLE_MAX_CHARS
        ):
            raise _snapshot_error(f"{field}.title")
        if (
            not isinstance(body, str)
            or not body.strip()
            or len(body) > WPS_NOTIFICATION_BODY_MAX_CHARS
        ):
            raise _snapshot_error(f"{field}.body")
        if not isinstance(level, str) or level not in WPS_NOTIFICATION_LEVELS:
            raise _snapshot_error(f"{field}.level")
        normalized_id = validated_ids[0]
        if normalized_id in seen:
            continue
        seen.add(normalized_id)
        notifications.append(
            {
                "notification_id": normalized_id,
                "title": title,
                "body": body,
                "level": level,
                "created_at": _required_int(item.get("created_at"), f"{field}.created_at"),
            }
        )
    return notifications


def _acknowledged_notification_ids(response: object, requested_ids: list[str]) -> list[str]:
    """Validate a public acknowledgement response against the submitted batch."""
    if not isinstance(response, dict):
        raise _snapshot_error("notifications.read")
    value = response.get("acknowledged_notification_ids")
    if not isinstance(value, list) or len(value) > len(requested_ids):
        raise _snapshot_error("notifications.read.acknowledged_notification_ids")
    requested = set(requested_ids)
    acknowledged: list[str] = []
    seen: set[str] = set()
    for item in value:
        try:
            notification_id = validate_notification_ids([item])[0]
        except WpsValidationError as exc:
            raise _snapshot_error("notifications.read.acknowledged_notification_ids") from exc
        if notification_id not in requested or notification_id in seen:
            raise _snapshot_error("notifications.read.acknowledged_notification_ids")
        seen.add(notification_id)
        acknowledged.append(notification_id)
    return acknowledged


def account_snapshot_from_response(response: dict) -> dict:
    """Parse the shared public Bootstrap Snapshot without handling local credentials."""
    if not isinstance(response, dict):
        raise _snapshot_error("response")
    user = response.get("user")
    device = response.get("device")
    features = response.get("features")
    if not isinstance(user, dict):
        raise _snapshot_error("user")
    if not isinstance(device, dict):
        raise _snapshot_error("device")
    if not isinstance(features, dict):
        raise _snapshot_error("features")
    return {
        "username": _required_text(user.get("username"), "user.username"),
        "user_id": _required_text(user.get("id"), "user.id"),
        "user_status": _required_text(user.get("status"), "user.status"),
        "device_id": _required_text(device.get("id"), "device.id"),
        "device_name": _required_text(device.get("device_name"), "device.device_name"),
        "platform": _required_text(device.get("platform"), "device.platform"),
        "device_status": _required_text(device.get("status"), "device.status"),
        "session_created_at": _required_int(
            response.get("session_created_at"), "session_created_at"
        ),
        "session_expires_at": _required_int(
            response.get("session_expires_at"), "session_expires_at"
        ),
        "features": dict(features),
        "config_version": _required_text(
            response.get("config_version"), "config_version"
        ),
        "heartbeat_interval_seconds": _required_int(
            response.get("heartbeat_interval_seconds"),
            "heartbeat_interval_seconds",
        ),
    }


def merge_account_snapshot(account: dict, response: dict) -> dict:
    """Merge `/auth/me` public fields without replacing locally owned credentials."""
    if not isinstance(account, dict):
        raise RuntimeError("WPS_LOCAL_ACCOUNT_INVALID")
    snapshot = account_snapshot_from_response(response)
    for local_key, snapshot_key in (("user_id", "user_id"), ("device_id", "device_id")):
        current = str(account.get(local_key) or "")
        if current and current != snapshot[snapshot_key]:
            raise PublicApiError(
                "WPS_PUBLIC_RESPONSE_INVALID",
                "WPS 服务账号快照与本机账号不一致",
            )
    return {**account, **snapshot}


class AccountRuntime:
    def __init__(self, account: dict, api, *, store=account_store, now_func=time.time) -> None:
        self._account = dict(account)
        initial_notifications = self._account.pop("_runtime_notifications", [])
        self._api = api
        self._store = store
        self._now = now_func
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._network_available = True
        self._error_code = ""
        self._heartbeat_observed = False
        self._heartbeat_network_failed = False
        self._heartbeat_error_code = ""
        self._reauth_required = False
        self._reauth_request_sent = False
        self._reauth_callback = None
        self._pending_notifications: dict[str, dict] = {}
        self._merge_pending_notifications(initial_notifications)

    def _merge_pending_notifications(self, notifications: list[dict]) -> int:
        """Keep one in-memory summary per notification ID and return additions."""
        added = 0
        for notification in notifications:
            notification_id = notification["notification_id"]
            if notification_id not in self._pending_notifications:
                added += 1
            self._pending_notifications[notification_id] = dict(notification)
        return added

    def _record_public_error(self, exc: PublicApiError) -> None:
        self._network_available = not exc.network
        self._error_code = exc.code
        if exc.code in {
            "SESSION_INVALID",
            "SESSION_EXPIRED",
            "INVALID_CREDENTIALS",
            "ACCOUNT_DISABLED",
            "DEVICE_DISABLED",
        }:
            self._enter_reauth_required(exc)

    def set_reauth_callback(self, callback) -> None:
        """Register the UI-thread handoff used after the runtime invalidates a session."""
        with self._lock:
            self._reauth_callback = callback

    def _enter_reauth_required(self, exc: PublicApiError) -> None:
        """Invalidate only the session and request one UI-owned reauthentication flow."""
        if not self._reauth_required:
            updated = self._store.invalidate_session()
            if updated:
                self._account = dict(updated)
            else:
                self._account["session_token"] = ""
                self._account["session_expires_at"] = 0
                self._account["auto_login"] = False
            self._reauth_required = True
            log_event(
                "WARNING",
                "account",
                "account.reauth.required",
                "WPS 登录会话已失效，需要在登录窗口重新认证",
                {
                    "error_code": exc.code,
                    "user_id_short": self._account.get("user_id", "")[:12],
                    "pending_result_count": self._store.count_format_results(),
                },
            )
        if self._reauth_request_sent:
            return
        self._reauth_request_sent = True
        callback = self._reauth_callback
        if callback is not None:
            callback()

    def summary(self) -> dict:
        with self._lock:
            return {
                "username": self._account.get("username", ""),
                "user_id": self._account.get("user_id", ""),
                "device_id": self._account.get("device_id", ""),
                "session_expires_at": int(self._account.get("session_expires_at", 0)),
                "network_available": self._network_available,
                "apply_available": (
                    self._network_available
                    and not self._reauth_required
                    and bool(self._account.get("session_token"))
                ),
                "pending_result_count": self._store.count_format_results(),
                "notifications": [
                    dict(notification)
                    for notification in self._pending_notifications.values()
                ],
                "error_code": self._error_code,
                "reauth_required": self._reauth_required,
            }

    def ensure_session(self) -> str:
        with self._lock:
            if (
                self._reauth_required
                or not self._account.get("session_token")
                or int(self._account.get("session_expires_at", 0)) <= int(self._now())
            ):
                raise PublicApiError("SESSION_EXPIRED", "登录已过期，请重新登录", 401)
            return self._account["session_token"]

    def logout(self) -> None:
        with self._lock:
            token = self._account.get("session_token", "")
            if token:
                self._api.logout(token)
            self._account["session_token"] = ""
            self._account["session_expires_at"] = 0
            self._account["auto_login"] = False
            if not self._account.get("remember_password"):
                self._account["password"] = ""
            self._store.save_account(self._account)

    def reload_account(self, account: dict = None) -> None:
        with self._lock:
            updated = dict(account) if account is not None else self._store.load_account()
            if not updated:
                raise RuntimeError("WPS_LOCAL_ACCOUNT_MISSING")
            notifications = updated.pop("_runtime_notifications", [])
            self._account = updated
            self._merge_pending_notifications(notifications)
            self._reauth_required = False
            self._reauth_request_sent = False
            self._network_available = True
            self._error_code = ""
            self._wake.set()

    def refresh_account_snapshot(self) -> dict:
        """Refresh only public snapshot fields through `/auth/me` when explicitly needed."""
        try:
            with self._lock:
                token = self.ensure_session()
            response = self._api.current_user(token)
            with self._lock:
                updated = merge_account_snapshot(self._account, response)
                self._store.save_account(updated)
                self._account = updated
                self._merge_pending_notifications(notification_summaries_from_response(response))
                return dict(updated)
        except PublicApiError as exc:
            with self._lock:
                self._record_public_error(exc)
            raise

    def _apply_heartbeat_refresh(self, response: dict) -> None:
        """Persist only dynamic heartbeat state after validating the server response."""
        if not isinstance(response, dict):
            raise _snapshot_error("heartbeat")
        notifications = notification_summaries_from_response(response)
        features = response.get("features")
        if not isinstance(features, dict):
            raise _snapshot_error("heartbeat.features")
        updated = dict(self._account)
        updated["features"] = dict(features)
        updated["config_version"] = _required_text(
            response.get("config_version"), "heartbeat.config_version"
        )
        updated["heartbeat_interval_seconds"] = _required_int(
            response.get("heartbeat_interval_seconds"),
            "heartbeat.heartbeat_interval_seconds",
        )
        account_status = response.get("account_status")
        device_status = response.get("device_status")
        if account_status is not None:
            updated["user_status"] = _required_text(
                account_status, "heartbeat.account_status"
            )
        if device_status is not None:
            updated["device_status"] = _required_text(
                device_status, "heartbeat.device_status"
            )
        self._store.save_account(updated)
        self._account = updated
        added_notifications = self._merge_pending_notifications(notifications)
        if added_notifications:
            log_event(
                "INFO",
                "account",
                "account.notification.received",
                "WPS 账号已收到待展示通知",
                {
                    "notification_count": added_notifications,
                    "pending_notification_count": len(self._pending_notifications),
                },
            )

    def acknowledge_notifications(self, notification_ids: list[str]) -> dict:
        """Confirm displayed notifications through the authenticated public API."""
        try:
            normalized_ids = validate_notification_ids(notification_ids)
        except WpsValidationError as exc:
            raise PublicApiError(
                "WPS_NOTIFICATION_IDS_INVALID", "通知确认编号无效"
            ) from exc
        try:
            with self._lock:
                token = self.ensure_session()
                response = self._api.acknowledge_notifications(token, normalized_ids)
                acknowledged = _acknowledged_notification_ids(
                    response,
                    normalized_ids,
                )
                for notification_id in acknowledged:
                    self._pending_notifications.pop(notification_id, None)
                self._network_available = True
                self._error_code = ""
        except PublicApiError as exc:
            with self._lock:
                self._record_public_error(exc)
            raise
        log_event(
            "INFO",
            "account",
            "account.notification.acknowledged",
            "WPS 通知展示确认已同步",
            {
                "acknowledged_count": len(acknowledged),
                "pending_notification_count": len(self._pending_notifications),
            },
        )
        return {"acknowledged_notification_ids": acknowledged}

    def _heartbeat_interval_seconds(self) -> int:
        """Return the server-provided heartbeat cadence without guessing a local fallback."""
        try:
            return _required_int(
                self._account.get("heartbeat_interval_seconds"),
                "local.heartbeat_interval_seconds",
            )
        except PublicApiError as exc:
            raise RuntimeError("WPS_ACCOUNT_HEARTBEAT_INTERVAL_INVALID") from exc

    def heartbeat_once(self) -> dict:
        try:
            with self._lock:
                token = self.ensure_session()
                result = self._api.heartbeat(
                    token,
                    {"device_id": self._account["device_id"], "app_version": package_version()},
                )
                self._apply_heartbeat_refresh(result)
                was_offline = self._heartbeat_network_failed
                self._network_available = True
                self._error_code = ""
                if was_offline:
                    log_event(
                        "INFO",
                        "account",
                        "account.heartbeat.recovered",
                        "WPS 账号心跳已恢复",
                        {
                            "user_id_short": self._account["user_id"][:12],
                            "device_id_short": self._account["device_id"][:12],
                        },
                    )
                elif not self._heartbeat_observed:
                    log_event(
                        "INFO",
                        "account",
                        "account.heartbeat.online",
                        "WPS 账号心跳已上线",
                        {
                            "user_id_short": self._account["user_id"][:12],
                            "device_id_short": self._account["device_id"][:12],
                        },
                    )
                self._heartbeat_observed = True
                self._heartbeat_network_failed = False
                self._heartbeat_error_code = ""
                return result
        except PublicApiError as exc:
            with self._lock:
                self._record_public_error(exc)
                if exc.network and not self._heartbeat_network_failed:
                    log_event(
                        "WARNING",
                        "account",
                        "account.heartbeat.failed",
                        "服务器无法连接",
                        {
                            "user_id_short": self._account.get("user_id", "")[:12],
                            "device_id_short": self._account.get("device_id", "")[:12],
                            "error_code": exc.code,
                            "network_available": not exc.network,
                        },
                    )
                elif not exc.network and self._heartbeat_error_code != exc.code:
                    log_event(
                        "WARNING",
                        "account",
                        "account.heartbeat.failed",
                        "WPS 账号心跳失败",
                        {
                            "user_id_short": self._account.get("user_id", "")[:12],
                            "device_id_short": self._account.get("device_id", "")[:12],
                            "error_code": exc.code,
                            "network_available": True,
                        },
                    )
                self._heartbeat_error_code = exc.code
                self._heartbeat_network_failed = exc.network
            raise

    def authorize_format(self, request_id: str) -> dict:
        try:
            with self._lock:
                token = self.ensure_session()
                result = self._api.authorize_format(
                    token,
                    {"request_id": request_id, "command": "apply", "app_version": package_version()},
                )
                self._network_available = True
                self._error_code = ""
                return result
        except PublicApiError as exc:
            with self._lock:
                self._record_public_error(exc)
            raise

    def report_format_result(
        self,
        request_id: str,
        status: str,
        duration_ms: int,
        error_code: str,
        document_name: str = "",
    ) -> dict:
        payload = {
            "request_id": request_id,
            "status": status,
            "duration_ms": duration_ms,
            "error_code": error_code,
            "app_version": package_version(),
        }
        if document_name:
            payload["document_name"] = document_name
        with self._lock:
            reused = self._store.enqueue_format_result(payload)
        self._wake.set()
        log_event(
            "INFO",
            "account",
            "account.format_result.queued",
            "WPS 排版结果已进入本机待发队列",
            {
                "request_id": request_id,
                "request_status": status,
                "pending_result_count": self.summary()["pending_result_count"],
                "reused": reused,
            },
        )
        return {"request_id": request_id, "queued": True, "reused": reused}

    def _flush_pending_results(self) -> None:
        while True:
            try:
                with self._lock:
                    pending = self._store.list_format_results()
                    if not pending:
                        return
                    payload = pending[0]
                    request_id = payload["request_id"]
                    token = self.ensure_session()
                self._api.report_format_result(token, payload)
            except PublicApiError as exc:
                with self._lock:
                    self._record_public_error(exc)
                    if exc.code == "REQUEST_STATUS_CONFLICT":
                        self._store.delete_format_result(request_id)
                if exc.code == "REQUEST_STATUS_CONFLICT":
                    log_event(
                        "ERROR",
                        "account",
                        "account.format_result.rejected",
                        "WPS 排版结果补报被公网终态拒绝",
                        {
                            "request_id": request_id,
                            "error_code": exc.code,
                            "pending_result_count": self.summary()["pending_result_count"],
                        },
                    )
                    continue
                log_event(
                    "WARNING",
                    "account",
                    "account.format_result.deferred",
                    "WPS 排版结果暂未同步，等待下次心跳",
                    {
                        "request_id": request_id,
                        "error_code": exc.code,
                        "network_available": not exc.network,
                        "pending_result_count": self.summary()["pending_result_count"],
                    },
                )
                raise
            with self._lock:
                self._store.delete_format_result(request_id)
                self._network_available = True
                self._error_code = ""
            log_event(
                "INFO",
                "account",
                "account.format_result.completed",
                "WPS 排版结果已同步公网服务",
                {
                    "request_id": request_id,
                    "request_status": payload["status"],
                    "pending_result_count": self.summary()["pending_result_count"],
                },
            )

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("WPS_ACCOUNT_RUNTIME_ALREADY_STARTED")
        self._thread = threading.Thread(target=self._heartbeat_loop, name="wps-account-heartbeat", daemon=True)
        self._thread.start()

    def _heartbeat_loop(self) -> None:
        next_heartbeat = 0.0
        try:
            while not self._stop.is_set():
                triggered = self._wake.is_set()
                self._wake.clear()
                now = time.monotonic()
                heartbeat_succeeded = False
                if now >= next_heartbeat:
                    try:
                        self.heartbeat_once()
                        heartbeat_succeeded = True
                    except PublicApiError:
                        pass
                    with self._lock:
                        interval = self._heartbeat_interval_seconds()
                    next_heartbeat = time.monotonic() + interval
                with self._lock:
                    pending = self._store.count_format_results() > 0
                if pending and (heartbeat_succeeded or triggered):
                    try:
                        self._flush_pending_results()
                    except PublicApiError:
                        pass
                wait_seconds = max(0.0, next_heartbeat - time.monotonic())
                self._wake.wait(wait_seconds)
        except Exception as exc:
            with self._lock:
                self._error_code = "WPS_ACCOUNT_HEARTBEAT_THREAD_FAILED"
            log_event(
                "ERROR",
                "account",
                "account.heartbeat.thread.failed",
                "WPS 账号心跳线程因意外错误停止",
                {
                    "error_code": "WPS_ACCOUNT_HEARTBEAT_THREAD_FAILED",
                    "error_type": type(exc).__name__,
                    "pending_result_count": self.summary()["pending_result_count"],
                },
            )

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                raise RuntimeError("WPS_ACCOUNT_HEARTBEAT_STOP_TIMEOUT")
