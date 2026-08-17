"""Split regression tests from the former test_wps_app module (test_wps_launcher.py)."""

# ruff: noqa: F405



from apps.wps.tests.support.wps_app_support import *  # noqa: F401,F403,F405



def test_verify_files_requires_new_bootstrap_files(monkeypatch, tmp_path):
    monkeypatch.setattr(wps_main, "APP_ROOT", tmp_path)
    for relative in (
        "package.json",
        "manifest.xml",
        "ribbon.xml",
        "index.html",
        "main.js",
        "js/bootstrap-log.js",
            "js/bootstrap-complete.js",
            "js/ribbon.js",
            "images/taskpane.svg",
            "images/check.svg",
            "images/eye.svg",
            "images/eye-off.svg",
            "images/taskpane-icons.svg",
            "images/login-window.png",
            "images/user.svg",
            "host-runtime.js",
        "taskpane.html",
        "taskpane.js",
        "format-config.js",
        "format-settings.html",
        "format-settings.js",
        "format-settings.css",
        "client-config.json",
        "reader/reader-client.js",
        "reader/reader-ui.js",
        "reader/reader.css",
        "account_store.py",
        "account_runtime.py",
        "format_profile_store.py",
        "public_api.py",
        "user_messages.py",
        "login_window.py",
        "desktop_runtime.py",
        "windows_startup.py",
            "control/server.py",
            "control/host_bridge.py",
            "control/format_current_document.py",
            "control/add_letterhead.py",
        "control/reader_routes.py",
        "control/document_transaction.py",
        "control/logging_adapter.py",
        "control/recognize_document.py",
        "control/monitor.py",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        '{"devDependencies":{"wpsjs":"2.2.3"},'
        '"overrides":{"wpsjs-rpc-sdk-new":"1.1.0"}}',
        encoding="utf-8",
    )

    wps_main.verify_files()

def test_taskpane_scrolls_content_without_moving_header():
    source = (wps_main.APP_ROOT / "taskpane.html").read_text(encoding="utf-8")

    assert "html,body{height:100%;max-width:100%;overflow:hidden}" in source
    assert "body{display:flex;flex-direction:column" in source
    assert "header{flex:0 0 auto" in source
    assert "main{flex:1 1 auto;min-height:0;overflow-y:auto" in source
    assert '<header id="taskpane_header">' in source
    assert 'id="focus_document"' not in source
    assert "返回文档" not in source
    assert '<div class="brand-heading"><div class="brand-title">DocxTool WPS</div><div id="status" class="brand-status">连接中</div></div>' in source
    assert 'id="account"' not in source
    assert 'document.getElementById("status").textContent="错误"' in source
    assert 'document.getElementById("message").textContent="运行配置加载失败，请重新打开状态面板。"' in source
    assert 'document.getElementById("error").textContent="错误代码：WPS_RUNTIME_CONFIG_LOAD_FAILED"' in source
    assert '<main id="content">' in source
    assert 'fetch("./runtime/config"' in source
    assert 'load("./reader/reader-client.js?v=2")' in source
    assert 'load("./reader/reader-ui.js?v=7")' in source
    assert 'load("./format-config.js?v=2")' in source
    assert 'load("./taskpane.js?v=25")' in source

def test_taskpane_format_settings_opens_the_central_dialog():
    root = Path(__file__).resolve().parents[1]
    source = (root / "taskpane.html").read_text(encoding="utf-8")
    script = (root / "taskpane.js").read_text(encoding="utf-8")
    assert 'id="format_settings"' in source
    assert 'id="format_settings_panel"' not in source
    assert "format-settings.html" in script
    assert "ShowDialog" in script
    for resource in ("format-settings.html", "format-settings.js", "format-settings.css"):
        assert (root / resource).is_file()
    for hidden_field in (
        "lines_per_page", "chars_per_line", "grid_alignment",
        "space_before_line", "space_after_line",
    ):
        assert hidden_field not in source
    assert "ensureFormatProfiles" in script
    assert "currentFormatConfig" in script
    assert 'format_config: formatConfig' in script

def test_taskpane_format_action_buttons_use_the_requested_three_row_order_and_labels():
    source = (Path(__file__).resolve().parents[1] / "taskpane.html").read_text(encoding="utf-8")
    order = [
        'id="apply"', 'id="health"', 'id="preview"',
        'id="clear_preview"', 'id="add_letterhead"', 'id="format_settings"',
    ]
    positions = [source.index(item) for item in order]
    assert positions == sorted(positions)
    assert "预览格式" in source
    assert "预览排版" not in source
    assert ".format-actions #health" not in source

def test_start_handles_keyboard_interrupt_without_traceback(monkeypatch):
    events = []

    class FakeControlServer:
        def serve_forever(self, **_kwargs):
            pass

        def shutdown(self):
            events.append("control-shutdown")

        def server_close(self):
            events.append("control-close")

    class FakeWebServer:
        def serve_forever(self, **_kwargs):
            raise KeyboardInterrupt

        def server_close(self):
            events.append("web-close")

    class FakeThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            events.append("thread-start")

        def join(self, timeout):
            events.append(("join", timeout))

        def is_alive(self):
            return False

    class FakeAccountRuntime:
        def start(self):
            events.append("account-start")

        def stop(self):
            events.append("account-stop")

    monkeypatch.setattr(wps_main, "verify_files", lambda: None)
    monkeypatch.setattr(wps_main, "configure_wps_logging", lambda _root: None)
    monkeypatch.setattr(
        wps_main, "_start_control", lambda _port, _runtime: (FakeControlServer(), 45678)
    )
    monkeypatch.setattr(
        wps_main, "_start_web_server", lambda _port: (FakeWebServer(), 3889)
    )
    monkeypatch.setattr(
        wps_main, "_publish_addin", lambda port: events.append(("publish", port))
    )
    monkeypatch.setattr(wps_main.threading, "Thread", FakeThread)
    monkeypatch.setattr(wps_main, "clear_runtime_config", lambda: events.append("clear"))
    monkeypatch.setattr(wps_main, "log_event", lambda _level, _component, event, _message, _fields=None: events.append(event))

    wps_main.start(0, FakeAccountRuntime())

    assert "launcher.interrupt.received" in events
    assert ("publish", 3889) in events
    assert events.index("account-start") < events.index(("publish", 3889))
    assert "web-close" in events
    assert "control-shutdown" in events
    assert events[-1] == "launcher.session.stop"

def test_start_requires_account_runtime_before_any_service_side_effect(monkeypatch):
    calls = []

    monkeypatch.setattr(wps_main, "verify_files", lambda: calls.append("verify"))
    monkeypatch.setattr(
        wps_main, "configure_wps_logging", lambda _root: calls.append("logging")
    )
    monkeypatch.setattr(
        wps_main, "_start_control", lambda *_args: calls.append("control")
    )
    monkeypatch.setattr(
        wps_main, "_start_web_server", lambda *_args: calls.append("web")
    )
    monkeypatch.setattr(
        wps_main, "_publish_addin", lambda *_args: calls.append("publish")
    )
    monkeypatch.setattr(
        wps_main, "clear_runtime_config", lambda: calls.append("runtime-config")
    )
    monkeypatch.setattr(wps_main, "log_event", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="WPS_ACCOUNT_RUNTIME_REQUIRED"):
        wps_main.start(0)

    assert calls == []

@pytest.mark.parametrize(
    ("failed_stage", "expected_error", "expected_event", "expected_error_code"),
    [
        (
            "account-stop",
            "ACCOUNT_STOP_FAILED",
            "launcher.account_runtime.stop.failed",
            "WPS_ACCOUNT_RUNTIME_STOP_FAILED",
        ),
        (
            "web-close",
            "WEB_CLOSE_FAILED",
            "launcher.web.close.failed",
            "WPS_WEB_SERVER_CLOSE_FAILED",
        ),
        (
            "control-shutdown",
            "CONTROL_SHUTDOWN_FAILED",
            "launcher.control.shutdown.failed",
            "WPS_CONTROL_SERVER_SHUTDOWN_FAILED",
        ),
        (
            "control-close",
            "CONTROL_CLOSE_FAILED",
            "launcher.control.close.failed",
            "WPS_CONTROL_SERVER_CLOSE_FAILED",
        ),
        (
            "thread-join",
            "THREAD_JOIN_FAILED",
            "launcher.control.thread.join.failed",
            "WPS_CONTROL_THREAD_JOIN_FAILED",
        ),
        (
            "thread-state",
            "THREAD_STATE_FAILED",
            "launcher.control.thread.state_check.failed",
            "WPS_CONTROL_THREAD_STATE_CHECK_FAILED",
        ),
        (
            "thread-timeout",
            "WPS_CONTROL_THREAD_STOP_TIMEOUT",
            "launcher.control.thread.stop_timeout",
            "WPS_CONTROL_THREAD_STOP_TIMEOUT",
        ),
        (
            "runtime-config",
            "RUNTIME_CONFIG_FAILED",
            "launcher.runtime_config.cleanup.failed",
            "WPS_RUNTIME_CONFIG_CLEANUP_FAILED",
        ),
    ],
)
def test_start_attempts_all_cleanup_after_each_failure(
    monkeypatch,
    failed_stage,
    expected_error,
    expected_event,
    expected_error_code,
):
    events = []
    log_records = []

    def step(name):
        events.append(name)
        if name == failed_stage:
            raise RuntimeError(expected_error)

    class FakeAccountRuntime:
        def start(self):
            events.append("account-start")

        def stop(self):
            step("account-stop")

    class FakeControlServer:
        def serve_forever(self, **_kwargs):
            pass

        def shutdown(self):
            step("control-shutdown")

        def server_close(self):
            step("control-close")

    class FakeWebServer:
        def serve_forever(self, **_kwargs):
            raise KeyboardInterrupt

        def server_close(self):
            step("web-close")

    class FakeThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            events.append("thread-start")

        def join(self, timeout):
            events.append(("thread-join-timeout", timeout))
            step("thread-join")

        def is_alive(self):
            if failed_stage == "thread-timeout":
                events.append("thread-state")
                return True
            step("thread-state")
            return False

    monkeypatch.setattr(wps_main, "verify_files", lambda: None)
    monkeypatch.setattr(wps_main, "configure_wps_logging", lambda _root: None)
    monkeypatch.setattr(
        wps_main,
        "_start_control",
        lambda _port, _runtime: (FakeControlServer(), 45678),
    )
    monkeypatch.setattr(
        wps_main, "_start_web_server", lambda _port: (FakeWebServer(), 3889)
    )
    monkeypatch.setattr(wps_main, "_publish_addin", lambda _port: None)
    monkeypatch.setattr(wps_main.threading, "Thread", FakeThread)
    monkeypatch.setattr(wps_main, "clear_runtime_config", lambda: step("runtime-config"))
    monkeypatch.setattr(
        wps_main,
        "log_event",
        lambda _level, _component, event, _message, fields=None: (
            events.append(event),
            log_records.append((event, fields or {})),
        ),
    )

    with pytest.raises(RuntimeError, match=expected_error):
        wps_main.start(0, FakeAccountRuntime())

    assert expected_event in events
    assert (expected_event, expected_error_code) in [
        (event, fields.get("error_code")) for event, fields in log_records
    ]
    for cleanup_stage in (
        "account-stop",
        "web-close",
        "control-shutdown",
        "control-close",
        "thread-join",
        "runtime-config",
    ):
        assert cleanup_stage in events

def test_start_raises_first_cleanup_failure_and_continues(monkeypatch):
    events = []

    class FakeControlServer:
        def serve_forever(self, **_kwargs):
            pass

        def shutdown(self):
            events.append("control-shutdown")
            raise RuntimeError("CONTROL_SHUTDOWN_SECOND")

        def server_close(self):
            events.append("control-close")
            raise RuntimeError("CONTROL_CLOSE_THIRD")

    class FakeWebServer:
        def serve_forever(self, **_kwargs):
            raise KeyboardInterrupt

        def server_close(self):
            events.append("web-close")
            raise RuntimeError("WEB_CLOSE_FIRST")

    class FakeThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

        def join(self, timeout):
            events.append(("thread-join", timeout))

        def is_alive(self):
            return False

    class FakeAccountRuntime:
        def start(self):
            return None

        def stop(self):
            return None

    monkeypatch.setattr(wps_main, "verify_files", lambda: None)
    monkeypatch.setattr(wps_main, "configure_wps_logging", lambda _root: None)
    monkeypatch.setattr(
        wps_main, "_start_control", lambda _port, _runtime: (FakeControlServer(), 45678)
    )
    monkeypatch.setattr(
        wps_main, "_start_web_server", lambda _port: (FakeWebServer(), 3889)
    )
    monkeypatch.setattr(wps_main, "_publish_addin", lambda _port: None)
    monkeypatch.setattr(wps_main.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        wps_main, "clear_runtime_config", lambda: events.append("runtime-config")
    )
    monkeypatch.setattr(wps_main, "log_event", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="WEB_CLOSE_FIRST"):
        wps_main.start(0, FakeAccountRuntime())

    assert events == [
        "web-close",
        "control-shutdown",
        "control-close",
        ("thread-join", 3),
        "runtime-config",
    ]

def test_start_preserves_business_error_when_cleanup_also_fails(monkeypatch):
    events = []

    class FakeControlServer:
        def serve_forever(self, **_kwargs):
            pass

        def shutdown(self):
            events.append("control-shutdown")
            raise RuntimeError("CLEANUP_FAILED")

        def server_close(self):
            events.append("control-close")

    class FakeWebServer:
        def serve_forever(self, **_kwargs):
            raise ValueError("BUSINESS_FAILED")

        def server_close(self):
            events.append("web-close")

    class FakeThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

        def join(self, timeout):
            events.append(("thread-join", timeout))

        def is_alive(self):
            return False

    class FakeAccountRuntime:
        def start(self):
            return None

        def stop(self):
            return None

    monkeypatch.setattr(wps_main, "verify_files", lambda: None)
    monkeypatch.setattr(wps_main, "configure_wps_logging", lambda _root: None)
    monkeypatch.setattr(
        wps_main, "_start_control", lambda _port, _runtime: (FakeControlServer(), 45678)
    )
    monkeypatch.setattr(
        wps_main, "_start_web_server", lambda _port: (FakeWebServer(), 3889)
    )
    monkeypatch.setattr(wps_main, "_publish_addin", lambda _port: None)
    monkeypatch.setattr(wps_main.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        wps_main, "clear_runtime_config", lambda: events.append("runtime-config")
    )
    monkeypatch.setattr(wps_main, "log_event", lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="BUSINESS_FAILED"):
        wps_main.start(0, FakeAccountRuntime())

    assert events == [
        "web-close",
        "control-shutdown",
        "control-close",
        ("thread-join", 3),
        "runtime-config",
    ]

def test_runtime_config_is_kept_in_launcher_memory():
    wps_main.write_runtime_config(9527, "test-token")
    assert wps_main._RUNTIME_CONFIG == {
        "controlBaseUrl": "http://127.0.0.1:9527",
        "sessionToken": "test-token",
    }
    wps_main.clear_runtime_config()
    assert wps_main._RUNTIME_CONFIG == {}

def test_wps_static_server_serves_plugin_without_launching_wps(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("WPS_BACKGROUND_READY", encoding="utf-8")
    monkeypatch.setattr(wps_main, "APP_ROOT", tmp_path)
    monkeypatch.setattr(wps_main, "log_event", lambda *_args, **_kwargs: None)

    wps_main.write_runtime_config(9527, "test-token")
    server, port = wps_main._start_web_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", "/index.html")
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Cache-Control") == (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        assert response.getheader("Pragma") == "no-cache"
        assert response.getheader("Expires") == "0"
        assert response.read().decode("utf-8") == "WPS_BACKGROUND_READY"
        connection.request("GET", "/runtime/config")
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type").startswith("application/json")
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        assert response.getheader("Access-Control-Allow-Origin") is None
        assert json.loads(response.read()) == {
            "controlBaseUrl": "http://127.0.0.1:9527",
            "sessionToken": "test-token",
        }
        connection.request("GET", "/runtime/runtime-config.js")
        assert connection.getresponse().status == 404
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

def test_wps_web_server_uses_stable_addin_origin():
    assert wps_main.DEFAULT_WEB_PORT == 3889
    assert wps_main._WpsStaticHttpServer.allow_reuse_address is False

def test_wps_web_server_reports_the_fixed_port_conflict(monkeypatch):
    def address_in_use(*_args, **_kwargs):
        raise OSError(errno.EADDRINUSE, "address already in use")

    monkeypatch.setattr(wps_main, "_WpsStaticHttpServer", address_in_use)
    monkeypatch.setattr(wps_main, "_stop_previous_docxtool_service", lambda _port: False)
    monkeypatch.setattr(wps_main, "log_event", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="WPS_WEB_SERVER_PORT_IN_USE") as exc_info:
        wps_main._start_web_server(wps_main.DEFAULT_WEB_PORT)

    assert isinstance(exc_info.value.__cause__, OSError)

def test_wps_web_server_retries_after_stopping_verified_previous_service(monkeypatch):
    attempts = []
    stopped = []

    class FakeServer:
        server_address = ("127.0.0.1", 3889)

    def create_server(*_args, **_kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError(errno.EADDRINUSE, "address already in use")
        return FakeServer()

    monkeypatch.setattr(wps_main, "_WpsStaticHttpServer", create_server)
    monkeypatch.setattr(
        wps_main,
        "_stop_previous_docxtool_service",
        lambda port: stopped.append(port) or True,
    )
    monkeypatch.setattr(wps_main, "log_event", lambda *_args, **_kwargs: None)

    _server, port = wps_main._start_web_server(wps_main.DEFAULT_WEB_PORT)

    assert port == 3889
    assert len(attempts) == 2
    assert stopped == [3889]

def test_publish_addin_updates_only_docxtool_entry(tmp_path, monkeypatch):
    publish_path = tmp_path / "publish.xml"
    publish_path.write_text(
        "<jsplugins>"
        '<jspluginonline name="another-addin" type="wps" url="http://example.test/" />'
        '<jspluginonline name="docxtool-wps-trial" type="wps" url="http://127.0.0.1:3890/" />'
        '<jspluginonline name="docxtool-wps-app" type="wps" url="http://127.0.0.1:3999/" />'
        '<jspluginonline name="docxtool-wps-app" type="wps" url="http://127.0.0.1:4000/" />'
        "</jsplugins>",
        encoding="utf-8",
    )
    monkeypatch.setattr(wps_main, "_publish_xml_path", lambda: publish_path)
    monkeypatch.setattr(wps_main, "log_event", lambda *_args, **_kwargs: None)

    wps_main._publish_addin(3889)

    root = ElementTree.parse(publish_path).getroot()
    entries = list(root)
    assert any(node.get("name") == "another-addin" for node in entries)
    assert not any(node.get("name") == "docxtool-wps-trial" for node in entries)
    docxtool = [node for node in entries if node.get("name") == "docxtool-wps-app"]
    assert len(docxtool) == 1
    assert docxtool[0].attrib == {
        "name": "docxtool-wps-app",
        "type": "wps",
        "url": "http://127.0.0.1:3889/",
        "debug": "",
        "enable": "enable_dev",
        "install": "null",
    }

def test_unpublish_addin_removes_only_docxtool_entries(tmp_path, monkeypatch):
    publish_path = tmp_path / "publish.xml"
    publish_path.write_text(
        "<jsplugins>"
        '<jspluginonline name="another-addin" type="wps" url="http://example.test/" />'
        '<jspluginonline name="docxtool-wps-trial" type="wps" url="http://127.0.0.1:3890/" />'
        '<jspluginonline name="docxtool-wps-app" type="wps" url="http://127.0.0.1:3889/" />'
        '<jspluginonline name="docxtool-wps-app" type="wps" url="http://127.0.0.1:3999/" />'
        "</jsplugins>",
        encoding="utf-8",
    )
    monkeypatch.setattr(wps_main, "_publish_xml_path", lambda: publish_path)
    monkeypatch.setattr(wps_main, "log_event", lambda *_args, **_kwargs: None)

    wps_main._unpublish_addin()

    entries = list(ElementTree.parse(publish_path).getroot())
    assert [node.get("name") for node in entries] == ["another-addin"]

def test_unpublish_addin_reports_atomic_write_failure(tmp_path, monkeypatch):
    publish_path = tmp_path / "publish.xml"
    publish_path.write_text(
        "<jsplugins>"
        '<jspluginonline name="docxtool-wps-app" type="wps" url="http://127.0.0.1:3889/" />'
        "</jsplugins>",
        encoding="utf-8",
    )
    monkeypatch.setattr(wps_main, "_publish_xml_path", lambda: publish_path)
    monkeypatch.setattr(wps_main, "log_event", lambda *_args, **_kwargs: None)

    def fail_write(self, *_args, **_kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(ElementTree.ElementTree, "write", fail_write)

    with pytest.raises(RuntimeError, match="WPS_UNPUBLISH_WRITE_FAILED") as exc_info:
        wps_main._unpublish_addin()

    assert isinstance(exc_info.value.__cause__, OSError)

@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["main.py"], "start"),
        (["main.py", "start"], "start"),
        (["main.py", "control"], "control"),
        (["main.py", "verify"], "verify"),
    ],
)
def test_main_action_defaults_and_routes(monkeypatch, argv, expected):
    calls = []

    def fake_desktop(port, *, force_login=False):
        calls.append(("start", port, force_login))
        return 0

    def fake_control(port):
        calls.append(("control", port))

    def fake_verify():
        calls.append(("verify",))

    monkeypatch.setattr(wps_main, "run_desktop", fake_desktop)
    monkeypatch.setattr(wps_main, "control_only", fake_control)
    monkeypatch.setattr(wps_main, "verify_files", fake_verify)
    monkeypatch.setattr(wps_main.sys, "argv", argv)
    assert wps_main.main() == 0
    if expected == "start":
        assert calls == [("start", wps_main.DEFAULT_PORT, False)]
    elif expected == "control":
        assert calls == [("control", wps_main.DEFAULT_PORT)]
    else:
        assert calls == [("verify",)]

def test_main_closing_login_window_stops_before_start(monkeypatch):
    application = type("Application", (), {})()
    instance = type("Instance", (), {"acquire": lambda self: True})()
    calls = []
    monkeypatch.setattr("apps.wps.desktop_runtime.ensure_application", lambda: application)
    monkeypatch.setattr("apps.wps.desktop_runtime.SingleInstance", lambda: instance)
    monkeypatch.setattr("apps.wps.desktop_runtime.shift_pressed", lambda: False)
    monkeypatch.setattr(wps_main, "WpsPublicApi", lambda: "api")
    monkeypatch.setattr(wps_main, "_unpublish_addin", lambda: calls.append("unpublish"))
    monkeypatch.setattr(
        "apps.wps.desktop_runtime.DesktopController",
        lambda **_kwargs: pytest.fail("DesktopController must not be created"),
    )
    monkeypatch.setattr(
        wps_main,
        "resolve_startup_account",
        lambda _api, force_login=False: {},
    )

    assert wps_main.run_desktop(wps_main.DEFAULT_PORT) == 0
    assert calls == ["unpublish"]


def test_single_instance_conflict_is_shown_without_an_unhandled_exception(monkeypatch):
    application = type("Application", (), {})()
    calls = []

    class Instance:
        def acquire(self):
            raise RuntimeError("WPS_SINGLE_INSTANCE_LISTEN_FAILED")

    monkeypatch.setattr("apps.wps.desktop_runtime.ensure_application", lambda: application)
    monkeypatch.setattr("apps.wps.desktop_runtime.SingleInstance", Instance)
    monkeypatch.setattr(
        "apps.wps.desktop_runtime.show_startup_error",
        lambda exc: calls.append(str(exc)),
    )

    assert wps_main.run_desktop(wps_main.DEFAULT_PORT) == 1
    assert calls == ["WPS_SINGLE_INSTANCE_LISTEN_FAILED"]


def test_frozen_launcher_migrates_legacy_startup_before_login(monkeypatch):
    application = type("Application", (), {})()
    instance = type("Instance", (), {"acquire": lambda self: True})()
    calls = []
    monkeypatch.setattr("apps.wps.desktop_runtime.ensure_application", lambda: application)
    monkeypatch.setattr("apps.wps.desktop_runtime.SingleInstance", lambda: instance)
    monkeypatch.setattr(wps_main, "FROZEN", True)
    monkeypatch.setattr(wps_main, "configure_wps_logging", lambda _root: calls.append("logging"))
    monkeypatch.setattr(
        wps_main.windows_startup,
        "migrate_legacy_registration",
        lambda: calls.append("migrate") or True,
    )
    monkeypatch.setattr(wps_main, "log_event", lambda *_args, **_kwargs: calls.append("log"))
    monkeypatch.setattr(wps_main, "_unpublish_addin", lambda: calls.append("unpublish"))
    monkeypatch.setattr(wps_main, "WpsPublicApi", lambda: "api")
    monkeypatch.setattr(wps_main, "resolve_startup_account", lambda *_args, **_kwargs: {})

    assert wps_main.run_desktop(wps_main.DEFAULT_PORT) == 0
    assert calls[:4] == ["logging", "migrate", "log", "unpublish"]
    assert calls[-1] == "log"  # 登录窗口关闭事件。

def test_main_starts_services_only_after_login_returns_an_account(monkeypatch):
    calls = []

    class Signal:
        def connect(self, callback):
            calls.append(("connect", callback))

    class Instance:
        show_requested = Signal()

        def acquire(self):
            return True

    class Application:
        def exec_(self):
            calls.append("exec")
            return 0

    class Controller:
        restart_login_requested = False

        def __init__(self, **kwargs):
            calls.append(("controller", kwargs["account_runtime"].summary()["username"]))

        def show_settings(self):
            return None

        def start(self):
            calls.append("start")

        def shutdown(self):
            calls.append("shutdown")

    monkeypatch.setattr("apps.wps.desktop_runtime.ensure_application", Application)
    monkeypatch.setattr("apps.wps.desktop_runtime.SingleInstance", Instance)
    monkeypatch.setattr("apps.wps.desktop_runtime.shift_pressed", lambda: False)
    monkeypatch.setattr("apps.wps.desktop_runtime.DesktopController", Controller)
    monkeypatch.setattr(wps_main, "WpsPublicApi", lambda: "api")
    monkeypatch.setattr(
        wps_main,
        "resolve_startup_account",
        lambda _api, force_login=False: {"username": "User01"},
    )
    monkeypatch.setattr(wps_main, "_unpublish_addin", lambda: calls.append("unpublish"))

    assert wps_main.run_desktop(wps_main.DEFAULT_PORT) == 0
    assert ("controller", "User01") in calls
    assert "start" in calls
    assert "shutdown" in calls
    assert calls.count("unpublish") == 1

def test_logout_stops_services_unpublishes_then_reopens_login(monkeypatch):
    calls = []

    class Signal:
        def connect(self, _callback):
            calls.append("connect")

    class Instance:
        show_requested = Signal()

        def acquire(self):
            return True

        def close(self):
            calls.append("instance-close")

    class Application:
        def exec_(self):
            calls.append("exec")
            return 0

    class Controller:
        restart_login_requested = True

        def __init__(self, **_kwargs):
            calls.append("controller")

        def show_settings(self):
            return None

        def start(self):
            calls.append("start")

        def shutdown(self):
            calls.append("shutdown")

    monkeypatch.setattr("apps.wps.desktop_runtime.ensure_application", Application)
    monkeypatch.setattr("apps.wps.desktop_runtime.SingleInstance", Instance)
    monkeypatch.setattr("apps.wps.desktop_runtime.shift_pressed", lambda: False)
    monkeypatch.setattr("apps.wps.desktop_runtime.DesktopController", Controller)
    monkeypatch.setattr(wps_main, "WpsPublicApi", lambda: "api")
    monkeypatch.setattr(
        wps_main,
        "resolve_startup_account",
        lambda _api, force_login=False: {"username": "User01"},
    )
    monkeypatch.setattr(wps_main, "_unpublish_addin", lambda: calls.append("unpublish"))
    monkeypatch.setattr(
        wps_main.windows_startup, "launch", lambda argument: calls.append(("launch", argument))
    )

    assert wps_main.run_desktop(wps_main.DEFAULT_PORT) == 0
    unpublish_positions = [index for index, value in enumerate(calls) if value == "unpublish"]
    assert len(unpublish_positions) == 2
    assert calls.index("shutdown") < unpublish_positions[1] < calls.index("instance-close")
    assert ("launch", "--force-login") in calls
