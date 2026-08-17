"""Strict HTTPS JSON client for the WPS public account service."""

from __future__ import annotations

import http.client
import json
from pathlib import Path
import socket
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from docxtool.version import package_version

API_PREFIX = "/wps-api/v1"
API_VERSION = "wps-api-v1"
DEFAULT_TIMEOUT_SECONDS = 8
CLIENT_USER_AGENT = f"DocxToolWPS/{package_version()}"


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that resolves the public gateway to IPv4 addresses only."""

    def connect(self) -> None:
        last_error: OSError | None = None
        addresses = socket.getaddrinfo(
            self.host,
            self.port,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
        for family, sock_type, protocol, _canonical_name, sockaddr in addresses:
            sock = socket.socket(family, sock_type, protocol)
            try:
                sock.settimeout(self.timeout)
                sock.connect(sockaddr)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                return
            except OSError as exc:
                last_error = exc
                sock.close()
        if last_error is not None:
            raise last_error
        raise OSError("WPS_PUBLIC_IPV4_ADDRESS_UNAVAILABLE")


class PublicApiError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 0, *, network: bool = False) -> None:
        self.code = code
        self.message = message
        self.status = status
        self.network = network
        super().__init__(code)


def _cloudflare_client_blocked(raw: bytes, status: int) -> bool:
    """Recognize Cloudflare's non-JSON browser-signature denial page."""
    return status == 403 and b"error code: 1010" in raw.lower()


def _config_path() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / "client-config.json"


def _validate_public_api_base_url(base_url: str) -> str:
    if not isinstance(base_url, str):
        raise RuntimeError("WPS_PUBLIC_API_BASE_URL_INVALID")
    parsed = urlparse(base_url)
    is_loopback = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    try:
        _ = parsed.port
    except ValueError as exc:
        raise RuntimeError("WPS_PUBLIC_API_BASE_URL_INVALID") from exc
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (parsed.scheme != "https" and not is_loopback)
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("WPS_PUBLIC_API_BASE_URL_INVALID")
    return base_url.rstrip("/")


def configured_public_api_base_url() -> str:
    value = json.loads(_config_path().read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"public_api_base_url"}:
        raise RuntimeError("WPS_CLIENT_CONFIG_INVALID")
    return _validate_public_api_base_url(value["public_api_base_url"])


class WpsPublicApi:
    def __init__(self, public_api_base_url: str = "", timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.public_api_base_url = (
            _validate_public_api_base_url(public_api_base_url)
            if public_api_base_url
            else configured_public_api_base_url()
        )
        self.timeout = timeout

    def _open_https_over_ipv4(self, method: str, path: str, body: bytes | None, headers: dict[str, str]) -> tuple[bytes, int]:
        parsed = urlparse(self.public_api_base_url)
        connection = _IPv4HTTPSConnection(
            parsed.hostname,
            port=parsed.port or 443,
            timeout=self.timeout,
        )
        try:
            connection.request(method, API_PREFIX + path, body=body, headers=headers)
            response = connection.getresponse()
            return response.read(), int(response.status)
        finally:
            connection.close()

    def _request(self, method: str, path: str, payload=None, *, token: str = "", request_id: str = "") -> dict:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json",
            # Cloudflare blocks the default Python-urllib signature before the
            # Pages Worker can process a request. Keep an explicit, stable
            # product identifier on every public WPS request instead.
            "User-Agent": CLIENT_USER_AGENT,
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if request_id:
            headers["X-DocxTool-Request-Id"] = request_id
        try:
            if self.public_api_base_url.startswith("https://"):
                raw, status = self._open_https_over_ipv4(method, path, body, headers)
            else:
                request = Request(self.public_api_base_url + API_PREFIX + path, data=body, headers=headers, method=method)
                response = urlopen(request, timeout=self.timeout)
                raw = response.read()
                status = int(response.status)
        except HTTPError as exc:
            raw = exc.read()
            status = int(exc.code)
        except (URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            raise PublicApiError("WPS_PUBLIC_SERVER_UNAVAILABLE", "暂时无法连接 WPS 服务", network=True) from exc
        if _cloudflare_client_blocked(raw, status):
            raise PublicApiError(
                "WPS_PUBLIC_CLIENT_BLOCKED",
                "客户端请求被访问规则拦截，请更新客户端或联系管理员。",
                status,
            )
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicApiError("WPS_PUBLIC_RESPONSE_INVALID", "WPS 服务返回无效响应", status) from exc
        if not isinstance(envelope, dict) or envelope.get("api_version") != API_VERSION or not isinstance(envelope.get("ok"), bool):
            raise PublicApiError("WPS_PUBLIC_RESPONSE_INVALID", "WPS 服务返回无效响应", status)
        if request_id and envelope.get("request_id") != request_id:
            raise PublicApiError(
                "WPS_PUBLIC_REQUEST_ID_MISMATCH",
                "WPS 服务响应与当前请求不匹配",
                status,
            )
        if envelope["ok"] is not True:
            error = envelope.get("error")
            if not isinstance(error, dict) or not isinstance(error.get("code"), str) or not isinstance(error.get("message"), str):
                raise PublicApiError("WPS_PUBLIC_RESPONSE_INVALID", "WPS 服务返回无效错误", status)
            raise PublicApiError(error["code"], error["message"], status)
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise PublicApiError("WPS_PUBLIC_RESPONSE_INVALID", "WPS 服务返回无效数据", status)
        return data

    def register(self, payload: dict) -> dict:
        return self._request("POST", "/auth/register", payload)

    def login(self, payload: dict) -> dict:
        return self._request("POST", "/auth/login", payload)

    def current_user(self, session_token: str) -> dict:
        return self._request("GET", "/auth/me", token=session_token)

    def logout(self, session_token: str) -> dict:
        return self._request("POST", "/auth/logout", {}, token=session_token)

    def heartbeat(self, session_token: str, payload: dict) -> dict:
        return self._request("POST", "/heartbeat", payload, token=session_token)

    def acknowledge_notifications(
        self, session_token: str, notification_ids: list[str]
    ) -> dict:
        """Confirm TaskPane display for an account-scoped notification batch."""
        return self._request(
            "POST",
            "/notifications/read",
            {"notification_ids": notification_ids},
            token=session_token,
        )

    def authorize_format(self, session_token: str, payload: dict) -> dict:
        data = self._request("POST", "/format/authorize", payload, token=session_token, request_id=payload["request_id"])
        if data.get("request_id") != payload["request_id"]:
            raise PublicApiError(
                "WPS_PUBLIC_REQUEST_ID_MISMATCH",
                "WPS 服务授权数据与当前请求不匹配",
            )
        return data

    def report_format_result(self, session_token: str, payload: dict) -> dict:
        data = self._request("POST", "/format/result", payload, token=session_token, request_id=payload["request_id"])
        if data.get("request_id") != payload["request_id"]:
            raise PublicApiError(
                "WPS_PUBLIC_REQUEST_ID_MISMATCH",
                "WPS 服务结果数据与当前请求不匹配",
            )
        return data
