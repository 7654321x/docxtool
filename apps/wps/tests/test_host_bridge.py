import http.client
import json
from pathlib import Path
import threading
import time
from typing import Tuple

import pytest

from apps.wps.control.host_bridge import HostBridge, HostBridgeError
from apps.wps.control import document_transaction as transaction_module
from apps.wps.control import server as server_module
from apps.wps.control.format_current_document import FormatResult
from apps.wps.public_api import PublicApiError


def _ready_bridge() -> Tuple[HostBridge, int]:
    bridge = HostBridge()
    registration = bridge.register_host("host-context-a")
    generation = registration["host_generation"]
    bridge.publish_state(
        "host-context-a",
        generation,
        {"host_ready": True, "status": "READY", "active_request": None},
    )
    return bridge, generation


def test_command_wait_blocks_until_taskpane_submits_command():
    bridge, generation = _ready_bridge()
    entered = threading.Event()
    completed = threading.Event()
    result = {}

    def wait_for_command() -> None:
        entered.set()
        result.update(
            bridge.wait_command("host-context-a", generation, timeout_seconds=2)
        )
        completed.set()

    thread = threading.Thread(target=wait_for_command)
    thread.start()
    assert entered.wait(timeout=1)
    assert not completed.wait(timeout=0.05)

    queued = bridge.enqueue_command(
        request_id="request-1",
        command="health",
        pane_instance_id="pane-1",
        host_generation=generation,
    )

    assert completed.wait(timeout=1)
    thread.join(timeout=1)
    assert queued == {
        "request_id": "request-1",
        "command_sequence": 1,
        "state_revision": 4,
    }
    assert result == {
        "timed_out": False,
        "command": {
            "schema_version": "wps-command-v2",
            "request_id": "request-1",
            "command": "health",
            "pane_instance_id": "pane-1",
            "command_sequence": 1,
            "host_generation": generation,
        },
    }


def test_panel_ready_is_allowed_and_unknown_commands_remain_rejected():
    bridge, generation = _ready_bridge()

    queued = bridge.enqueue_command(
        "request-panel-ready", "panel_ready", "pane-1", generation
    )

    assert queued["request_id"] == "request-panel-ready"
    command = bridge.wait_command(
        "host-context-a", generation, timeout_seconds=0
    )["command"]
    assert command["command"] == "panel_ready"

    bridge.publish_state(
        "host-context-a",
        generation,
        {
            "host_ready": True,
            "status": "READY",
            "active_request": {
                "request_id": "request-panel-ready",
                "request_status": "PASS",
            },
        },
    )
    with pytest.raises(HostBridgeError, match="WPS_REQUEST_COMMAND_INVALID"):
        bridge.enqueue_command(
            "request-invalid", "unknown", "pane-1", generation
        )


def test_command_submission_wakes_only_one_host_waiter():
    bridge, generation = _ready_bridge()
    results = []
    results_lock = threading.Lock()

    def wait_for_command() -> None:
        result = bridge.wait_command(
            "host-context-a", generation, timeout_seconds=0.2
        )
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=wait_for_command) for _ in range(2)]
    for thread in threads:
        thread.start()
    time.sleep(0.05)

    bridge.enqueue_command("request-1", "health", "pane-1", generation)

    for thread in threads:
        thread.join(timeout=1)
        assert not thread.is_alive()
    delivered = [result for result in results if result["timed_out"] is False]
    timed_out = [result for result in results if result["timed_out"] is True]
    assert len(delivered) == 1
    assert delivered[0]["command"]["request_id"] == "request-1"
    assert timed_out == [{"timed_out": True, "command": None}]


def test_single_command_slot_remains_busy_until_terminal_state():
    bridge, generation = _ready_bridge()
    bridge.enqueue_command("request-1", "preview", "pane-1", generation)
    bridge.wait_command("host-context-a", generation, timeout_seconds=0)

    with pytest.raises(HostBridgeError, match="WPS_COMMAND_BUSY"):
        bridge.enqueue_command("request-2", "health", "pane-1", generation)

    bridge.publish_state(
        "host-context-a",
        generation,
        {
            "host_ready": True,
            "status": "PASS",
            "active_request": {
                "request_id": "request-1",
                "request_status": "PASS",
            },
        },
    )

    queued = bridge.enqueue_command("request-2", "health", "pane-1", generation)
    assert queued["request_id"] == "request-2"


def test_apply_command_requires_matching_authorized_config():
    bridge, generation = _ready_bridge()
    with pytest.raises(HostBridgeError, match="WPS_APPLY_AUTHORIZATION_REQUIRED"):
        bridge.enqueue_command("request-apply", "apply", "pane-1", generation)

    queued = bridge.enqueue_command(
        "request-apply",
        "apply",
        "pane-1",
        generation,
        {
            "request_id": "request-apply",
            "config_version": "config-1",
            "format_config": {"features": {}},
        },
    )
    delivered = bridge.wait_command("host-context-a", generation, timeout_seconds=0)

    assert queued["request_id"] == "request-apply"
    assert delivered["command"]["schema_version"] == "wps-command-v2"
    assert delivered["command"]["authorization"] == {
        "request_id": "request-apply",
        "config_version": "config-1",
    }


def test_wrong_host_context_and_generation_are_rejected():
    bridge, generation = _ready_bridge()

    with pytest.raises(HostBridgeError, match="WPS_HOST_CONTEXT_MISMATCH"):
        bridge.wait_command("host-context-b", generation, timeout_seconds=0)
    with pytest.raises(HostBridgeError, match="WPS_HOST_GENERATION_MISMATCH"):
        bridge.enqueue_command("request-1", "health", "pane-1", generation + 1)


def test_state_wait_wakes_on_revision_change():
    bridge, generation = _ready_bridge()
    initial = bridge.wait_state(after_revision=0, host_generation=generation, timeout_seconds=0)
    revision = initial["state_revision"]
    result = {}
    completed = threading.Event()

    def wait_for_state() -> None:
        result.update(
            bridge.wait_state(
                after_revision=revision,
                host_generation=generation,
                timeout_seconds=2,
            )
        )
        completed.set()

    thread = threading.Thread(target=wait_for_state)
    thread.start()
    assert not completed.wait(timeout=0.05)
    bridge.publish_state(
        "host-context-a",
        generation,
        {"host_ready": True, "status": "RUNNING", "stage": "recognition"},
    )

    assert completed.wait(timeout=1)
    thread.join(timeout=1)
    assert result["timed_out"] is False
    assert result["state"]["status"] == "RUNNING"
    assert result["state_revision"] > revision


def test_command_submission_wakes_state_wait_for_ack_deadline():
    bridge, generation = _ready_bridge()
    revision = bridge.wait_state(0, generation, 0)["state_revision"]
    result = {}
    completed = threading.Event()

    def wait_for_state() -> None:
        result.update(bridge.wait_state(revision, generation, timeout_seconds=2))
        completed.set()

    thread = threading.Thread(target=wait_for_state)
    thread.start()
    assert not completed.wait(timeout=0.05)

    queued = bridge.enqueue_command(
        "request-ack", "health", "pane-1", generation
    )

    assert completed.wait(timeout=1)
    thread.join(timeout=1)
    assert result["timed_out"] is False
    assert result["state"]["status"] == "READY"
    assert result["state_revision"] == queued["state_revision"]
    assert result["state_revision"] > revision


def test_wait_timeout_is_a_normal_empty_result():
    bridge, generation = _ready_bridge()
    started = time.monotonic()

    result = bridge.wait_command(
        "host-context-a", generation, timeout_seconds=0.05
    )

    assert time.monotonic() - started >= 0.04
    assert result == {"timed_out": True, "command": None}


def test_new_host_invalidates_old_waiter_and_pending_command():
    bridge, generation = _ready_bridge()
    bridge.enqueue_command("request-1", "health", "pane-1", generation)
    errors = []
    completed = threading.Event()

    def wait_on_old_host() -> None:
        try:
            bridge.wait_command("host-context-a", generation, timeout_seconds=2)
        except HostBridgeError as exc:
            errors.append(exc.code)
        finally:
            completed.set()

    first = bridge.wait_command("host-context-a", generation, timeout_seconds=0)
    assert first["command"]["request_id"] == "request-1"
    thread = threading.Thread(target=wait_on_old_host)
    thread.start()
    assert not completed.wait(timeout=0.05)

    replacement = bridge.register_host("host-context-b")

    assert completed.wait(timeout=1)
    thread.join(timeout=1)
    assert errors == ["WPS_HOST_CONTEXT_REPLACED"]
    assert replacement["host_generation"] == generation + 1
    snapshot = bridge.wait_state(
        after_revision=0,
        host_generation=generation,
        timeout_seconds=0,
    )
    assert snapshot["generation_changed"] is True
    assert snapshot["state"]["error_code"] == "WPS_HOST_CONTEXT_REPLACED"


def test_close_releases_command_and_state_waiters():
    bridge, generation = _ready_bridge()
    revision = bridge.wait_state(0, generation, 0)["state_revision"]
    errors = []
    command_completed = threading.Event()
    state_completed = threading.Event()

    def wait_for_command() -> None:
        try:
            bridge.wait_command("host-context-a", generation, timeout_seconds=2)
        except HostBridgeError as exc:
            errors.append(exc.code)
        finally:
            command_completed.set()

    def wait_for_state() -> None:
        try:
            bridge.wait_state(revision, generation, timeout_seconds=2)
        except HostBridgeError as exc:
            errors.append(exc.code)
        finally:
            state_completed.set()

    command_thread = threading.Thread(target=wait_for_command)
    state_thread = threading.Thread(target=wait_for_state)
    command_thread.start()
    state_thread.start()
    assert not command_completed.wait(timeout=0.05)
    assert not state_completed.is_set()

    bridge.close()

    assert command_completed.wait(timeout=1)
    assert state_completed.wait(timeout=1)
    command_thread.join(timeout=1)
    state_thread.join(timeout=1)
    assert errors == ["WPS_BRIDGE_CLOSED", "WPS_BRIDGE_CLOSED"]
    with pytest.raises(HostBridgeError, match="WPS_BRIDGE_CLOSED"):
        bridge.wait_state(revision, generation, timeout_seconds=0)


def _post(server, path, payload, token="test-token", origin=""):
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=2
    )
    try:
        headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "X-DocxTool-Request-Id": "bridge-request-1",
        }
        if origin:
            headers["Origin"] = origin
        connection.request(
            "POST",
            path,
            body=json.dumps(payload),
            headers=headers,
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        assert response.getheader("X-DocxTool-Request-Id") == "bridge-request-1"
        return response.status, body
    finally:
        connection.close()


def _get(server, path, token="test-token"):
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=2
    )
    try:
        connection.request(
            "GET",
            path,
            headers={"Authorization": "Bearer " + token},
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def _install_fake_formatter(monkeypatch):
    def fake_format(
        source_path,
        output_path,
        *,
        operation_id,
        log_dir,
        format_config=None,
        request_id="",
    ):
        target = Path(output_path)
        target.write_bytes(b"formatted")
        log_path = Path(log_dir) / "test.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8")
        return FormatResult(
            output_path=target,
            log_path=log_path,
            document_mode="NORMAL",
            paragraph_count=1,
            heading_count=0,
            body_count=1,
            export_stats={},
        )

    monkeypatch.setattr(transaction_module, "format_current_document", fake_format)


class _AccountRuntime:
    def __init__(self):
        self.reports = []

    def authorize_format(self, request_id):
        return {
            "allowed": True,
            "request_id": request_id,
            "config_version": "config-1",
            "format_config": {"features": {}},
        }

    def report_format_result(self, *args):
        self.reports.append(args)


def _prepare_apply(application, request_id, source_path):
    registration = application.dispatch_bridge(
        "/v1/bridge/host/register", {"host_context_id": "host-context-a"}
    )
    generation = registration["host_generation"]
    application.dispatch_bridge(
        "/v1/bridge/state",
        {
            "host_context_id": "host-context-a",
            "host_generation": generation,
            "state": {"host_ready": True, "status": "READY"},
        },
    )
    application.dispatch_bridge(
        "/v1/bridge/command",
        {
            "request_id": request_id,
            "command": "apply",
            "pane_instance_id": "pane-1",
            "host_generation": generation,
        },
    )
    result = application.dispatch(
        "/v1/format/prepare",
        {"source_path": str(source_path)},
        request_id=request_id,
    )
    return generation, result["operation_id"]


def test_apply_fail_rolls_back_prepared_transaction_by_request_id(
    tmp_path, monkeypatch
):
    _install_fake_formatter(monkeypatch)
    first = tmp_path / "first.docx"
    second = tmp_path / "second.docx"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    account = _AccountRuntime()
    application = server_module.WpsControlApplication(
        tmp_path, "test-token", account
    )
    generation, operation_id = _prepare_apply(
        application, "request-failed", first
    )

    application.dispatch_bridge(
        "/v1/bridge/state",
        {
            "host_context_id": "host-context-a",
            "host_generation": generation,
            "state": {
                "host_ready": True,
                "status": "FAIL",
                "active_request": {
                    "request_id": "request-failed",
                    "command": "apply",
                    "request_status": "FAIL",
                    "error_code": "WPS_FORMAT_RESPONSE_FAILED",
                },
            },
        },
    )

    with pytest.raises(
        transaction_module.DocumentTransactionError,
        match="WPS_TRANSACTION_NOT_FOUND",
    ):
        application.transactions.get(operation_id, "request-failed")
    _next_generation, next_operation_id = _prepare_apply(
        application, "request-next", second
    )
    application.transactions.rollback(
        next_operation_id, request_id="request-next"
    )


def test_apply_pass_does_not_roll_back_prepared_transaction(tmp_path, monkeypatch):
    _install_fake_formatter(monkeypatch)
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    account = _AccountRuntime()
    application = server_module.WpsControlApplication(
        tmp_path, "test-token", account
    )
    generation, operation_id = _prepare_apply(
        application, "request-passed", source
    )

    application.dispatch_bridge(
        "/v1/bridge/state",
        {
            "host_context_id": "host-context-a",
            "host_generation": generation,
            "state": {
                "host_ready": True,
                "status": "PASS",
                "active_request": {
                    "request_id": "request-passed",
                    "command": "apply",
                    "request_status": "PASS",
                },
            },
        },
    )

    assert application.transactions.get(
        operation_id, "request-passed"
    ).state == "prepared"
    application.transactions.rollback(operation_id, request_id="request-passed")


def test_apply_is_authorized_before_host_delivery_and_result_is_reported(tmp_path):
    class AccountRuntime:
        def __init__(self):
            self.reports = []

        def summary(self):
            return {"username": "User01", "apply_available": True, "network_available": True}

        def authorize_format(self, request_id):
            return {
                "allowed": True,
                "request_id": request_id,
                "config_version": "config-1",
                "format_config": {"features": {}},
            }

        def report_format_result(self, *args):
            self.reports.append(args)

    account = AccountRuntime()
    server = server_module.create_server(
        tmp_path, "test-token", 0, account_runtime=account
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, account_status = _get(server, "/v1/account")
        assert status == 200
        assert account_status["data"]["apply_available"] is True

        _, registered = _post(
            server,
            "/v1/bridge/host/register",
            {"host_context_id": "host-context-http"},
        )
        generation = registered["data"]["host_generation"]
        _post(
            server,
            "/v1/bridge/state",
            {
                "host_context_id": "host-context-http",
                "host_generation": generation,
                "state": {"host_ready": True, "status": "READY"},
            },
        )
        status, _queued = _post(
            server,
            "/v1/bridge/command",
            {
                "request_id": "request-http-apply",
                "command": "apply",
                "pane_instance_id": "pane-http-1",
                "host_generation": generation,
            },
        )
        assert status == 200
        _, delivered = _post(
            server,
            "/v1/bridge/host/wait",
            {
                "host_context_id": "host-context-http",
                "host_generation": generation,
                "timeout_seconds": 0,
            },
        )
        command = delivered["data"]["command"]
        assert command["schema_version"] == "wps-command-v2"
        assert command["authorization"]["config_version"] == "config-1"

        _post(
            server,
            "/v1/bridge/state",
            {
                "host_context_id": "host-context-http",
                "host_generation": generation,
                "state": {
                    "host_ready": True,
                    "status": "PASS",
                    "active_request": {
                        "request_id": "request-http-apply",
                        "command": "apply",
                        "request_status": "PASS",
                        "error_code": "",
                        "duration_ms": 321,
                    },
                },
            },
        )
        assert account.reports == [("request-http-apply", "success", 321, "")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_public_authorization_network_failure_does_not_enqueue_host_command(tmp_path):
    class OfflineAccountRuntime:
        def authorize_format(self, _request_id):
            raise PublicApiError(
                "WPS_PUBLIC_SERVER_UNAVAILABLE",
                "服务器无法连接",
                network=True,
            )

    application = server_module.WpsControlApplication(
        tmp_path,
        "test-token",
        OfflineAccountRuntime(),
    )
    registration = application.dispatch_bridge(
        "/v1/bridge/host/register",
        {"host_context_id": "host-context-offline"},
    )
    generation = registration["host_generation"]
    application.dispatch_bridge(
        "/v1/bridge/state",
        {
            "host_context_id": "host-context-offline",
            "host_generation": generation,
            "state": {"host_ready": True, "status": "READY"},
        },
    )

    with pytest.raises(
        PublicApiError,
        match="WPS_PUBLIC_SERVER_UNAVAILABLE",
    ):
        application.dispatch_bridge(
            "/v1/bridge/command",
            {
                "request_id": "request-offline-apply",
                "command": "apply",
                "pane_instance_id": "pane-offline",
                "host_generation": generation,
            },
        )

    assert application.host_bridge.wait_command(
        "host-context-offline",
        generation,
        timeout_seconds=0,
    ) == {"timed_out": True, "command": None}


def test_enqueue_error_is_not_replaced_when_public_result_reporting_fails(monkeypatch, tmp_path):
    class AccountRuntime:
        def authorize_format(self, request_id):
            return {
                "allowed": True,
                "request_id": request_id,
                "config_version": "config-1",
                "format_config": {"features": {}},
            }

        def report_format_result(self, *args):
            raise PublicApiError("WPS_PUBLIC_SERVER_UNAVAILABLE", "offline", network=True)

    application = server_module.WpsControlApplication(tmp_path, "test-token", AccountRuntime())
    registration = application.host_bridge.register_host("host-context-http")
    generation = registration["host_generation"]
    application.host_bridge.publish_state(
        "host-context-http", generation, {"host_ready": True, "status": "READY"}
    )
    monkeypatch.setattr(
        application.host_bridge,
        "enqueue_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(HostBridgeError("WPS_COMMAND_BUSY")),
    )

    with pytest.raises(HostBridgeError, match="WPS_COMMAND_BUSY"):
        application.dispatch_bridge(
            "/v1/bridge/command",
            {
                "request_id": "request-http-apply",
                "command": "apply",
                "pane_instance_id": "pane-http-1",
                "host_generation": generation,
            },
        )


def test_public_result_is_queued_without_changing_command_pass(tmp_path):
    class AccountRuntime:
        def __init__(self):
            self.reports = []

        def summary(self):
            return {
                "apply_available": True,
                "network_available": True,
                "pending_result_count": len(self.reports),
            }

        def authorize_format(self, request_id):
            return {
                "allowed": True,
                "request_id": request_id,
                "config_version": "config-1",
                "format_config": {"features": {}},
            }

        def report_format_result(self, *args):
            self.reports.append(args)
            return {"queued": True}

    account = AccountRuntime()
    server = server_module.create_server(tmp_path, "test-token", 0, account_runtime=account)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, registered = _post(server, "/v1/bridge/host/register", {"host_context_id": "host-context-http"})
        generation = registered["data"]["host_generation"]
        _post(
            server,
            "/v1/bridge/state",
            {
                "host_context_id": "host-context-http",
                "host_generation": generation,
                "state": {"host_ready": True, "status": "READY"},
            },
        )
        _post(
            server,
            "/v1/bridge/command",
            {
                "request_id": "request-http-apply",
                "command": "apply",
                "pane_instance_id": "pane-http-1",
                "host_generation": generation,
            },
        )
        status, published = _post(
            server,
            "/v1/bridge/state",
            {
                "host_context_id": "host-context-http",
                "host_generation": generation,
                "state": {
                    "host_ready": True,
                    "status": "PASS",
                    "active_request": {
                        "request_id": "request-http-apply",
                        "command": "apply",
                        "request_status": "PASS",
                        "duration_ms": 321,
                    },
                },
            },
        )
        assert status == 200
        status, state = _post(
            server,
            "/v1/bridge/state/wait",
            {"after_revision": 0, "host_generation": generation, "timeout_seconds": 0},
        )
        assert status == 200
        assert published["data"]["state_revision"] == state["data"]["state_revision"]
        assert state["data"]["state"]["status"] == "PASS"
        assert state["data"]["state"]["result_sync_status"] == "pending"
        assert state["data"]["state"]["result_sync_error_code"] == ""
        assert state["data"]["account"]["pending_result_count"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_stale_host_terminal_state_cannot_consume_apply_authorization(tmp_path):
    class AccountRuntime:
        def __init__(self):
            self.reports = []

        def authorize_format(self, request_id):
            return {
                "allowed": True,
                "request_id": request_id,
                "config_version": "config-1",
                "format_config": {"features": {}},
            }

        def report_format_result(self, *args):
            self.reports.append(args)

    account = AccountRuntime()
    application = server_module.WpsControlApplication(
        tmp_path, "test-token", account
    )
    registration = application.dispatch_bridge(
        "/v1/bridge/host/register", {"host_context_id": "host-context-a"}
    )
    generation = registration["host_generation"]
    application.dispatch_bridge(
        "/v1/bridge/state",
        {
            "host_context_id": "host-context-a",
            "host_generation": generation,
            "state": {"host_ready": True, "status": "READY"},
        },
    )
    application.dispatch_bridge(
        "/v1/bridge/command",
        {
            "request_id": "request-stale-host",
            "command": "apply",
            "pane_instance_id": "pane-1",
            "host_generation": generation,
        },
    )

    with pytest.raises(HostBridgeError, match="WPS_HOST_GENERATION_MISMATCH"):
        application.dispatch_bridge(
            "/v1/bridge/state",
            {
                "host_context_id": "host-context-a",
                "host_generation": generation + 1,
                "state": {
                    "host_ready": True,
                    "status": "PASS",
                    "active_request": {
                        "request_id": "request-stale-host",
                        "command": "apply",
                        "request_status": "PASS",
                    },
                },
            },
        )

    assert account.reports == []
    assert "request-stale-host" in application._authorized_requests


def test_host_replacement_queues_one_failure_for_the_displaced_apply(tmp_path):
    class AccountRuntime:
        def __init__(self):
            self.reports = []

        def authorize_format(self, request_id):
            return {
                "allowed": True,
                "request_id": request_id,
                "config_version": "config-1",
                "format_config": {"features": {}},
            }

        def report_format_result(self, *args):
            self.reports.append(args)

    account = AccountRuntime()
    application = server_module.WpsControlApplication(
        tmp_path, "test-token", account
    )
    registration = application.dispatch_bridge(
        "/v1/bridge/host/register", {"host_context_id": "host-context-a"}
    )
    generation = registration["host_generation"]
    application.dispatch_bridge(
        "/v1/bridge/state",
        {
            "host_context_id": "host-context-a",
            "host_generation": generation,
            "state": {"host_ready": True, "status": "READY"},
        },
    )
    application.dispatch_bridge(
        "/v1/bridge/command",
        {
            "request_id": "request-replaced-host",
            "command": "apply",
            "pane_instance_id": "pane-1",
            "host_generation": generation,
        },
    )

    application.dispatch_bridge(
        "/v1/bridge/host/register", {"host_context_id": "host-context-b"}
    )
    application.dispatch_bridge(
        "/v1/bridge/host/register", {"host_context_id": "host-context-c"}
    )

    assert account.reports == [
        (
            "request-replaced-host",
            "failed",
            account.reports[0][2],
            "WPS_HOST_CONTEXT_REPLACED",
        )
    ]
    assert "request-replaced-host" not in application._authorized_requests


def test_bridge_http_routes_bypass_command_monitor(tmp_path):
    server = server_module.create_server(tmp_path, "test-token", 0)
    monitor_calls = []
    server.command_monitor.submit = lambda *args, **kwargs: monitor_calls.append(
        (args, kwargs)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, registered = _post(
            server,
            "/v1/bridge/host/register",
            {"host_context_id": "host-context-http"},
        )
        assert status == 200
        generation = registered["data"]["host_generation"]

        status, published = _post(
            server,
            "/v1/bridge/state",
            {
                "host_context_id": "host-context-http",
                "host_generation": generation,
                "state": {"host_ready": True, "status": "READY"},
            },
        )
        assert status == 200

        status, state = _post(
            server,
            "/v1/bridge/state/wait",
            {
                "after_revision": 0,
                "host_generation": generation,
                "timeout_seconds": 0,
            },
        )
        assert status == 200
        assert state["data"]["state"]["status"] == "READY"
        assert state["data"]["account"]["pending_result_count"] == 0

        status, queued = _post(
            server,
            "/v1/bridge/command",
            {
                "request_id": "request-http-1",
                "command": "health",
                "pane_instance_id": "pane-http-1",
                "host_generation": generation,
            },
        )
        assert status == 200
        assert queued["data"]["request_id"] == "request-http-1"
        assert queued["data"]["state_revision"] > published["data"][
            "state_revision"
        ]

        status, command = _post(
            server,
            "/v1/bridge/host/wait",
            {
                "host_context_id": "host-context-http",
                "host_generation": generation,
                "timeout_seconds": 0,
            },
        )
        assert status == 200
        assert command["data"]["command"]["command"] == "health"
        assert published["data"]["state_revision"] > registered["data"][
            "state_revision"
        ]
        assert monitor_calls == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_control_client_disconnect_is_logged_once_without_second_response(
    tmp_path, monkeypatch
):
    events = []
    server = server_module.create_server(tmp_path, "test-token", 0)
    handler_type = server.RequestHandlerClass
    handler = object.__new__(handler_type)
    handler.path = "/v1/bridge/state/wait"
    handler.command = "POST"
    handler.headers = {}
    handler.send_response = lambda _status: None
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None

    class AbortedWriter:
        def write(self, _data):
            error = ConnectionAbortedError("client left")
            error.winerror = 10053
            raise error

    handler.wfile = AbortedWriter()
    monkeypatch.setattr(
        server_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields or {})
        ),
    )
    try:
        with pytest.raises(Exception) as raised:
            handler._json(200, {"ok": True})
        assert getattr(raised.value, "code", "") == "WPS_CONTROL_CLIENT_DISCONNECTED"
        assert [event for event, _fields in events] == ["control.client.disconnected"]
        assert events[0][1]["error_code"] == "WPS_CONTROL_CLIENT_DISCONNECTED"
        assert server_module._client_disconnected(OSError("disk failed")) is False
    finally:
        server.server_close()


def test_control_client_disconnect_during_headers_is_handled_for_get(
    tmp_path, monkeypatch
):
    events = []
    server = server_module.create_server(tmp_path, "test-token", 0)
    handler_type = server.RequestHandlerClass
    handler = object.__new__(handler_type)
    handler.path = "/v1/health"
    handler.command = "GET"
    handler.headers = {"Authorization": "Bearer test-token"}
    handler.request_version = "HTTP/1.1"
    handler.close_connection = False
    handler._origin_allowed = lambda: True
    handler.log_request = lambda *_args: None

    def abort_response(_status):
        error = ConnectionResetError("client left")
        error.winerror = 10054
        raise error

    handler.send_response = abort_response
    monkeypatch.setattr(
        server_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields or {})
        ),
    )
    try:
        handler.do_GET()
        assert [event for event, _fields in events].count(
            "control.client.disconnected"
        ) == 1
        assert "control.response.write_failed" not in {
            event for event, _fields in events
        }
    finally:
        server.server_close()


def test_control_response_write_failure_is_not_retried(tmp_path, monkeypatch):
    events = []
    writes = 0
    server = server_module.create_server(tmp_path, "test-token", 0)
    handler_type = server.RequestHandlerClass
    handler = object.__new__(handler_type)
    handler.path = "/v1/bridge/state/wait"
    handler.command = "POST"
    handler.headers = {"Authorization": "Bearer test-token"}
    handler.rfile = object()
    handler.send_response = lambda _status: None
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None
    handler._origin_allowed = lambda: True
    handler._read_body = lambda: {}

    class FailingWriter:
        def write(self, _data):
            nonlocal writes
            writes += 1
            raise OSError("disk failed")

    handler.wfile = FailingWriter()
    monkeypatch.setattr(
        server_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields or {})
        ),
    )
    try:
        with pytest.raises(OSError, match="disk failed"):
            handler.do_POST()
        assert writes == 1
        assert [event for event, _fields in events].count(
            "control.response.write_failed"
        ) == 1
    finally:
        server.server_close()


def test_bridge_http_rejects_auth_and_stale_generation(tmp_path):
    server = server_module.create_server(tmp_path, "test-token", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, unauthorized = _post(
            server,
            "/v1/bridge/command",
            {
                "request_id": "request-http-1",
                "command": "health",
                "pane_instance_id": "pane-http-1",
                "host_generation": 1,
            },
            token="wrong-token",
        )
        assert status == 401
        assert unauthorized["error_code"] == "WPS_CONTROL_UNAUTHORIZED"

        _, registered = _post(
            server,
            "/v1/bridge/host/register",
            {"host_context_id": "host-context-http"},
        )
        generation = registered["data"]["host_generation"]
        _post(
            server,
            "/v1/bridge/state",
            {
                "host_context_id": "host-context-http",
                "host_generation": generation,
                "state": {"host_ready": True, "status": "READY"},
            },
        )
        status, stale = _post(
            server,
            "/v1/bridge/command",
            {
                "request_id": "request-http-1",
                "command": "health",
                "pane_instance_id": "pane-http-1",
                "host_generation": generation + 1,
            },
        )
        assert status == 400
        assert stale["error_code"] == "WPS_HOST_GENERATION_MISMATCH"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_control_browser_origin_is_exactly_scoped(tmp_path):
    allowed = "http://127.0.0.1:3889"
    server = server_module.create_server(
        tmp_path, "test-token", 0, allowed_origin=allowed
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_address[1], timeout=2
        )
        connection.request(
            "OPTIONS",
            "/v1/log",
            headers={
                "Origin": allowed,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        response = connection.getresponse()
        assert response.status == 204
        assert response.getheader("Access-Control-Allow-Origin") == allowed
        response.read()
        connection.close()

        status, body = _post(
            server,
            "/v1/log",
            {"level": "INFO", "component": "test", "event": "origin.allowed", "message": "ok", "fields": {}},
            origin=allowed,
        )
        assert status == 200
        assert body["ok"] is True

        status, body = _post(
            server,
            "/v1/log",
            {"level": "INFO", "component": "test", "event": "origin.external", "message": "bad", "fields": {}},
            origin="https://external.example",
        )
        assert status == 403
        assert body["error_code"] == "WPS_CONTROL_ORIGIN_REJECTED"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_bridge_wait_timeout_does_not_emit_request_lifecycle_logs(
    monkeypatch, tmp_path
):
    events = []
    monkeypatch.setattr(
        server_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields or {})
        ),
    )
    server = server_module.create_server(tmp_path, "test-token", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, registered = _post(
            server,
            "/v1/bridge/host/register",
            {"host_context_id": "host-context-http"},
        )
        generation = registered["data"]["host_generation"]
        events.clear()
        status, result = _post(
            server,
            "/v1/bridge/host/wait",
            {
                "host_context_id": "host-context-http",
                "host_generation": generation,
                "timeout_seconds": 0.02,
            },
        )
        assert status == 200
        assert result["data"] == {"timed_out": True, "command": None}
        assert not any(
            event in {"request.start", "request.completed", "access"}
            for event, _fields in events
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
