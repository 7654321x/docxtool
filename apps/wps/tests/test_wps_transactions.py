"""Split regression tests from the former test_wps_app module (test_wps_transactions.py)."""

# ruff: noqa: F405



from apps.wps.tests.support.wps_app_support import *  # noqa: F401,F403,F405



def test_transaction_commit_then_rollback_restores_original(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    assert source.read_bytes() == b"original"
    assert operation.temporary_path.read_bytes() == b"formatted"
    assert manager.journal_path.is_file()

    manager.commit(operation.operation_id)
    assert source.read_bytes() == b"formatted"
    assert operation.backup_path.read_bytes() == b"original"

    manager.rollback(operation.operation_id)
    assert source.read_bytes() == b"original"
    assert not manager.journal_path.exists()

def test_transaction_finalize_keeps_formatted_document(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    manager.commit(operation.operation_id)
    manager.finalize(operation.operation_id)

    assert source.read_bytes() == b"formatted"
    assert not operation.backup_path.exists()
    assert not manager.journal_path.exists()

def test_legacy_upgrade_commit_then_rollback_restores_original(tmp_path, monkeypatch):
    source = tmp_path / "sample.doc"
    source.write_bytes(b"legacy-original")
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.reserve_upgrade(str(source), command="apply")
    assert operation.state == "conversion_pending"
    assert operation.target_path == tmp_path / "sample.docx"
    operation.conversion_path.write_bytes(b"converted-docx")

    operation = manager.prepare_upgrade(operation.operation_id)
    assert operation.state == "prepared"
    assert operation.temporary_path.read_bytes() == b"formatted"

    manager.commit(operation.operation_id)
    assert not source.exists()
    assert operation.target_path.read_bytes() == b"formatted"
    assert operation.backup_path.read_bytes() == b"legacy-original"

    manager.rollback(operation.operation_id)
    assert source.read_bytes() == b"legacy-original"
    assert not operation.target_path.exists()
    assert not operation.conversion_path.exists()

def test_legacy_upgrade_finalize_keeps_only_docx(tmp_path, monkeypatch):
    source = tmp_path / "sample.wps"
    source.write_bytes(b"legacy-original")
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.reserve_upgrade(str(source), command="apply")
    operation.conversion_path.write_bytes(b"converted-docx")
    manager.prepare_upgrade(operation.operation_id)
    manager.commit(operation.operation_id)
    manager.finalize(operation.operation_id)

    assert not source.exists()
    assert operation.target_path.read_bytes() == b"formatted"
    assert not operation.backup_path.exists()
    assert not operation.conversion_path.exists()
    assert not manager.journal_path.exists()

def test_legacy_upgrade_rejects_existing_docx_before_reservation(tmp_path):
    source = tmp_path / "sample.doc"
    target = tmp_path / "sample.docx"
    source.write_bytes(b"legacy-original")
    target.write_bytes(b"existing-docx")

    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        manager.reserve_upgrade(str(source), command="preview")

    assert exc_info.value.code == "WPS_LEGACY_UPGRADE_TARGET_EXISTS"
    assert source.read_bytes() == b"legacy-original"
    assert target.read_bytes() == b"existing-docx"
    assert not manager.journal_path.exists()

def test_legacy_upgrade_prepare_converted_preserves_docx_bytes(tmp_path):
    source = tmp_path / "sample.doc"
    source.write_bytes(b"legacy-original")
    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.reserve_upgrade(str(source), command="preview")
    operation.conversion_path.write_bytes(b"converted-docx")

    prepared = manager.prepare_converted_upgrade(operation.operation_id)

    assert prepared.state == "prepared"
    assert prepared.format_result is None
    assert prepared.temporary_path.read_bytes() == b"converted-docx"
    assert prepared.conversion_path.read_bytes() == b"converted-docx"
    manager.rollback(operation.operation_id)

@pytest.mark.parametrize("command", ["preview", "apply"])
def test_legacy_upgrade_prepare_rejects_the_wrong_transaction_command(
    tmp_path, monkeypatch, command
):
    source = tmp_path / "sample.doc"
    source.write_bytes(b"legacy-original")
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.reserve_upgrade(
        str(source), command=command, request_id="request-owner"
    )
    operation.conversion_path.write_bytes(b"converted-docx")

    with pytest.raises(
        transaction_module.DocumentTransactionError,
        match="WPS_TRANSACTION_COMMAND_MISMATCH",
    ):
        if command == "preview":
            manager.prepare_upgrade(
                operation.operation_id, request_id="request-owner"
            )
        else:
            manager.prepare_converted_upgrade(
                operation.operation_id, request_id="request-owner"
            )

    manager.rollback(operation.operation_id, request_id="request-owner")

@pytest.mark.parametrize("action", ["commit", "finalize", "rollback"])
def test_transaction_lifecycle_rejects_a_different_request_id(
    tmp_path, monkeypatch, action
):
    source = tmp_path / f"{action}.docx"
    source.write_bytes(b"original")
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(tmp_path / f"logs-{action}")
    operation = manager.prepare(str(source), request_id="request-owner")
    if action == "finalize":
        manager.commit(operation.operation_id, request_id="request-owner")

    with pytest.raises(
        transaction_module.DocumentTransactionError,
        match="WPS_TRANSACTION_REQUEST_MISMATCH",
    ):
        getattr(manager, action)(
            operation.operation_id, request_id="request-other"
        )

    manager.rollback(operation.operation_id, request_id="request-owner")

def test_legacy_upgrade_recovery_cleans_uncommitted_conversion(tmp_path):
    source = tmp_path / "sample.doc"
    source.write_bytes(b"legacy-original")
    log_dir = tmp_path / "logs"

    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.reserve_upgrade(str(source), command="preview")
    operation.conversion_path.write_bytes(b"converted-docx")

    recovered = transaction_module.DocumentTransactionManager(log_dir)

    assert source.read_bytes() == b"legacy-original"
    assert not operation.target_path.exists()
    assert not operation.conversion_path.exists()
    assert not recovered.journal_path.exists()

def test_legacy_upgrade_recovery_cleans_unjournaled_publish_copy(tmp_path):
    source = tmp_path / "sample.doc"
    source.write_bytes(b"legacy-original")
    log_dir = tmp_path / "logs"
    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.reserve_upgrade(str(source), command="preview")
    operation.conversion_path.write_bytes(b"converted-docx")
    operation.temporary_path.write_bytes(b"converted-docx")

    recovered = transaction_module.DocumentTransactionManager(log_dir)

    assert source.read_bytes() == b"legacy-original"
    assert not operation.target_path.exists()
    assert not operation.conversion_path.exists()
    assert not operation.temporary_path.exists()
    assert not recovered.journal_path.exists()

def test_legacy_upgrade_recovery_restores_committed_source(tmp_path, monkeypatch):
    source = tmp_path / "sample.wps"
    source.write_bytes(b"legacy-original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.reserve_upgrade(str(source), command="apply")
    operation.conversion_path.write_bytes(b"converted-docx")
    manager.prepare_upgrade(operation.operation_id)
    manager.commit(operation.operation_id)

    recovered = transaction_module.DocumentTransactionManager(log_dir)

    assert source.read_bytes() == b"legacy-original"
    assert not operation.target_path.exists()
    assert not operation.backup_path.exists()
    assert not operation.conversion_path.exists()
    assert not recovered.journal_path.exists()

def test_control_legacy_upgrade_routes_share_one_transaction(tmp_path, monkeypatch):
    source = tmp_path / "sample.doc"
    source.write_bytes(b"legacy-original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)
    application = object.__new__(server_module.WpsControlApplication)
    application.log_dir = log_dir
    application.transactions = transaction_module.DocumentTransactionManager(log_dir)
    application._authorization_lock = threading.RLock()
    application._authorized_requests = {
        "request-upgrade": {
            "started_at": 0.0,
            "config_version": "config-1",
            "format_config": {"features": {}},
            "host_generation": 1,
            "state": "authorized",
            "operation_id": "",
        }
    }

    reserved = application.dispatch(
        "/v1/format/upgrade/reserve",
        {"source_path": str(source), "command": "apply"},
        request_id="request-upgrade",
    )
    conversion_path = Path(reserved["conversion_path"])
    conversion_path.write_bytes(b"converted-docx")

    prepared = application.dispatch(
        "/v1/format/upgrade/prepare",
        {"operation_id": reserved["operation_id"]},
        request_id="request-upgrade",
    )
    rolled_back = application.dispatch(
        "/v1/format/rollback",
        {"operation_id": reserved["operation_id"]},
        request_id="request-upgrade",
    )

    assert reserved["state"] == "conversion_pending"
    assert reserved["source_format"] == "doc"
    assert Path(reserved["target_path"]) == source.with_suffix(".docx")
    assert prepared["state"] == "prepared"
    assert rolled_back["state"] == "rolled_back"
    assert source.read_bytes() == b"legacy-original"
    assert not conversion_path.exists()

def test_control_prepare_converted_upgrade_route(tmp_path):
    source = tmp_path / "sample.wps"
    source.write_bytes(b"legacy-original")
    log_dir = tmp_path / "logs"
    application = object.__new__(server_module.WpsControlApplication)
    application.log_dir = log_dir
    application.transactions = transaction_module.DocumentTransactionManager(log_dir)
    reserved = application.dispatch(
        "/v1/format/upgrade/reserve",
        {"source_path": str(source), "command": "preview"},
        request_id="request-preview-upgrade",
    )
    Path(reserved["conversion_path"]).write_bytes(b"converted-docx")

    prepared = application.dispatch(
        "/v1/format/upgrade/prepare-converted",
        {"operation_id": reserved["operation_id"]},
        request_id="request-preview-upgrade",
    )

    assert prepared == {
        "operation_id": reserved["operation_id"],
        "state": "prepared",
    }
    application.dispatch(
        "/v1/format/rollback",
        {"operation_id": reserved["operation_id"]},
        request_id="request-preview-upgrade",
    )

def test_control_format_prepare_requires_public_authorization(tmp_path):
    application = object.__new__(server_module.WpsControlApplication)
    application.log_dir = tmp_path / "logs"
    application.transactions = transaction_module.DocumentTransactionManager(
        application.log_dir
    )
    application._authorization_lock = threading.RLock()
    application._authorized_requests = {}

    with pytest.raises(
        transaction_module.DocumentTransactionError,
        match="WPS_APPLY_AUTHORIZATION_REQUIRED",
    ):
        application.dispatch(
            "/v1/format/prepare",
            {"source_path": str(tmp_path / "sample.docx")},
            request_id="request-without-authorization",
        )

def test_control_uses_authorized_config_once_and_ignores_request_body_config(
    tmp_path, monkeypatch
):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    observed_configs = []

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
        observed_configs.append(format_config)
        return _fake_result(target, Path(log_dir))

    monkeypatch.setattr(transaction_module, "format_current_document", fake_format)
    application = object.__new__(server_module.WpsControlApplication)
    application.log_dir = log_dir
    application.transactions = transaction_module.DocumentTransactionManager(log_dir)
    application._authorization_lock = threading.RLock()
    application._authorized_requests = {
        "request-authorized": {
            "started_at": 0.0,
            "config_version": "config-1",
            "format_config": {"features": {"numbering": {"enabled": True}}},
            "host_generation": 1,
            "state": "authorized",
            "operation_id": "",
        }
    }

    prepared = application.dispatch(
        "/v1/format/prepare",
        {
            "source_path": str(source),
            "format_config": {"features": {"numbering": {"enabled": False}}},
        },
        request_id="request-authorized",
    )

    assert observed_configs == [
        {"features": {"numbering": {"enabled": True}}}
    ]
    with pytest.raises(
        transaction_module.DocumentTransactionError,
        match="WPS_APPLY_AUTHORIZATION_CONSUMED",
    ):
        application.dispatch(
            "/v1/format/prepare",
            {"source_path": str(source)},
            request_id="request-authorized",
        )
    application.dispatch(
        "/v1/format/rollback",
        {"operation_id": prepared["operation_id"]},
        request_id="request-authorized",
    )

def test_prepare_journal_failure_does_not_publish_operation(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    original_write = Path.write_text

    def fail_journal_write(path, *args, **kwargs):
        if path == manager.journal_path.with_suffix(".tmp"):
            raise OSError("journal unavailable")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_journal_write)
    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        manager.prepare(str(source))
    assert exc_info.value.code == "WPS_TRANSACTION_JOURNAL_WRITE_FAILED"
    assert not manager._operations
    assert not list(tmp_path.glob(".sample.docxtool-*.docx"))

def test_commit_started_journal_failure_keeps_consistent_state(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.prepare(str(source))
    original_write = Path.write_text

    def fail_journal_write(path, *args, **kwargs):
        if path == manager.journal_path.with_suffix(".tmp"):
            raise OSError("journal unavailable")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_journal_write)
    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        manager.commit(operation.operation_id)
    assert exc_info.value.code == "WPS_TRANSACTION_JOURNAL_WRITE_FAILED"
    assert operation.state == "prepared"
    assert source.read_bytes() == b"original"
    assert operation.temporary_path.read_bytes() == b"formatted"
    assert not operation.backup_path.exists()

def test_commit_replace_failure_keeps_recoverable_state(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.prepare(str(source))
    original_replace = transaction_module.os.replace

    def fail_document_replace(source_path, destination_path):
        if Path(source_path) == operation.temporary_path and Path(destination_path) == operation.source_path:
            raise OSError("document locked")
        return original_replace(source_path, destination_path)

    monkeypatch.setattr(transaction_module.os, "replace", fail_document_replace)
    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        manager.commit(operation.operation_id)
    assert exc_info.value.code == "WPS_TRANSACTION_REPLACE_FAILED"
    assert operation.state == "commit_started"
    assert source.read_bytes() == b"original"
    assert operation.temporary_path.read_bytes() == b"formatted"
    assert operation.backup_path.read_bytes() == b"original"

def test_commit_backup_copy_failure_keeps_recoverable_state(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.prepare(str(source))

    def fail_backup_copy(*_args, **_kwargs):
        raise OSError("backup unavailable")

    monkeypatch.setattr(transaction_module.shutil, "copy2", fail_backup_copy)
    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        manager.commit(operation.operation_id)
    assert exc_info.value.code == "WPS_TRANSACTION_BACKUP_FAILED"
    assert operation.state == "commit_started"
    assert source.read_bytes() == b"original"
    assert operation.temporary_path.read_bytes() == b"formatted"
    assert not operation.backup_path.exists()

def test_committed_journal_failure_is_recoverable(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.prepare(str(source))
    original_write = Path.write_text
    write_count = 0

    def fail_committed_write(path, *args, **kwargs):
        nonlocal write_count
        if path == manager.journal_path.with_suffix(".tmp"):
            write_count += 1
            if write_count == 3:
                raise OSError("journal unavailable")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_committed_write)
    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        manager.commit(operation.operation_id)
    assert exc_info.value.code == "WPS_TRANSACTION_JOURNAL_WRITE_FAILED"
    assert operation.state == "commit_started"
    assert source.read_bytes() == b"formatted"
    monkeypatch.undo()
    transaction_module.DocumentTransactionManager(tmp_path / "logs")
    assert source.read_bytes() == b"original"
    assert not manager.journal_path.exists()

def test_recovery_refuses_changed_source_and_preserves_artifacts(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.prepare(str(source))
    manager.commit(operation.operation_id)
    source.write_bytes(b"changed outside transaction")

    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        transaction_module.DocumentTransactionManager(tmp_path / "logs")
    assert exc_info.value.code == "WPS_TRANSACTION_RECOVERY_REQUIRED"
    assert source.read_bytes() == b"changed outside transaction"
    assert operation.backup_path.exists()
    assert manager.journal_path.exists()

def test_recovery_restores_only_verified_formatted_source(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.prepare(str(source))
    manager.commit(operation.operation_id)

    transaction_module.DocumentTransactionManager(tmp_path / "logs")
    assert source.read_bytes() == b"original"
    assert not operation.backup_path.exists()
    assert not manager.journal_path.exists()

def test_recovery_refuses_wrong_backup(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.prepare(str(source))
    manager.commit(operation.operation_id)
    operation.backup_path.write_bytes(b"wrong backup")

    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        transaction_module.DocumentTransactionManager(tmp_path / "logs")
    assert exc_info.value.code == "WPS_TRANSACTION_RECOVERY_REQUIRED"
    assert source.read_bytes() == b"formatted"
    assert operation.backup_path.read_bytes() == b"wrong backup"

def test_restart_discards_committed_transaction_when_backup_is_missing(
    tmp_path, monkeypatch
):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    manager.commit(operation.operation_id)
    operation.backup_path.unlink()

    restarted = transaction_module.DocumentTransactionManager(log_dir)

    assert source.read_bytes() == b"formatted"
    assert not restarted.journal_path.exists()

def test_second_format_transaction_is_rejected_until_first_finishes(tmp_path, monkeypatch):
    first = tmp_path / "first.docx"
    second = tmp_path / "second.docx"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(tmp_path / "logs")
    operation = manager.prepare(str(first))
    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        manager.prepare(str(second))
    assert exc_info.value.code == "WPS_FORMAT_BUSY"

    manager.rollback(operation.operation_id)
    replacement = manager.prepare(str(second))
    manager.rollback(replacement.operation_id)

def test_restart_cleans_prepared_transaction(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    assert operation.temporary_path.exists()

    recovered = transaction_module.DocumentTransactionManager(log_dir)
    assert source.read_bytes() == b"original"
    assert not operation.temporary_path.exists()
    assert not recovered.journal_path.exists()

def test_restart_restores_committed_transaction(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)

    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    manager.commit(operation.operation_id)
    assert source.read_bytes() == b"formatted"
    assert operation.backup_path.exists()

    recovered = transaction_module.DocumentTransactionManager(log_dir)
    assert source.read_bytes() == b"original"
    assert not operation.backup_path.exists()
    assert not recovered.journal_path.exists()

def test_stale_transaction_recovery_logs_lifecycle(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    events = []
    monkeypatch.setattr(
        transaction_module,
        "log_event",
        lambda _level, _component, event, _message, _fields=None: events.append(event),
    )

    transaction_module.DocumentTransactionManager(log_dir)

    assert events == [
        "transaction.recovery.start",
        "transaction.recovery.temporary_cleanup.start",
        "transaction.recovery.temporary_cleanup.completed",
        "transaction.recovery.journal_clear.start",
        "transaction.recovery.journal_clear.completed",
        "transaction.recovery.completed",
    ]
    assert not operation.temporary_path.exists()

def test_stale_transaction_source_restore_failure_has_own_event(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(log_dir)
    operation = manager.prepare(str(source))
    manager.commit(operation.operation_id)
    original_replace = transaction_module.os.replace

    def fail_backup_restore(source_path, destination_path):
        if (
            Path(source_path) == operation.backup_path
            and Path(destination_path) == operation.source_path
        ):
            raise OSError("restore failed")
        return original_replace(source_path, destination_path)

    events = []
    monkeypatch.setattr(transaction_module.os, "replace", fail_backup_restore)
    monkeypatch.setattr(
        transaction_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields)
        ),
    )

    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        transaction_module.DocumentTransactionManager(log_dir)

    assert exc_info.value.code == "WPS_TRANSACTION_RECOVERY_SOURCE_RESTORE_FAILED"
    assert [event for event, _fields in events][-3:] == [
        "transaction.recovery.source_restore.start",
        "transaction.recovery.source_restore.failed",
        "transaction.recovery.failed",
    ]

def test_stale_transaction_journal_clear_failure_has_own_event(tmp_path, monkeypatch):
    source = tmp_path / "sample.docx"
    source.write_bytes(b"original")
    log_dir = tmp_path / "logs"
    _install_fake_formatter(monkeypatch)
    manager = transaction_module.DocumentTransactionManager(log_dir)
    manager.prepare(str(source))
    events = []

    def fail_journal_clear(_manager):
        raise OSError("journal clear failed")

    monkeypatch.setattr(
        transaction_module.DocumentTransactionManager,
        "_clear_journal",
        fail_journal_clear,
    )
    monkeypatch.setattr(
        transaction_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields)
        ),
    )

    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        transaction_module.DocumentTransactionManager(log_dir)

    assert exc_info.value.code == "WPS_TRANSACTION_RECOVERY_JOURNAL_CLEAR_FAILED"
    assert [event for event, _fields in events][-3:] == [
        "transaction.recovery.journal_clear.start",
        "transaction.recovery.journal_clear.failed",
        "transaction.recovery.failed",
    ]

@pytest.mark.parametrize(
    ("case", "expected_event", "expected_code"),
    [
        (
            "json",
            "transaction.journal.parse.failed",
            "WPS_TRANSACTION_JOURNAL_JSON_INVALID",
        ),
        (
            "schema",
            "transaction.journal.schema.invalid",
            "WPS_TRANSACTION_JOURNAL_SCHEMA_INVALID",
        ),
        (
            "path",
            "transaction.journal.paths.invalid",
            "WPS_TRANSACTION_JOURNAL_PATH_INVALID",
        ),
        (
            "hash",
            "transaction.journal.hashes.invalid",
            "WPS_TRANSACTION_JOURNAL_HASH_INVALID",
        ),
    ],
)
def test_invalid_stale_transaction_logs_exact_validation_failure(
    tmp_path, monkeypatch, case, expected_event, expected_code
):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    journal_path = runtime_dir / "transaction-state.json"
    source = tmp_path / "sample.docx"
    payload = _transaction_journal_payload(source)
    if case == "json":
        journal_path.write_text("{", encoding="utf-8")
    elif case == "schema":
        journal_path.write_text("{}", encoding="utf-8")
    else:
        if case == "path":
            payload["source_path"] = str(source.with_suffix(".txt"))
        elif case == "hash":
            payload["original_source_sha256"] = "invalid"
        journal_path.write_text(json.dumps(payload), encoding="utf-8")
    events = []
    monkeypatch.setattr(
        transaction_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append((event, fields)),
    )

    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        transaction_module.DocumentTransactionManager(tmp_path / "logs")

    assert [event for event, _fields in events] == [
        "transaction.recovery.start",
        expected_event,
        "transaction.recovery.failed",
    ]
    assert exc_info.value.code == expected_code
    assert events[-1][1]["error_code"] == expected_code

def test_stale_transaction_journal_read_failure_has_own_event(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    journal_path = runtime_dir / "transaction-state.json"
    journal_path.write_text("{}", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_journal_read(path, *args, **kwargs):
        if path == journal_path:
            raise OSError("journal read failed")
        return original_read_text(path, *args, **kwargs)

    events = []
    monkeypatch.setattr(Path, "read_text", fail_journal_read)
    monkeypatch.setattr(
        transaction_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields)
        ),
    )

    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        transaction_module.DocumentTransactionManager(tmp_path / "logs")

    assert [event for event, _fields in events] == [
        "transaction.recovery.start",
        "transaction.journal.read.failed",
        "transaction.recovery.failed",
    ]
    assert exc_info.value.code == "WPS_TRANSACTION_JOURNAL_READ_FAILED"

@pytest.mark.parametrize(
    ("role", "expected_event", "expected_code"),
    [
        (
            "source",
            "transaction.recovery.source_state.failed",
            "WPS_TRANSACTION_SOURCE_STATE_READ_FAILED",
        ),
        (
            "temporary",
            "transaction.recovery.temporary_state.failed",
            "WPS_TRANSACTION_TEMPORARY_STATE_READ_FAILED",
        ),
        (
            "backup",
            "transaction.recovery.backup_state.failed",
            "WPS_TRANSACTION_BACKUP_STATE_READ_FAILED",
        ),
    ],
)
def test_stale_transaction_file_state_failure_has_own_event(
    tmp_path, monkeypatch, role, expected_event, expected_code
):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    source = tmp_path / "sample.docx"
    payload = _transaction_journal_payload(source)
    paths = {
        "source": source,
        "temporary": Path(payload["temporary_path"]),
        "backup": Path(payload["backup_path"]),
    }
    paths["source"].write_bytes(b"original")
    paths["temporary"].write_bytes(b"formatted")
    paths["backup"].write_bytes(b"original")
    payload["original_source_sha256"] = transaction_module.sha256_file(paths["source"])
    payload["temporary_sha256"] = transaction_module.sha256_file(paths["temporary"])
    payload["backup_sha256"] = payload["original_source_sha256"]
    (runtime_dir / "transaction-state.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    original_sha256_file = transaction_module.sha256_file

    def fail_selected_file_state(path):
        if Path(path) == paths[role]:
            raise OSError("file state read failed")
        return original_sha256_file(path)

    events = []
    monkeypatch.setattr(transaction_module, "sha256_file", fail_selected_file_state)
    monkeypatch.setattr(
        transaction_module,
        "log_event",
        lambda _level, _component, event, _message, fields=None: events.append(
            (event, fields)
        ),
    )

    with pytest.raises(transaction_module.DocumentTransactionError) as exc_info:
        transaction_module.DocumentTransactionManager(tmp_path / "logs")

    assert [event for event, _fields in events] == [
        "transaction.recovery.start",
        expected_event,
        "transaction.recovery.failed",
    ]
    assert exc_info.value.code == expected_code
