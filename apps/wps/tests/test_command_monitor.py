from __future__ import annotations

import threading

import pytest

from apps.wps.control.monitor import CommandMonitor, CommandMonitorError


def test_monitor_executes_business_commands_on_its_single_thread():
    caller_thread = threading.get_ident()
    executed = []

    def dispatch(path, body, request_id=""):
        executed.append((threading.get_ident(), path, body, request_id))
        return {"status": "ok"}

    monitor = CommandMonitor(dispatch)
    monitor.start()
    try:
        result = monitor.submit("/v1/recognize", {"source_path": "ignored"}, "request-1")
    finally:
        monitor.stop()

    assert result == {"status": "ok"}
    assert len(executed) == 1
    assert executed[0][0] != caller_thread
    assert executed[0][1:] == (
        "/v1/recognize",
        {"source_path": "ignored"},
        "request-1",
    )


def test_monitor_rejects_second_command_while_first_is_running():
    entered = threading.Event()
    release = threading.Event()

    def dispatch(_path, _body, request_id=""):
        entered.set()
        assert release.wait(timeout=5)
        return {"request_id": request_id}

    monitor = CommandMonitor(dispatch)
    monitor.start()
    first_result = []
    first = threading.Thread(
        target=lambda: first_result.append(
            monitor.submit("/v1/recognize", {}, "request-1")
        )
    )
    first.start()
    assert entered.wait(timeout=5)
    try:
        with pytest.raises(CommandMonitorError) as exc_info:
            monitor.submit("/v1/recognize", {}, "request-2")
        assert exc_info.value.code == "WPS_COMMAND_BUSY"
    finally:
        release.set()
        first.join(timeout=5)
        monitor.stop()

    assert first_result == [{"request_id": "request-1"}]


def test_monitor_rejects_commands_before_start_and_after_stop():
    monitor = CommandMonitor(lambda *_args, **_kwargs: {})

    with pytest.raises(CommandMonitorError) as before_start:
        monitor.submit("/v1/recognize", {}, "request-1")
    assert before_start.value.code == "WPS_MONITOR_NOT_RUNNING"

    monitor.start()
    monitor.stop()

    with pytest.raises(CommandMonitorError) as after_stop:
        monitor.submit("/v1/recognize", {}, "request-2")
    assert after_stop.value.code == "WPS_MONITOR_NOT_RUNNING"


def test_monitor_preserves_dispatch_error_and_accepts_next_command():
    calls = []

    def dispatch(_path, _body, request_id=""):
        calls.append(request_id)
        if request_id == "request-fail":
            raise ValueError("WPS_HOST_SNAPSHOT_REQUIRED")
        return {"status": "ok"}

    monitor = CommandMonitor(dispatch)
    monitor.start()
    try:
        with pytest.raises(ValueError, match="WPS_HOST_SNAPSHOT_REQUIRED"):
            monitor.submit("/v1/recognize/bind", {}, "request-fail")
        assert monitor.submit("/v1/recognize", {}, "request-pass") == {
            "status": "ok"
        }
    finally:
        monitor.stop()

    assert calls == ["request-fail", "request-pass"]


def test_monitor_crash_unblocks_waiting_command_without_restart():
    def dispatch(_path, _body, _request_id):
        raise KeyboardInterrupt()

    monitor = CommandMonitor(dispatch)
    monitor.start()
    try:
        with pytest.raises(CommandMonitorError) as exc_info:
            monitor.submit("/v1/recognize", {}, "request-crash")
        assert exc_info.value.code == "WPS_MONITOR_THREAD_CRASHED"
        assert monitor.running is False
    finally:
        monitor.stop()
