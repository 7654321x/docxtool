import http.client
import json
import threading
import time
from typing import Tuple

import pytest

from apps.wps.control.host_bridge import HostBridge, HostBridgeError
from apps.wps.control import server as server_module


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
            "schema_version": "wps-command-v1",
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


def _post(server, path, payload, token="test-token"):
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=2
    )
    try:
        connection.request(
            "POST",
            path,
            body=json.dumps(payload),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "X-DocxTool-Request-Id": "bridge-request-1",
            },
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        assert response.getheader("X-DocxTool-Request-Id") == "bridge-request-1"
        return response.status, body
    finally:
        connection.close()


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
