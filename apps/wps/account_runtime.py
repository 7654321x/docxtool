"""Runtime account state, silent login, heartbeat, and controlled authorization."""

from __future__ import annotations

import socket
import threading
import time

from docxtool.version import package_version

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


def account_from_response(response: dict, *, origin: str, username: str, password: str, device_key: str) -> dict:
    return {
        "server_origin": origin,
        "username": response["user"]["username"],
        "user_id": response["user"]["id"],
        "device_id": response["device"]["id"],
        "password": password,
        "session_token": response["session_token"],
        "device_key": device_key,
        "session_expires_at": int(response["session_expires_at"]),
    }


class AccountRuntime:
    def __init__(self, account: dict, api, *, store=account_store, now_func=time.time) -> None:
        self._account = dict(account)
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
        self._pending_results = {}

    def _record_public_error(self, exc: PublicApiError) -> None:
        self._network_available = not exc.network
        self._error_code = exc.code
        if exc.code in {"SESSION_INVALID", "SESSION_EXPIRED"}:
            self._account["session_token"] = ""
            self._account["session_expires_at"] = 0
        elif exc.code in {"INVALID_CREDENTIALS", "ACCOUNT_DISABLED", "DEVICE_DISABLED"}:
            self._store.clear_account()
            self._account["session_token"] = ""
            self._account["session_expires_at"] = 0

    def summary(self) -> dict:
        with self._lock:
            return {
                "username": self._account.get("username", ""),
                "user_id": self._account.get("user_id", ""),
                "device_id": self._account.get("device_id", ""),
                "session_expires_at": int(self._account.get("session_expires_at", 0)),
                "network_available": self._network_available,
                "apply_available": self._network_available and bool(self._account.get("session_token")),
                "pending_result_count": len(self._pending_results),
                "error_code": self._error_code,
            }

    def _login(self) -> None:
        fields = {
            "user_id_short": self._account.get("user_id", "")[:12],
            "device_id_short": self._account.get("device_id", "")[:12],
        }
        log_event("INFO", "account", "account.session.refresh.start", "开始静默刷新 WPS 登录状态", fields)
        try:
            response = self._api.login(
                {
                    "username": self._account["username"],
                    "password": self._account["password"],
                    "device": device_payload(self._account["device_key"]),
                }
            )
        except PublicApiError as exc:
            self._record_public_error(exc)
            log_event(
                "WARNING",
                "account",
                "account.session.refresh.failed",
                "WPS 登录状态静默刷新失败",
                {**fields, "error_code": exc.code, "network_available": not exc.network},
            )
            raise
        updated = account_from_response(
            response,
            origin=self._account["server_origin"],
            username=self._account["username"],
            password=self._account["password"],
            device_key=self._account["device_key"],
        )
        self._store.save_account(updated)
        self._account = updated
        self._network_available = True
        self._error_code = ""
        log_event(
            "INFO",
            "account",
            "account.session.refresh.completed",
            "WPS 登录状态静默刷新完成",
            {
                "user_id_short": updated["user_id"][:12],
                "device_id_short": updated["device_id"][:12],
            },
        )

    def ensure_session(self) -> str:
        with self._lock:
            if int(self._account.get("session_expires_at", 0)) <= int(self._now()):
                self._login()
            return self._account["session_token"]

    def heartbeat_once(self) -> dict:
        try:
            with self._lock:
                token = self.ensure_session()
                result = self._api.heartbeat(
                    token,
                    {"device_id": self._account["device_id"], "app_version": package_version()},
                )
                was_offline = self._heartbeat_network_failed
                self._network_available = True
                self._error_code = ""
                if not self._heartbeat_observed:
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
                elif was_offline:
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
                self._heartbeat_observed = True
                self._heartbeat_network_failed = False
                self._heartbeat_error_code = ""
                return result
        except PublicApiError as exc:
            with self._lock:
                self._record_public_error(exc)
                if self._heartbeat_error_code != exc.code:
                    log_event(
                        "WARNING",
                        "account",
                        "account.heartbeat.failed",
                        "WPS 账号心跳失败",
                        {
                            "user_id_short": self._account.get("user_id", "")[:12],
                            "device_id_short": self._account.get("device_id", "")[:12],
                            "error_code": exc.code,
                            "network_available": not exc.network,
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

    def report_format_result(self, request_id: str, status: str, duration_ms: int, error_code: str) -> dict:
        payload = {
            "request_id": request_id,
            "status": status,
            "duration_ms": duration_ms,
            "error_code": error_code,
            "app_version": package_version(),
        }
        with self._lock:
            existing = self._pending_results.get(request_id)
            if existing is not None and existing != payload:
                raise RuntimeError("WPS_FORMAT_RESULT_QUEUE_CONFLICT")
            reused = existing is not None
            self._pending_results[request_id] = payload
        self._wake.set()
        log_event(
            "INFO",
            "account",
            "account.format_result.queued",
            "WPS 排版结果已进入内存待发队列",
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
            with self._lock:
                if not self._pending_results:
                    return
                request_id, payload = next(iter(self._pending_results.items()))
                token = self.ensure_session()
            try:
                self._api.report_format_result(token, payload)
            except PublicApiError as exc:
                with self._lock:
                    self._record_public_error(exc)
                    if exc.code == "REQUEST_STATUS_CONFLICT":
                        self._pending_results.pop(request_id, None)
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
                self._pending_results.pop(request_id, None)
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
                    next_heartbeat = time.monotonic() + 600
                with self._lock:
                    pending = bool(self._pending_results)
                if pending and (heartbeat_succeeded or triggered):
                    try:
                        self._flush_pending_results()
                    except PublicApiError:
                        pass
                wait_seconds = max(0.0, next_heartbeat - time.monotonic())
                self._wake.wait(wait_seconds)
        except Exception as exc:
            with self._lock:
                self._network_available = False
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
        pending_count = self.summary()["pending_result_count"]
        if pending_count:
            with self._lock:
                self._pending_results.clear()
            log_event(
                "WARNING",
                "account",
                "account.format_result.discarded",
                "WPS 进程退出，内存中的待发排版结果已丢弃",
                {"pending_result_count": pending_count},
            )
