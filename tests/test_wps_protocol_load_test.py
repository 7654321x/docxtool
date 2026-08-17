"""Focused tests for the bounded public WPS protocol load-test utility."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "wps_protocol_load_test.py"
SPEC = importlib.util.spec_from_file_location("wps_protocol_load_test", SCRIPT_PATH)
assert SPEC and SPEC.loader
wps_protocol_load_test = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wps_protocol_load_test
SPEC.loader.exec_module(wps_protocol_load_test)


def _envelope(data, request_id="test-request"):
    return {
        "ok": True,
        "api_version": "wps-api-v1",
        "request_id": request_id,
        "server_time": 1,
        "data": data,
    }


def _error_envelope(code, request_id):
    return {
        "ok": False,
        "api_version": "wps-api-v1",
        "request_id": request_id,
        "server_time": 1,
        "error": {"code": code, "message": "test rejection"},
    }


def _bearer_token(headers):
    value = headers.get("Authorization", "")
    return value[7:] if value.startswith("Bearer ") else ""


def test_public_target_and_settings_require_explicit_production_authorization():
    with pytest.raises(
        wps_protocol_load_test.WpsLoadTestConfigurationError,
        match="confirm-production-load",
    ):
        wps_protocol_load_test.parse_target(
            "https://docx.toolpp.cn", confirm_production_load=False
        )

    target = wps_protocol_load_test.parse_target(
        "https://docx.toolpp.cn", confirm_production_load=True
    )
    settings = wps_protocol_load_test.ScenarioSettings(
        users=2,
        format_requests_per_user=1,
        concurrency=2,
        request_timeout_seconds=5,
        account_prefix="LoadT",
    )
    with pytest.raises(
        wps_protocol_load_test.WpsLoadTestConfigurationError,
        match="confirm-test-account-creation",
    ):
        wps_protocol_load_test.validate_settings(
            settings, target, confirm_test_account_creation=False
        )


def test_identity_and_correlation_contracts_reject_mismatched_responses():
    snapshot = {
        "user": {"id": "wusr_one", "username": "LoadT01", "status": "active"},
        "device": {"id": "wdev_one", "status": "active"},
        "config_version": "config-test-1",
        "heartbeat_interval_seconds": 600,
    }
    assert (
        wps_protocol_load_test._validate_snapshot(
            snapshot,
            include_token=False,
            expected_username="LoadT02",
            expected_user_id="wusr_one",
            expected_device_id="wdev_one",
        )
        == "WPS_LOAD_TEST_RESPONSE_IDENTITY_MISMATCH"
    )
    assert (
        wps_protocol_load_test._response_request_id_error(
            {"request_id": "other-request"}, "expected-request"
        )
        == "WPS_LOAD_TEST_CORRELATION_ID_MISMATCH"
    )


def test_concurrent_wps_protocol_scenario_preserves_retry_and_result_contracts():
    state = {
        "authorizations": {},
        "results": {},
        "tokens": {},
        "logged_out": set(),
    }
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def _write(self, status, payload):
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _payload(self):
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _request_id(self):
            return self.headers["X-DocxTool-Request-Id"]

        def _session_context(self):
            token = _bearer_token(self.headers)
            with lock:
                return token, state["tokens"].get(token), token in state["logged_out"]

        def do_GET(self):  # noqa: N802
            assert self.path == "/wps-api/v1/auth/me"
            request_id = self._request_id()
            _token, context, logged_out = self._session_context()
            if logged_out:
                self._write(401, _error_envelope("SESSION_INVALID", request_id))
                return
            assert context is not None
            self._write(
                200,
                _envelope(
                    {
                        "user": {
                            "id": context["user_id"],
                            "username": context["username"],
                            "status": "active",
                        },
                        "device": {"id": context["device_id"], "status": "active"},
                        "session_created_at": 1,
                        "session_expires_at": 2,
                        "features": {},
                        "config_version": "config-test-1",
                        "heartbeat_interval_seconds": 600,
                    },
                    request_id,
                ),
            )

        def do_POST(self):  # noqa: N802
            body = self._payload()
            path = self.path
            request_id = self._request_id()
            if path == "/wps-api/v1/auth/register":
                username = str(body["username"])
                token = ("T" + username).ljust(43, "A")
                context = {
                    "user_id": "wusr_%s" % username,
                    "username": username,
                    "device_id": "wdev_%s" % username,
                }
                with lock:
                    state["tokens"][token] = context
                self._write(
                    201,
                    _envelope(
                        {
                            "user": {
                                "id": context["user_id"],
                                "username": context["username"],
                                "status": "active",
                            },
                            "device": {
                                "id": context["device_id"],
                                "status": "active",
                            },
                            "session_token": token,
                            "session_created_at": 1,
                            "session_expires_at": 2,
                            "features": {},
                            "config_version": "config-test-1",
                            "heartbeat_interval_seconds": 600,
                            "notifications": [],
                        },
                        request_id,
                    ),
                )
                return
            token, context, logged_out = self._session_context()
            if logged_out:
                self._write(401, _error_envelope("SESSION_INVALID", request_id))
                return
            assert context is not None
            if path == "/wps-api/v1/heartbeat":
                assert body["device_id"] == context["device_id"]
                self._write(
                    200,
                    _envelope(
                        {
                            "account_status": "active",
                            "device_status": "active",
                            "session_expires_at": 2,
                            "features": {},
                            "config_version": "config-test-1",
                            "heartbeat_interval_seconds": 600,
                            "notifications": [],
                        },
                        request_id,
                    ),
                )
                return
            if path == "/wps-api/v1/format/authorize":
                request_id = body["request_id"]
                assert self.headers["X-DocxTool-Request-Id"] == request_id
                with lock:
                    owner = state["authorizations"].get(request_id)
                    if owner is not None and owner != token:
                        self._write(
                            409, _error_envelope("REQUEST_ID_CONFLICT", request_id)
                        )
                        return
                    reused = owner is not None
                    state["authorizations"][request_id] = token
                self._write(
                    200,
                    _envelope(
                        {
                            "allowed": True,
                            "reused": reused,
                            "request_id": request_id,
                            "command": "apply",
                            "request_status": "authorized",
                            "config_version": "config-test-1",
                            "format_config": {"features": {}},
                        },
                        request_id,
                    ),
                )
                return
            if path == "/wps-api/v1/format/result":
                request_id = body["request_id"]
                assert self.headers["X-DocxTool-Request-Id"] == request_id
                assert body["status"] == "failed"
                assert body["error_code"] == "WPS_LOAD_TEST_SYNTHETIC"
                with lock:
                    assert state["authorizations"].get(request_id) == token
                    owner = state["results"].get(request_id)
                    reused = owner is not None
                    state["results"][request_id] = token
                self._write(
                    200,
                    _envelope(
                        {
                            "request_id": request_id,
                            "status": "failed",
                            "reused": reused,
                        },
                        request_id,
                    ),
                )
                return
            if path == "/wps-api/v1/auth/logout":
                with lock:
                    state["logged_out"].add(token)
                self._write(200, _envelope({"logged_out": True}, request_id))
                return
            raise AssertionError("unexpected path: %s" % path)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        target = wps_protocol_load_test.parse_target(
            "http://127.0.0.1:%s" % server.server_port,
            confirm_production_load=False,
        )
        settings = wps_protocol_load_test.ScenarioSettings(
            users=2,
            format_requests_per_user=2,
            concurrency=2,
            request_timeout_seconds=5,
            account_prefix="LoadT",
        )
        run_label, outcomes = wps_protocol_load_test.run_scenario(
            target, settings, run_label="LoadTabcd1234"
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    summary = wps_protocol_load_test.summarize(outcomes)
    assert run_label == "LoadTabcd1234"
    assert summary["conclusion"] == "PASS"
    assert summary["failed"] == 0
    assert summary["stages"]["register"]["success"] == 2
    assert summary["stages"]["format_authorize_retry"]["success"] == 4
    assert summary["stages"]["format_result_retry"]["success"] == 4
    assert summary["stages"]["cross_account_request_isolation"]["success"] == 1
    assert summary["stages"]["session_revoked"]["success"] == 2
    assert len(state["authorizations"]) == 5
    assert len(state["results"]) == 5

    report = wps_protocol_load_test.build_report(
        target, settings, run_label, outcomes, summary
    )
    serialized = json.dumps(report)
    assert not any(token in serialized for token in state["tokens"])
    assert "LoadA1" not in serialized
