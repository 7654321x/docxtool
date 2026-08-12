from concurrent.futures import ThreadPoolExecutor
import logging
import sqlite3
import threading

from argon2 import extract_parameters
from argon2.low_level import Type
import pytest

from docxtool.auth.passwords import verify_password
from docxtool.wps_server import database
from docxtool.wps_server import service as service_module
from docxtool.wps_server.auth import WpsAuthError, authenticated_session, bearer_token
from docxtool.wps_server.service import WpsServiceError, heartbeat, login_user, register_user
from docxtool.wps_server.validation import WpsValidationError, validate_password, validate_username


def _setup(tmp_path):
    path = tmp_path / "wps_plugin.db"

    def connect():
        return database.connect(path)

    lock = threading.Lock()
    database.initialize_database(connect, lock)
    return path, connect, lock


def _device():
    return {
        "device_key": "device-key-001",
        "device_name": "测试电脑",
        "platform": "windows",
        "app_version": "5.1",
    }


def _register(connect, lock, now=1000):
    return register_user(
        {"username": "User01", "password": "Pass01", "device": _device()},
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: now,
        config_version="test-config",
    )


def test_register_and_login_sessions_are_exactly_seven_days_and_username_is_case_insensitive(tmp_path):
    _path, connect, lock = _setup(tmp_path)
    registered = _register(connect, lock)

    assert registered["session_expires_at"] - registered["session_created_at"] == 604800
    assert set(registered["user"]) == {"id", "username", "status"}
    logged_in = login_user(
        {"username": "user01", "password": "Pass01", "device": _device()},
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1100,
        config_version="test-config",
    )
    assert logged_in["session_expires_at"] - logged_in["session_created_at"] == 604800

    with pytest.raises(WpsServiceError) as exc_info:
        register_user(
            {"username": "user01", "password": "Pass02", "device": _device()},
            connect_func=connect,
            sql_lock=lock,
            client_ip="127.0.0.1",
            now_func=lambda: 1001,
            config_version="test-config",
        )
    assert exc_info.value.code == "USERNAME_TAKEN"


def test_registration_rejects_the_removed_display_name_field(tmp_path):
    _path, connect, lock = _setup(tmp_path)

    with pytest.raises(WpsValidationError) as exc_info:
        register_user(
            {
                "username": "User01",
                "password": "Pass01",
                "display_name": "用户一",
                "device": _device(),
            },
            connect_func=connect,
            sql_lock=lock,
            client_ip="127.0.0.1",
            now_func=lambda: 1000,
            config_version="test-config",
        )

    assert exc_info.value.code == "WPS_UNKNOWN_FIELD"


def test_registration_and_login_accept_a_legacy_display_name_column(tmp_path):
    _path, connect, lock = _setup(tmp_path)
    with lock:
        conn = connect()
        try:
            conn.execute(
                "ALTER TABLE wps_users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''"
            )
            conn.commit()
        finally:
            conn.close()

    registered = _register(connect, lock)
    logged_in = login_user(
        {"username": "User01", "password": "Pass01", "device": _device()},
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1100,
        config_version="test-config",
    )

    assert registered["user"]["username"] == "User01"
    assert logged_in["user"]["username"] == "User01"
    assert "display_name" not in logged_in["user"]


@pytest.mark.parametrize(
    ("validator", "value", "code"),
    [
        (validate_username, "A1b", "USERNAME_LENGTH_INVALID"),
        (validate_username, "User_1", "USERNAME_CHARSET_INVALID"),
        (validate_username, "UserOnly", "USERNAME_COMPOSITION_INVALID"),
        (validate_password, "A1b", "PASSWORD_LENGTH_INVALID"),
        (validate_password, "Pass_1", "PASSWORD_CHARSET_INVALID"),
        (validate_password, "123456", "PASSWORD_COMPOSITION_INVALID"),
    ],
)
def test_wps_account_rules_are_enforced_by_server_validators(validator, value, code):
    with pytest.raises(WpsValidationError) as exc_info:
        validator(value)
    assert exc_info.value.code == code


def test_concurrent_case_insensitive_registration_creates_one_user(tmp_path):
    path, connect, lock = _setup(tmp_path)

    def register(username):
        try:
            register_user(
                {"username": username, "password": "Pass01", "device": _device()},
                connect_func=connect,
                sql_lock=lock,
                client_ip="127.0.0.1",
                now_func=lambda: 1000,
                config_version="test-config",
            )
            return "created"
        except WpsServiceError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register, ("User01", "user01")))

    assert sorted(results) == ["USERNAME_TAKEN", "created"]
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wps_users").fetchone()[0] == 1


def test_login_reuses_device_and_invalid_credentials_share_one_error(tmp_path):
    path, connect, lock = _setup(tmp_path)
    _register(connect, lock)

    for username, password in (("Missing1", "Pass01"), ("User01", "Wrong01"), ("bad", "bad")):
        with pytest.raises(WpsServiceError) as exc_info:
            login_user(
                {"username": username, "password": password, "device": _device()},
                connect_func=connect,
                sql_lock=lock,
                client_ip="127.0.0.1",
                now_func=lambda: 1100,
                config_version="test-config",
            )
        assert exc_info.value.code == "INVALID_CREDENTIALS"

    login_user(
        {"username": "user01", "password": "Pass01", "device": _device()},
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1200,
        config_version="test-config",
    )
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wps_devices").fetchone()[0] == 1


def test_missing_account_uses_a_valid_argon2_dummy_hash():
    valid, _needs_rehash = verify_password(
        service_module._DUMMY_PASSWORD_HASH,
        service_module._DUMMY_PASSWORD,
    )
    assert valid is True


def test_wps_argon2id_parameters_are_unchanged():
    parameters = extract_parameters(service_module._DUMMY_PASSWORD_HASH)

    assert parameters.type == Type.ID
    assert parameters.memory_cost == 65536
    assert parameters.time_cost == 3
    assert parameters.parallelism == 4


def test_wps_argon2_process_limit_allows_two_operations_and_queues_the_third(monkeypatch):
    release = threading.Event()
    two_entered = threading.Event()
    all_attempted = threading.Event()
    state_lock = threading.Lock()
    active = 0
    entered = 0
    attempted = 0
    peak = 0

    def controlled_operation():
        nonlocal active, entered, peak
        with state_lock:
            active += 1
            entered += 1
            peak = max(peak, active)
            if entered == 2:
                two_entered.set()
        assert release.wait(5)
        with state_lock:
            active -= 1

    def controlled_hash(_password):
        controlled_operation()
        return "controlled-hash"

    def controlled_verify(_password_hash, _password):
        controlled_operation()
        return True, False

    def invoke(operation):
        nonlocal attempted
        with state_lock:
            attempted += 1
            if attempted == 3:
                all_attempted.set()
        return operation()

    monkeypatch.setattr(service_module, "_WPS_ARGON2_LIMIT", threading.BoundedSemaphore(2))
    monkeypatch.setattr(service_module, "hash_password", controlled_hash)
    monkeypatch.setattr(service_module, "verify_password", controlled_verify)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(invoke, lambda: service_module._hash_wps_password("Pass01")),
            pool.submit(
                invoke,
                lambda: service_module._verify_wps_password("digest", "Pass01"),
            ),
            pool.submit(invoke, lambda: service_module._hash_wps_password("Pass02")),
        ]
        try:
            assert all_attempted.wait(2)
            assert two_entered.wait(2)
            with state_lock:
                assert active == 2
                assert entered == 2
                assert peak == 2
        finally:
            release.set()
        assert [future.result(timeout=5) for future in futures] == [
            "controlled-hash",
            (True, False),
            "controlled-hash",
        ]

    assert entered == 3
    assert peak == 2


def test_registration_real_missing_and_rehash_paths_share_the_wps_argon2_limit(
    tmp_path,
    monkeypatch,
):
    path, connect, lock = _setup(tmp_path)
    operations = []
    needs_rehash = False
    hash_count = 0

    class TrackingLimit:
        def __init__(self):
            self.active = 0
            self.entries = 0

        def __enter__(self):
            self.active += 1
            self.entries += 1

        def __exit__(self, exc_type, exc_value, traceback):
            self.active -= 1

    limit = TrackingLimit()

    def fake_hash(password):
        nonlocal hash_count
        assert limit.active == 1
        hash_count += 1
        digest = f"controlled-hash-{hash_count}"
        operations.append(("hash", password, digest))
        return digest

    def fake_verify(password_hash, password):
        assert limit.active == 1
        operations.append(("verify", password_hash, password))
        if password_hash == service_module._DUMMY_PASSWORD_HASH:
            return False, False
        return True, needs_rehash

    monkeypatch.setattr(service_module, "_WPS_ARGON2_LIMIT", limit)
    monkeypatch.setattr(service_module, "hash_password", fake_hash)
    monkeypatch.setattr(service_module, "verify_password", fake_verify)

    _register(connect, lock)
    login_user(
        {"username": "User01", "password": "Pass01", "device": _device()},
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1100,
        config_version="test-config",
    )
    with pytest.raises(WpsServiceError, match="INVALID_CREDENTIALS"):
        login_user(
            {"username": "Missing1", "password": "Pass01", "device": _device()},
            connect_func=connect,
            sql_lock=lock,
            client_ip="127.0.0.1",
            now_func=lambda: 1200,
            config_version="test-config",
        )
    needs_rehash = True
    login_user(
        {"username": "User01", "password": "Pass01", "device": _device()},
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1300,
        config_version="test-config",
    )

    assert [operation[0] for operation in operations] == [
        "hash",
        "verify",
        "verify",
        "verify",
        "hash",
    ]
    assert operations[2][1] == service_module._DUMMY_PASSWORD_HASH
    assert limit.entries == 5
    assert limit.active == 0
    with sqlite3.connect(str(path)) as conn:
        stored_hash = conn.execute(
            "SELECT password_hash FROM wps_users WHERE username_norm='user01'"
        ).fetchone()[0]
    assert stored_hash == "controlled-hash-2"


def test_password_rehash_is_computed_before_the_sqlite_write_lock(tmp_path, monkeypatch):
    path, connect, lock = _setup(tmp_path)
    _register(connect, lock)
    hash_lock_states = []

    monkeypatch.setattr(
        service_module,
        "_verify_wps_password",
        lambda _password_hash, _password: (True, True),
    )

    def precompute_hash(_password):
        hash_lock_states.append(lock.locked())
        return "precomputed-upgraded-hash"

    monkeypatch.setattr(service_module, "_hash_wps_password", precompute_hash)

    login_user(
        {"username": "User01", "password": "Pass01", "device": _device()},
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.1",
        now_func=lambda: 1400,
        config_version="test-config",
    )

    assert hash_lock_states == [False]
    with sqlite3.connect(str(path)) as conn:
        stored_hash = conn.execute(
            "SELECT password_hash FROM wps_users WHERE username_norm='user01'"
        ).fetchone()[0]
    assert stored_hash == "precomputed-upgraded-hash"


def test_bearer_rejects_non_ascii_before_hashing():
    with pytest.raises(WpsAuthError) as exc_info:
        bearer_token({"Authorization": "Bearer " + ("é" * 43)})
    assert exc_info.value.code == "SESSION_REQUIRED"


def test_heartbeat_updates_activity_without_extending_expiry(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="docx_tool")
    path, connect, lock = _setup(tmp_path)
    registered = _register(connect, lock, now=2000)
    headers = {"Authorization": f"Bearer {registered['session_token']}"}
    principal = authenticated_session(headers, connect_func=connect, sql_lock=lock, now_func=lambda: 2500)

    result = heartbeat(
        principal,
        {"device_id": registered["device"]["id"], "app_version": "5.1"},
        connect_func=connect,
        sql_lock=lock,
        client_ip="127.0.0.2",
        now_func=lambda: 2500,
        config_version="test-config",
    )

    assert result["session_expires_at"] == 2000 + 604800
    with sqlite3.connect(str(path)) as conn:
        row = conn.execute("SELECT last_seen_at,expires_at FROM wps_sessions").fetchone()
    assert row == (2500, 2000 + 604800)

    with pytest.raises(WpsAuthError) as exc_info:
        authenticated_session(headers, connect_func=connect, sql_lock=lock, now_func=lambda: 2000 + 604800)
    assert exc_info.value.code == "SESSION_EXPIRED"
    assert "wps.auth.session.expired" in caplog.text


def test_existing_24_hour_session_keeps_its_stored_expiry(tmp_path):
    path, connect, lock = _setup(tmp_path)
    created_at = 5000
    old_expires_at = created_at + 86400
    registered = _register(connect, lock, now=created_at)
    headers = {"Authorization": f"Bearer {registered['session_token']}"}
    with sqlite3.connect(str(path)) as conn:
        conn.execute("UPDATE wps_sessions SET expires_at=?", (old_expires_at,))
        conn.commit()

    principal = authenticated_session(
        headers,
        connect_func=connect,
        sql_lock=lock,
        now_func=lambda: old_expires_at - 1,
    )
    assert principal["expires_at"] == old_expires_at

    with pytest.raises(WpsAuthError) as exc_info:
        authenticated_session(
            headers,
            connect_func=connect,
            sql_lock=lock,
            now_func=lambda: old_expires_at,
        )
    assert exc_info.value.code == "SESSION_EXPIRED"
