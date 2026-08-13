"""Transactional WPS document replacement lifecycle.

DocxTool renders to a temporary DOCX while WPS keeps the source open. Only
after WPS closes the document does this module replace the source. A backup is
kept until WPS confirms that the formatted file reopened successfully. A small
local journal lets a restarted Control Server recover an interrupted replace.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
from typing import Dict, Optional
import uuid

from .add_letterhead import LetterheadOperationResult, add_letterhead_to_document
from .format_current_document import FormatResult, format_current_document
from .logging_adapter import file_identity, log_event


class DocumentTransactionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class FormatOperation:
    operation_id: str
    source_path: Path
    target_path: Path
    source_sha256: str
    temporary_path: Path
    backup_path: Path
    temporary_sha256: Optional[str] = None
    format_result: Optional[FormatResult | LetterheadOperationResult] = None
    request_id: str = ""
    command: str = "apply"
    state: str = "prepared"
    transaction_mode: str = "replace"
    conversion_path: Optional[Path] = None
    conversion_sha256: Optional[str] = None
    backup_sha256: Optional[str] = None
    formatted_source_sha256: Optional[str] = None

    @property
    def is_upgrade(self) -> bool:
        return self.transaction_mode == "legacy_upgrade"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _error_code(error: Exception, default: str) -> str:
    code = getattr(error, "code", "")
    if isinstance(code, str) and code:
        return code
    value = str(error).strip()
    if value and value.upper() == value and len(value) <= 100:
        return value
    return default


class DocumentTransactionManager:
    """Own exactly one active WPS formatting transaction."""

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = Path(log_dir)
        self.runtime_dir = self.log_dir.parent / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.runtime_dir / "transaction-state.json"
        self._operations: Dict[str, FormatOperation] = {}
        self._preparing = False
        self._lock = threading.RLock()
        self._recover_stale_transaction()

    def _write_journal(self, operation: FormatOperation) -> None:
        payload = {
            "version": 2,
            "operation_id": operation.operation_id,
            "command": operation.command,
            "state": operation.state,
            "transaction_mode": operation.transaction_mode,
            "source_path": str(operation.source_path),
            "target_path": str(operation.target_path),
            "conversion_path": (
                str(operation.conversion_path) if operation.conversion_path else None
            ),
            "temporary_path": str(operation.temporary_path),
            "backup_path": str(operation.backup_path),
            "original_source_sha256": operation.source_sha256,
            "conversion_sha256": operation.conversion_sha256,
            "temporary_sha256": operation.temporary_sha256,
            "backup_sha256": operation.backup_sha256,
            "formatted_source_sha256": operation.formatted_source_sha256,
        }
        temporary = self.journal_path.with_suffix(".tmp")
        log_event("DEBUG", "transaction", "transaction.journal.write.start", "开始写入 WPS 事务日志", {"operation_id_short": operation.operation_id[:12], "request_id": operation.request_id, "state": operation.state})
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.journal_path)
        except OSError:
            temporary.unlink(missing_ok=True)
            log_event("ERROR", "transaction", "transaction.journal.write.failed", "WPS 事务日志写入失败", {"operation_id_short": operation.operation_id[:12], "request_id": operation.request_id, "stage": "journal_write", "state": operation.state, "error_type": "OSError", "error_code": "WPS_TRANSACTION_JOURNAL_WRITE_FAILED"})
            raise DocumentTransactionError("WPS_TRANSACTION_JOURNAL_WRITE_FAILED")
        log_event("DEBUG", "transaction", "transaction.journal.write.completed", "WPS 事务日志写入完成", {"operation_id_short": operation.operation_id[:12], "request_id": operation.request_id, "state": operation.state})

    def _clear_journal(self) -> None:
        self.journal_path.unlink(missing_ok=True)
        self.journal_path.with_suffix(".tmp").unlink(missing_ok=True)

    @staticmethod
    def _validated_journal_paths(
        payload: dict,
    ) -> tuple[str, str, str, Path, Path, Optional[Path], Path, Path]:
        operation_id = str(payload.get("operation_id", ""))
        state = str(payload.get("state", ""))
        transaction_mode = str(payload.get("transaction_mode", "replace"))
        command = str(payload.get("command", "apply"))
        if command not in {
            "preview",
            "apply",
            "inspect_letterhead",
            "add_letterhead",
        }:
            raise ValueError("invalid command")
        if len(operation_id) != 32 or any(char not in "0123456789abcdef" for char in operation_id):
            raise ValueError("invalid operation id")
        source = Path(str(payload.get("source_path", ""))).expanduser().resolve()
        target = Path(str(payload.get("target_path", source))).expanduser().resolve()
        temporary = Path(str(payload.get("temporary_path", ""))).expanduser().resolve()
        backup = Path(str(payload.get("backup_path", ""))).expanduser().resolve()
        if transaction_mode == "replace":
            if source.suffix.lower() != ".docx" or target != source:
                raise ValueError("invalid source")
            conversion = None
            expected_temporary = source.with_name(
                f".{source.stem}.docxtool-{operation_id[:12]}.docx"
            )
            expected_backup = source.with_name(
                f".{source.stem}.docxtool-backup-{operation_id[:12]}.docx"
            )
        elif transaction_mode == "legacy_upgrade":
            if source.suffix.lower() not in {".doc", ".wps"}:
                raise ValueError("invalid legacy source")
            if target != source.with_suffix(".docx"):
                raise ValueError("invalid upgrade target")
            conversion = Path(
                str(payload.get("conversion_path", ""))
            ).expanduser().resolve()
            expected_temporary = source.with_name(
                f".{source.stem}.docxtool-{operation_id[:12]}.docx"
            )
            expected_backup = source.with_name(
                f".{source.stem}.docxtool-backup-{operation_id[:12]}{source.suffix.lower()}"
            )
            expected_conversion = source.with_name(
                f".{source.stem}.docxtool-convert-{operation_id[:12]}.docx"
            )
            if conversion != expected_conversion:
                raise ValueError("unexpected conversion path")
        else:
            raise ValueError("invalid transaction mode")
        if temporary != expected_temporary or backup != expected_backup:
            raise ValueError("unexpected transaction paths")
        return (
            operation_id,
            state,
            transaction_mode,
            source,
            target,
            conversion,
            temporary,
            backup,
        )

    @staticmethod
    def _journal_hash(payload: dict, name: str, *, optional: bool = False) -> Optional[str]:
        value = payload.get(name)
        if optional and value is None:
            return None
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("invalid journal hash")
        return value

    @staticmethod
    def _file_state(path: Path, original: str, formatted: str) -> str:
        if not path.is_file():
            return "missing"
        actual = sha256_file(path)
        if actual == original:
            return "original_match"
        if actual == formatted:
            return "formatted_match"
        return "unexpected"

    @staticmethod
    def _raise_recovery_error(
        event: str,
        message: str,
        stage: str,
        code: str,
        error: Exception,
    ) -> None:
        fields = {
            "stage": stage,
            "error_type": type(error).__name__,
            "error_code": code,
        }
        log_event("ERROR", "transaction", event, message, fields)
        log_event(
            "ERROR",
            "transaction",
            "transaction.recovery.failed",
            "WPS 排版事务恢复失败",
            fields,
        )
        raise DocumentTransactionError(code) from error

    def _recover_stale_upgrade(
        self,
        *,
        state: str,
        source: Path,
        target: Path,
        conversion: Path,
        temporary: Path,
        backup: Path,
        original_hash: str,
        conversion_hash: Optional[str],
        temporary_hash: Optional[str],
    ) -> None:
        def file_state(path: Path, expected: Optional[str]) -> str:
            if not path.is_file():
                return "missing"
            if expected is None:
                return "present"
            return "match" if sha256_file(path) == expected else "unexpected"

        source_state = file_state(source, original_hash)
        target_state = file_state(target, temporary_hash)
        conversion_state = file_state(conversion, conversion_hash)
        temporary_state = file_state(temporary, temporary_hash)
        backup_state = file_state(backup, original_hash)
        details = {
            "previous_state": state,
            "source_state": source_state,
            "target_state": target_state,
            "conversion_state": conversion_state,
            "temporary_state": temporary_state,
            "backup_state": backup_state,
        }
        if state == "conversion_pending":
            valid = (
                source_state == "match"
                and target_state == "missing"
                and temporary_state in {"missing", "present"}
                and backup_state == "missing"
                and conversion_state in {"missing", "present"}
            )
        elif state == "prepared":
            valid = (
                source_state == "match"
                and target_state == "missing"
                and temporary_state == "match"
                and backup_state == "missing"
                and conversion_state in {"match", "present"}
            )
        elif state in {"commit_started", "committed"}:
            valid = (
                target_state in {"missing", "match"}
                and temporary_state in {"missing", "match"}
                and conversion_state in {"missing", "match", "present"}
                and (
                    (source_state == "match" and backup_state == "missing")
                    or (source_state == "missing" and backup_state == "match")
                )
            )
        else:
            valid = False
        if not valid:
            log_event(
                "ERROR", "transaction", "upgrade.recovery.state.invalid",
                "旧格式升级事务文件状态不满足自动恢复条件",
                {"error_code": "WPS_TRANSACTION_RECOVERY_REQUIRED", **details},
            )
            raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_REQUIRED")
        try:
            if target_state == "match":
                target.unlink()
            if backup_state == "match":
                os.replace(backup, source)
            temporary.unlink(missing_ok=True)
            conversion.unlink(missing_ok=True)
            self._clear_journal()
        except OSError as exc:
            log_event(
                "ERROR", "transaction", "upgrade.recovery.cleanup.failed",
                "旧格式升级事务恢复失败",
                {
                    "error_code": "WPS_TRANSACTION_RECOVERY_REQUIRED",
                    "error_type": type(exc).__name__,
                    **details,
                },
            )
            raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_REQUIRED") from exc
        log_event(
            "WARNING", "transaction", "transaction.recovery.completed",
            "Control Server 启动时已恢复未完成的旧格式升级事务",
            {"file_id": file_identity(source), **details},
        )

    def _recover_stale_transaction(self) -> None:
        if not self.journal_path.is_file():
            return
        log_event(
            "WARNING",
            "transaction",
            "transaction.recovery.start",
            "开始恢复未完成的 WPS 排版事务",
            {"stage": "journal_validation"},
        )
        try:
            journal_text = self.journal_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self._raise_recovery_error(
                "transaction.journal.read.failed",
                "WPS 事务日志读取失败",
                "journal_read",
                "WPS_TRANSACTION_JOURNAL_READ_FAILED",
                exc,
            )
        try:
            payload = json.loads(journal_text)
        except json.JSONDecodeError as exc:
            self._raise_recovery_error(
                "transaction.journal.parse.failed",
                "WPS 事务日志 JSON 无效",
                "journal_parse",
                "WPS_TRANSACTION_JOURNAL_JSON_INVALID",
                exc,
            )
        if not isinstance(payload, dict) or payload.get("version") != 2:
            self._raise_recovery_error(
                "transaction.journal.schema.invalid",
                "WPS 事务日志结构无效",
                "journal_schema",
                "WPS_TRANSACTION_JOURNAL_SCHEMA_INVALID",
                ValueError("invalid journal schema"),
            )
        try:
            (
                _operation_id,
                state,
                transaction_mode,
                source,
                target,
                conversion,
                temporary,
                backup,
            ) = self._validated_journal_paths(payload)
        except (OSError, RuntimeError, ValueError) as exc:
            self._raise_recovery_error(
                "transaction.journal.paths.invalid",
                "WPS 事务日志路径无效",
                "journal_paths",
                "WPS_TRANSACTION_JOURNAL_PATH_INVALID",
                exc,
            )
        try:
            original_hash = self._journal_hash(payload, "original_source_sha256")
            temporary_hash = self._journal_hash(
                payload,
                "temporary_sha256",
                optional=transaction_mode == "legacy_upgrade",
            )
            conversion_hash = self._journal_hash(
                payload, "conversion_sha256", optional=True
            )
            backup_hash = self._journal_hash(payload, "backup_sha256", optional=True)
            formatted_hash = self._journal_hash(payload, "formatted_source_sha256", optional=True)
            if backup_hash not in {None, original_hash}:
                raise ValueError("invalid backup hash")
            if formatted_hash not in {None, temporary_hash}:
                raise ValueError("invalid formatted hash")
        except (TypeError, ValueError) as exc:
            self._raise_recovery_error(
                "transaction.journal.hashes.invalid",
                "WPS 事务日志哈希字段无效",
                "journal_hashes",
                "WPS_TRANSACTION_JOURNAL_HASH_INVALID",
                exc,
            )

        if transaction_mode == "legacy_upgrade":
            if conversion is None:
                raise DocumentTransactionError("WPS_TRANSACTION_JOURNAL_PATH_INVALID")
            self._recover_stale_upgrade(
                state=state,
                source=source,
                target=target,
                conversion=conversion,
                temporary=temporary,
                backup=backup,
                original_hash=original_hash,
                conversion_hash=conversion_hash,
                temporary_hash=temporary_hash,
            )
            return
        if temporary_hash is None:
            raise DocumentTransactionError("WPS_TRANSACTION_JOURNAL_HASH_INVALID")
        try:
            source_state = self._file_state(source, original_hash, temporary_hash)
        except OSError as exc:
            self._raise_recovery_error(
                "transaction.recovery.source_state.failed",
                "WPS 事务源文档状态读取失败",
                "source_state",
                "WPS_TRANSACTION_SOURCE_STATE_READ_FAILED",
                exc,
            )
        try:
            temporary_state = self._file_state(temporary, original_hash, temporary_hash)
        except OSError as exc:
            self._raise_recovery_error(
                "transaction.recovery.temporary_state.failed",
                "WPS 事务临时文档状态读取失败",
                "temporary_state",
                "WPS_TRANSACTION_TEMPORARY_STATE_READ_FAILED",
                exc,
            )
        try:
            backup_state = self._file_state(backup, original_hash, temporary_hash)
        except OSError as exc:
            self._raise_recovery_error(
                "transaction.recovery.backup_state.failed",
                "WPS 事务备份文档状态读取失败",
                "backup_state",
                "WPS_TRANSACTION_BACKUP_STATE_READ_FAILED",
                exc,
            )
        recovery_details = {
            "previous_state": state,
            "source_state": source_state,
            "temporary_state": temporary_state,
            "backup_state": backup_state,
        }
        file_id = file_identity(source)
        try:
            if state == "prepared":
                if source_state != "original_match" or temporary_state != "formatted_match" or backup_state != "missing":
                    log_event(
                        "ERROR", "transaction", "transaction.recovery.prepared_state.invalid",
                        "prepared 事务文件状态不满足自动恢复条件",
                        {"error_code": "WPS_TRANSACTION_RECOVERY_REQUIRED", **recovery_details},
                    )
                    raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_REQUIRED")
                log_event("DEBUG", "transaction", "transaction.recovery.temporary_cleanup.start", "开始清理未提交的排版临时文档", recovery_details)
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    log_event("ERROR", "transaction", "transaction.recovery.temporary_cleanup.failed", "未提交排版临时文档清理失败", {"error_code": "WPS_TRANSACTION_RECOVERY_TEMPORARY_CLEANUP_FAILED", "error_type": type(exc).__name__, **recovery_details})
                    raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_TEMPORARY_CLEANUP_FAILED") from exc
                log_event("DEBUG", "transaction", "transaction.recovery.temporary_cleanup.completed", "未提交的排版临时文档已清理", recovery_details)
            elif state in {"commit_started", "committed"}:
                if source_state == "formatted_match" and backup_state == "original_match" and temporary_state == "missing":
                    log_event("WARNING", "transaction", "transaction.recovery.source_restore.start", "开始使用备份恢复源文档", recovery_details)
                    try:
                        os.replace(backup, source)
                    except OSError as exc:
                        log_event("ERROR", "transaction", "transaction.recovery.source_restore.failed", "使用备份恢复源文档失败", {"error_code": "WPS_TRANSACTION_RECOVERY_SOURCE_RESTORE_FAILED", "error_type": type(exc).__name__, **recovery_details})
                        raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_SOURCE_RESTORE_FAILED") from exc
                    log_event("WARNING", "transaction", "transaction.recovery.source_restore.completed", "源文档已从备份恢复", recovery_details)
                elif source_state == "original_match" and temporary_state == "formatted_match" and backup_state in {"missing", "original_match"}:
                    log_event("DEBUG", "transaction", "transaction.recovery.temporary_cleanup.start", "开始清理未生效的排版临时文档", recovery_details)
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError as exc:
                        log_event("ERROR", "transaction", "transaction.recovery.temporary_cleanup.failed", "未生效排版临时文档清理失败", {"error_code": "WPS_TRANSACTION_RECOVERY_TEMPORARY_CLEANUP_FAILED", "error_type": type(exc).__name__, **recovery_details})
                        raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_TEMPORARY_CLEANUP_FAILED") from exc
                    log_event("DEBUG", "transaction", "transaction.recovery.temporary_cleanup.completed", "未生效的排版临时文档已清理", recovery_details)
                    log_event("DEBUG", "transaction", "transaction.recovery.backup_cleanup.start", "开始清理未使用的排版备份", recovery_details)
                    try:
                        backup.unlink(missing_ok=True)
                    except OSError as exc:
                        log_event("ERROR", "transaction", "transaction.recovery.backup_cleanup.failed", "未使用排版备份清理失败", {"error_code": "WPS_TRANSACTION_RECOVERY_BACKUP_CLEANUP_FAILED", "error_type": type(exc).__name__, **recovery_details})
                        raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_BACKUP_CLEANUP_FAILED") from exc
                    log_event("DEBUG", "transaction", "transaction.recovery.backup_cleanup.completed", "未使用的排版备份已清理", recovery_details)
                elif (
                    state == "committed"
                    and source_state == "formatted_match"
                    and backup_state == "missing"
                    and temporary_state == "missing"
                ):
                    log_event(
                        "WARNING",
                        "transaction",
                        "transaction.recovery.backup_missing.discarded",
                        "排版结果已生效但事务备份缺失，结束旧事务",
                        recovery_details,
                    )
                    try:
                        self._clear_journal()
                    except OSError as exc:
                        log_event(
                            "ERROR",
                            "transaction",
                            "transaction.recovery.backup_missing.discard_failed",
                            "备份缺失的旧事务登记清理失败",
                            {
                                "error_code": "WPS_TRANSACTION_RECOVERY_JOURNAL_CLEAR_FAILED",
                                "error_type": type(exc).__name__,
                                **recovery_details,
                            },
                        )
                        raise DocumentTransactionError(
                            "WPS_TRANSACTION_RECOVERY_JOURNAL_CLEAR_FAILED"
                        ) from exc
                    log_event(
                        "WARNING",
                        "transaction",
                        "transaction.recovery.backup_missing.discard_completed",
                        "备份缺失的旧事务已结束",
                        recovery_details,
                    )
                    return
                else:
                    log_event(
                        "ERROR", "transaction", "transaction.recovery.committed_state.invalid",
                        "已提交事务文件状态不满足自动恢复条件",
                        {"error_code": "WPS_TRANSACTION_RECOVERY_REQUIRED", **recovery_details},
                    )
                    raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_REQUIRED")
            else:
                log_event(
                    "ERROR", "transaction", "transaction.recovery.state.invalid",
                    "WPS 事务日志状态无效",
                    {"error_code": "WPS_TRANSACTION_JOURNAL_INVALID", **recovery_details},
                )
                raise DocumentTransactionError("WPS_TRANSACTION_JOURNAL_INVALID")
            log_event("DEBUG", "transaction", "transaction.recovery.journal_clear.start", "开始清理已恢复的 WPS 事务日志", recovery_details)
            try:
                self._clear_journal()
            except OSError as exc:
                log_event("ERROR", "transaction", "transaction.recovery.journal_clear.failed", "已恢复事务日志清理失败", {"error_code": "WPS_TRANSACTION_RECOVERY_JOURNAL_CLEAR_FAILED", "error_type": type(exc).__name__, **recovery_details})
                raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_JOURNAL_CLEAR_FAILED") from exc
            log_event("DEBUG", "transaction", "transaction.recovery.journal_clear.completed", "已恢复的 WPS 事务日志已清理", recovery_details)
        except DocumentTransactionError as exc:
            log_event(
                "ERROR",
                "transaction",
                "transaction.recovery.failed",
                "WPS 排版事务恢复失败",
                {
                    "stage": "file_recovery",
                    "error_type": type(exc).__name__,
                    "error_code": exc.code,
                    **recovery_details,
                },
            )
            raise
        except OSError as exc:
            # Keep the journal intact so closing WPS and restarting can retry.
            log_event(
                "ERROR",
                "transaction",
                "transaction.recovery.failed",
                "WPS 排版事务恢复失败",
                {
                    "stage": "file_recovery",
                    "error_type": type(exc).__name__,
                    "error_code": "WPS_TRANSACTION_RECOVERY_REQUIRED",
                    **recovery_details,
                },
            )
            raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_REQUIRED") from exc
        log_event(
            "WARNING",
            "transaction",
            "transaction.recovery.completed",
            "Control Server 启动时已恢复未完成的 WPS 排版事务",
            {"file_id": file_id, **recovery_details},
        )

    def _claim_prepare(self, request_id: str) -> None:
        with self._lock:
            if self._preparing or self._operations:
                log_event(
                    "WARNING", "transaction", "prepare.rejected.busy",
                    "已有 WPS 排版事务正在执行",
                    {"request_id": request_id, "error_code": "WPS_FORMAT_BUSY"},
                )
                raise DocumentTransactionError("WPS_FORMAT_BUSY")
            self._preparing = True

    def _release_prepare(self) -> None:
        with self._lock:
            self._preparing = False

    def reserve_upgrade(
        self, source_path: str, *, command: str, request_id: str = ""
    ) -> FormatOperation:
        if command not in {
            "preview",
            "apply",
            "inspect_letterhead",
            "add_letterhead",
        }:
            raise DocumentTransactionError("WPS_TRANSACTION_COMMAND_INVALID")
        source = Path(source_path).expanduser().resolve()
        if source.suffix.lower() not in {".doc", ".wps"} or not source.is_file():
            log_event(
                "ERROR", "transaction", "upgrade.reserve.input.invalid",
                "旧格式升级源文件无效",
                {"request_id": request_id, "error_code": "WPS_LEGACY_INPUT_INVALID"},
            )
            raise DocumentTransactionError("WPS_LEGACY_INPUT_INVALID")
        target = source.with_suffix(".docx")
        if target.exists():
            log_event(
                "ERROR", "transaction", "upgrade.reserve.target.exists",
                "旧格式升级目标 DOCX 已存在",
                {"request_id": request_id, "error_code": "WPS_LEGACY_UPGRADE_TARGET_EXISTS"},
            )
            raise DocumentTransactionError("WPS_LEGACY_UPGRADE_TARGET_EXISTS")
        self._claim_prepare(request_id)
        operation_id = uuid.uuid4().hex
        conversion = source.with_name(
            f".{source.stem}.docxtool-convert-{operation_id[:12]}.docx"
        )
        temporary = source.with_name(
            f".{source.stem}.docxtool-{operation_id[:12]}.docx"
        )
        backup = source.with_name(
            f".{source.stem}.docxtool-backup-{operation_id[:12]}{source.suffix.lower()}"
        )
        try:
            if conversion.exists() or temporary.exists() or backup.exists():
                log_event(
                    "ERROR", "transaction", "upgrade.reserve.path_collision",
                    "旧格式升级临时路径已存在",
                    {
                        "operation_id_short": operation_id[:12],
                        "request_id": request_id,
                        "error_code": "WPS_TRANSACTION_PATH_COLLISION",
                    },
                )
                raise DocumentTransactionError("WPS_TRANSACTION_PATH_COLLISION")
            try:
                source_hash = sha256_file(source)
            except OSError as exc:
                log_event(
                    "ERROR", "transaction", "upgrade.reserve.source_hash.failed",
                    "旧格式升级源文件状态读取失败",
                    {
                        "operation_id_short": operation_id[:12],
                        "request_id": request_id,
                        "error_code": "WPS_TRANSACTION_SOURCE_HASH_FAILED",
                        "error_type": type(exc).__name__,
                    },
                )
                raise DocumentTransactionError(
                    "WPS_TRANSACTION_SOURCE_HASH_FAILED"
                ) from exc
            operation = FormatOperation(
                operation_id=operation_id,
                source_path=source,
                target_path=target,
                source_sha256=source_hash,
                temporary_path=temporary,
                backup_path=backup,
                request_id=request_id,
                command=command,
                state="conversion_pending",
                transaction_mode="legacy_upgrade",
                conversion_path=conversion,
            )
            with self._lock:
                self._write_journal(operation)
                self._operations[operation_id] = operation
            log_event(
                "INFO", "transaction", "upgrade.reserve.completed",
                "旧格式升级事务已预留，等待 WPS 转换为 DOCX",
                {
                    "operation_id_short": operation_id[:12],
                    "request_id": request_id,
                    "file_id": file_identity(source),
                    "source_format": source.suffix.lower().lstrip("."),
                    "target_format": "docx",
                },
            )
            return operation
        finally:
            self._release_prepare()

    def prepare_upgrade(
        self,
        operation_id: str,
        format_config: Optional[dict] = None,
        *,
        request_id: str = "",
        host_snapshot: Optional[dict] = None,
        selected_host_paragraph_indexes: Optional[list[int]] = None,
    ) -> FormatOperation:
        operation = self.get(operation_id, request_id)
        operation.request_id = request_id or operation.request_id
        if operation.command not in {"apply", "add_letterhead"}:
            raise DocumentTransactionError("WPS_TRANSACTION_COMMAND_MISMATCH")
        if not operation.is_upgrade or operation.state != "conversion_pending":
            raise DocumentTransactionError("WPS_TRANSACTION_INVALID_STATE")
        if operation.conversion_path is None or not operation.conversion_path.is_file():
            log_event(
                "ERROR", "transaction", "upgrade.prepare.conversion.missing",
                "WPS 转换后的临时 DOCX 不存在",
                {
                    "operation_id_short": operation_id[:12],
                    "request_id": operation.request_id,
                    "error_code": "WPS_LEGACY_CONVERTED_FILE_MISSING",
                },
            )
            raise DocumentTransactionError("WPS_LEGACY_CONVERTED_FILE_MISSING")
        if operation.target_path.exists():
            raise DocumentTransactionError("WPS_LEGACY_UPGRADE_TARGET_EXISTS")
        if sha256_file(operation.source_path) != operation.source_sha256:
            raise DocumentTransactionError("DOCUMENT_CHANGED")
        operation.conversion_sha256 = sha256_file(operation.conversion_path)
        log_event(
            "INFO", "transaction", "upgrade.prepare.start",
            "开始排版 WPS 转换后的临时 DOCX",
            {
                "operation_id_short": operation_id[:12],
                "request_id": operation.request_id,
                "file_id": file_identity(operation.source_path),
            },
        )
        try:
            scope_arguments = {}
            if selected_host_paragraph_indexes is not None:
                scope_arguments = {
                    "host_snapshot": host_snapshot,
                    "selected_host_paragraph_indexes": selected_host_paragraph_indexes,
                }
            if operation.command == "add_letterhead":
                result = add_letterhead_to_document(
                    str(operation.conversion_path),
                    str(operation.temporary_path),
                    format_config,
                    operation_id=operation_id,
                    log_dir=self.log_dir,
                    request_id=operation.request_id,
                )
            else:
                result = format_current_document(
                    str(operation.conversion_path),
                    str(operation.temporary_path),
                    operation_id=operation_id,
                    log_dir=self.log_dir,
                    format_config=format_config,
                    request_id=operation.request_id,
                    **scope_arguments,
                )
        except Exception as exc:
            operation.temporary_path.unlink(missing_ok=True)
            log_event(
                "ERROR", "transaction", "upgrade.prepare.failed",
                "转换后的 DOCX 排版失败",
                {
                    "operation_id_short": operation_id[:12],
                    "request_id": operation.request_id,
                    "stage": "temporary_format",
                    "error_code": _error_code(exc, "WPS_FORMAT_PREPARE_FAILED"),
                    "error_type": type(exc).__name__,
                },
            )
            raise
        temporary_hash = sha256_file(operation.temporary_path)
        if sha256_file(operation.source_path) != operation.source_sha256:
            operation.temporary_path.unlink(missing_ok=True)
            raise DocumentTransactionError("DOCUMENT_CHANGED")
        if operation.target_path.exists():
            operation.temporary_path.unlink(missing_ok=True)
            raise DocumentTransactionError("WPS_LEGACY_UPGRADE_TARGET_EXISTS")
        operation.format_result = result
        operation.temporary_sha256 = temporary_hash
        operation.state = "prepared"
        try:
            self._write_journal(operation)
        except DocumentTransactionError:
            operation.state = "conversion_pending"
            operation.format_result = None
            operation.temporary_sha256 = None
            operation.temporary_path.unlink(missing_ok=True)
            raise
        log_event(
            "INFO", "transaction", "upgrade.prepare.completed",
            "旧格式升级排版结果已生成",
            {
                "operation_id_short": operation_id[:12],
                "request_id": operation.request_id,
                "log_file": result.log_path.name,
            },
        )
        return operation

    def prepare_converted_upgrade(
        self,
        operation_id: str,
        *,
        request_id: str = "",
    ) -> FormatOperation:
        operation = self.get(operation_id, request_id)
        operation.request_id = request_id or operation.request_id
        if operation.command != "preview":
            raise DocumentTransactionError("WPS_TRANSACTION_COMMAND_MISMATCH")
        if not operation.is_upgrade or operation.state != "conversion_pending":
            raise DocumentTransactionError("WPS_TRANSACTION_INVALID_STATE")
        if operation.conversion_path is None or not operation.conversion_path.is_file():
            raise DocumentTransactionError("WPS_LEGACY_CONVERTED_FILE_MISSING")
        if operation.target_path.exists():
            raise DocumentTransactionError("WPS_LEGACY_UPGRADE_TARGET_EXISTS")
        if sha256_file(operation.source_path) != operation.source_sha256:
            raise DocumentTransactionError("DOCUMENT_CHANGED")
        operation.conversion_sha256 = sha256_file(operation.conversion_path)
        log_event(
            "INFO",
            "transaction",
            "upgrade.prepare_converted.start",
            "开始准备原样发布 WPS 转换后的 DOCX",
            {
                "operation_id_short": operation_id[:12],
                "request_id": operation.request_id,
                "file_id": file_identity(operation.source_path),
            },
        )
        try:
            shutil.copy2(operation.conversion_path, operation.temporary_path)
        except OSError as exc:
            operation.temporary_path.unlink(missing_ok=True)
            log_event(
                "ERROR",
                "transaction",
                "upgrade.prepare_converted.copy.failed",
                "WPS 转换结果复制到发布临时文件失败",
                {
                    "operation_id_short": operation_id[:12],
                    "request_id": operation.request_id,
                    "error_code": "WPS_LEGACY_CONVERTED_COPY_FAILED",
                    "error_type": type(exc).__name__,
                },
            )
            raise DocumentTransactionError(
                "WPS_LEGACY_CONVERTED_COPY_FAILED"
            ) from exc
        temporary_hash = sha256_file(operation.temporary_path)
        if temporary_hash != operation.conversion_sha256:
            operation.temporary_path.unlink(missing_ok=True)
            raise DocumentTransactionError("WPS_LEGACY_CONVERTED_COPY_MISMATCH")
        if sha256_file(operation.source_path) != operation.source_sha256:
            operation.temporary_path.unlink(missing_ok=True)
            raise DocumentTransactionError("DOCUMENT_CHANGED")
        if operation.target_path.exists():
            operation.temporary_path.unlink(missing_ok=True)
            raise DocumentTransactionError("WPS_LEGACY_UPGRADE_TARGET_EXISTS")
        operation.temporary_sha256 = temporary_hash
        operation.state = "prepared"
        try:
            self._write_journal(operation)
        except DocumentTransactionError:
            operation.state = "conversion_pending"
            operation.temporary_sha256 = None
            operation.temporary_path.unlink(missing_ok=True)
            raise
        log_event(
            "INFO",
            "transaction",
            "upgrade.prepare_converted.completed",
            "WPS 转换结果已准备原样发布",
            {
                "operation_id_short": operation_id[:12],
                "request_id": operation.request_id,
            },
        )
        return operation

    def prepare(
        self,
        source_path: str,
        format_config: Optional[dict] = None,
        *,
        request_id: str = "",
        host_snapshot: Optional[dict] = None,
        selected_host_paragraph_indexes: Optional[list[int]] = None,
    ) -> FormatOperation:
        source = Path(source_path).expanduser().resolve()
        if source.suffix.lower() != ".docx" or not source.is_file():
            log_event(
                "ERROR", "transaction", "prepare.input.invalid",
                "WPS 排版事务源文件无效",
                {"request_id": request_id, "error_code": "INVALID_DOCX_INPUT"},
            )
            raise DocumentTransactionError("INVALID_DOCX_INPUT")
        self._claim_prepare(request_id)
        operation_id = uuid.uuid4().hex
        temporary = source.with_name(f".{source.stem}.docxtool-{operation_id[:12]}.docx")
        backup = source.with_name(f".{source.stem}.docxtool-backup-{operation_id[:12]}.docx")
        try:
            if temporary.exists() or backup.exists():
                log_event(
                    "ERROR", "transaction", "prepare.path_collision",
                    "WPS 排版事务临时路径已存在",
                    {
                        "operation_id_short": operation_id[:12],
                        "request_id": request_id,
                        "error_code": "WPS_TRANSACTION_PATH_COLLISION",
                    },
                )
                raise DocumentTransactionError("WPS_TRANSACTION_PATH_COLLISION")
            log_event(
                "DEBUG", "transaction", "prepare.source_hash.start",
                "开始记录排版前源文件状态",
                {"operation_id_short": operation_id[:12], "request_id": request_id},
            )
            try:
                source_hash = sha256_file(source)
            except OSError as exc:
                log_event(
                    "ERROR", "transaction", "prepare.source_hash.failed",
                    "排版前源文件状态读取失败",
                    {
                        "operation_id_short": operation_id[:12],
                        "request_id": request_id,
                        "error_code": "WPS_TRANSACTION_SOURCE_HASH_FAILED",
                        "error_type": type(exc).__name__,
                    },
                )
                raise DocumentTransactionError(
                    "WPS_TRANSACTION_SOURCE_HASH_FAILED"
                ) from exc
            log_event(
                "DEBUG", "transaction", "prepare.source_hash.completed",
                "排版前源文件状态已记录",
                {"operation_id_short": operation_id[:12], "request_id": request_id},
            )
            log_event("INFO", "transaction", "prepare.start", "开始生成 WPS 排版临时文档", {"operation_id_short": operation_id[:12], "request_id": request_id, "file_id": file_identity(source)})
            try:
                scope_arguments = {}
                if selected_host_paragraph_indexes is not None:
                    scope_arguments = {
                        "host_snapshot": host_snapshot,
                        "selected_host_paragraph_indexes": selected_host_paragraph_indexes,
                    }
                result = format_current_document(
                    str(source),
                    str(temporary),
                    operation_id=operation_id,
                    log_dir=self.log_dir,
                    format_config=format_config,
                    request_id=request_id,
                    **scope_arguments,
                )
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                log_event("ERROR", "transaction", "prepare.failed", "WPS 排版临时文档生成失败", {"operation_id_short": operation_id[:12], "request_id": request_id, "stage": "temporary_format", "file_id": file_identity(source), "error_code": _error_code(exc, "WPS_FORMAT_PREPARE_FAILED"), "error_type": type(exc).__name__})
                raise
            try:
                temporary_hash = sha256_file(temporary)
            except OSError as exc:
                temporary.unlink(missing_ok=True)
                log_event(
                    "ERROR", "transaction", "prepare.output_hash.failed",
                    "排版临时文档状态读取失败",
                    {
                        "operation_id_short": operation_id[:12],
                        "request_id": request_id,
                        "error_code": "WPS_TRANSACTION_OUTPUT_HASH_FAILED",
                        "error_type": type(exc).__name__,
                    },
                )
                raise DocumentTransactionError(
                    "WPS_TRANSACTION_OUTPUT_HASH_FAILED"
                ) from exc
            if sha256_file(source) != source_hash:
                temporary.unlink(missing_ok=True)
                log_event(
                    "ERROR", "transaction", "prepare.source_changed",
                    "生成临时文档期间源文件发生变化",
                    {
                        "operation_id_short": operation_id[:12],
                        "request_id": request_id,
                        "error_code": "DOCUMENT_CHANGED",
                    },
                )
                raise DocumentTransactionError("DOCUMENT_CHANGED")
            operation = FormatOperation(operation_id=operation_id, source_path=source, target_path=source, source_sha256=source_hash, temporary_sha256=temporary_hash, temporary_path=temporary, backup_path=backup, format_result=result, request_id=request_id, command="apply")
            with self._lock:
                try:
                    self._write_journal(operation)
                except DocumentTransactionError:
                    temporary.unlink(missing_ok=True)
                    raise
                self._operations[operation_id] = operation
            log_event("INFO", "transaction", "prepare.completed", "WPS 排版临时文档已生成，等待宿主关闭原文档", {"operation_id_short": operation_id[:12], "request_id": request_id, "file_id": file_identity(source), "log_file": result.log_path.name})
            return operation
        finally:
            self._release_prepare()

    def prepare_letterhead(
        self,
        source_path: str,
        letterhead_request: object,
        *,
        request_id: str = "",
    ) -> FormatOperation:
        source = Path(source_path).expanduser().resolve()
        if source.suffix.lower() != ".docx" or not source.is_file():
            raise DocumentTransactionError("INVALID_DOCX_INPUT")
        self._claim_prepare(request_id)
        operation_id = uuid.uuid4().hex
        temporary = source.with_name(
            f".{source.stem}.docxtool-{operation_id[:12]}.docx"
        )
        backup = source.with_name(
            f".{source.stem}.docxtool-backup-{operation_id[:12]}.docx"
        )
        try:
            if temporary.exists() or backup.exists():
                raise DocumentTransactionError("WPS_TRANSACTION_PATH_COLLISION")
            source_hash = sha256_file(source)
            try:
                result = add_letterhead_to_document(
                    str(source),
                    str(temporary),
                    letterhead_request,
                    operation_id=operation_id,
                    log_dir=self.log_dir,
                    request_id=request_id,
                )
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            temporary_hash = sha256_file(temporary)
            if sha256_file(source) != source_hash:
                temporary.unlink(missing_ok=True)
                raise DocumentTransactionError("DOCUMENT_CHANGED")
            operation = FormatOperation(
                operation_id=operation_id,
                source_path=source,
                target_path=source,
                source_sha256=source_hash,
                temporary_path=temporary,
                backup_path=backup,
                temporary_sha256=temporary_hash,
                format_result=result,
                request_id=request_id,
                command="add_letterhead",
            )
            with self._lock:
                try:
                    self._write_journal(operation)
                except DocumentTransactionError:
                    temporary.unlink(missing_ok=True)
                    raise
                self._operations[operation_id] = operation
            return operation
        finally:
            self._release_prepare()

    def get(self, operation_id: str, request_id: str = "") -> FormatOperation:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                log_event(
                    "ERROR", "transaction", "transaction.lookup.failed",
                    "WPS 排版事务不存在",
                    {
                        "operation_id_short": operation_id[:12],
                        "request_id": request_id,
                        "error_code": "WPS_TRANSACTION_NOT_FOUND",
                    },
                )
                raise DocumentTransactionError("WPS_TRANSACTION_NOT_FOUND")
            if operation.request_id and request_id != operation.request_id:
                log_event(
                    "ERROR",
                    "transaction",
                    "transaction.request.mismatch",
                    "WPS 排版事务与请求编号不匹配",
                    {
                        "operation_id_short": operation_id[:12],
                        "request_id": request_id,
                        "error_code": "WPS_TRANSACTION_REQUEST_MISMATCH",
                    },
                )
                raise DocumentTransactionError("WPS_TRANSACTION_REQUEST_MISMATCH")
            return operation

    def commit(self, operation_id: str, *, request_id: str = "") -> FormatOperation:
        with self._lock:
            operation = self.get(operation_id, request_id)
            operation.request_id = request_id or operation.request_id
            if operation.state != "prepared":
                log_event("ERROR", "transaction", "commit.state.invalid", "排版事务当前状态不能提交", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "state": operation.state, "error_code": "WPS_TRANSACTION_INVALID_STATE"})
                raise DocumentTransactionError("WPS_TRANSACTION_INVALID_STATE")
            if not operation.source_path.is_file():
                log_event("ERROR", "transaction", "commit.source.missing", "提交前源文件不存在", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "error_code": "WPS_TRANSACTION_SOURCE_MISSING"})
                raise DocumentTransactionError("WPS_TRANSACTION_SOURCE_MISSING")
            if sha256_file(operation.source_path) != operation.source_sha256:
                log_event("ERROR", "transaction", "commit.source.changed", "提交前源文件内容发生变化", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "error_code": "DOCUMENT_CHANGED"})
                raise DocumentTransactionError("DOCUMENT_CHANGED")
            if not operation.temporary_path.is_file():
                log_event("ERROR", "transaction", "commit.output.missing", "排版临时文档不存在", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "error_code": "WPS_FORMAT_OUTPUT_MISSING"})
                raise DocumentTransactionError("WPS_FORMAT_OUTPUT_MISSING")
            if operation.temporary_sha256 is None:
                raise DocumentTransactionError("WPS_TRANSACTION_INVALID_STATE")
            if operation.is_upgrade and operation.target_path.exists():
                log_event("ERROR", "transaction", "upgrade.commit.target.exists", "旧格式升级目标 DOCX 已存在", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "error_code": "WPS_LEGACY_UPGRADE_TARGET_EXISTS"})
                raise DocumentTransactionError("WPS_LEGACY_UPGRADE_TARGET_EXISTS")
            log_event("INFO", "transaction", "commit.start", "宿主已关闭原文档，开始原子替换", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "file_id": file_identity(operation.source_path)})
            prior_state = operation.state
            operation.state = "commit_started"
            try:
                self._write_journal(operation)
            except DocumentTransactionError:
                operation.state = prior_state
                raise
            if operation.is_upgrade:
                log_event("INFO", "transaction", "upgrade.source.retire.start", "开始将旧格式源文件移入事务备份", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "legacy_source_backup"})
                try:
                    os.replace(operation.source_path, operation.backup_path)
                except OSError as exc:
                    log_event("ERROR", "transaction", "upgrade.source.retire.failed", "旧格式源文件移入事务备份失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "legacy_source_backup", "error_type": type(exc).__name__, "error_code": "WPS_TRANSACTION_BACKUP_FAILED"})
                    raise DocumentTransactionError("WPS_TRANSACTION_BACKUP_FAILED") from exc
                operation.backup_sha256 = sha256_file(operation.backup_path)
                if operation.backup_sha256 != operation.source_sha256:
                    raise DocumentTransactionError("WPS_TRANSACTION_BACKUP_MISMATCH")
                self._write_journal(operation)
                log_event("INFO", "transaction", "upgrade.source.retire.completed", "旧格式源文件已移入事务备份", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "legacy_source_backup"})
                log_event("INFO", "transaction", "upgrade.target.publish.start", "开始发布升级后的 DOCX", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "upgrade_target_publish"})
                try:
                    os.replace(operation.temporary_path, operation.target_path)
                except OSError as exc:
                    log_event("ERROR", "transaction", "upgrade.target.publish.failed", "升级后的 DOCX 发布失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "upgrade_target_publish", "error_type": type(exc).__name__, "error_code": "WPS_TRANSACTION_REPLACE_FAILED"})
                    raise DocumentTransactionError("WPS_TRANSACTION_REPLACE_FAILED") from exc
                log_event("INFO", "transaction", "upgrade.target.publish.completed", "升级后的 DOCX 已发布", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "upgrade_target_publish"})
            else:
                log_event("INFO", "transaction", "backup.copy.start", "开始创建原文档事务备份", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "backup_copy"})
                try:
                    shutil.copy2(operation.source_path, operation.backup_path)
                except OSError as exc:
                    log_event("ERROR", "transaction", "backup.copy.failed", "原文档事务备份失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "backup_copy", "error_type": type(exc).__name__, "error_code": "WPS_TRANSACTION_BACKUP_FAILED"})
                    raise DocumentTransactionError("WPS_TRANSACTION_BACKUP_FAILED") from exc
                operation.backup_sha256 = sha256_file(operation.backup_path)
                if operation.backup_sha256 != operation.source_sha256:
                    log_event("ERROR", "transaction", "backup.verify.failed", "原文档事务备份校验失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "backup_verify", "error_code": "WPS_TRANSACTION_BACKUP_MISMATCH"})
                    raise DocumentTransactionError("WPS_TRANSACTION_BACKUP_MISMATCH")
                log_event("DEBUG", "transaction", "backup.verify.completed", "原文档事务备份校验完成", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "backup_verify"})
                log_event("INFO", "transaction", "backup.copy.completed", "原文档事务备份完成", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "backup_copy"})
                self._write_journal(operation)
                log_event("INFO", "transaction", "source.replace.start", "开始原子替换源文档", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "source_replace"})
                try:
                    os.replace(operation.temporary_path, operation.target_path)
                except OSError as exc:
                    log_event("ERROR", "transaction", "source.replace.failed", "源文档原子替换失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "source_replace", "error_type": type(exc).__name__, "error_code": "WPS_TRANSACTION_REPLACE_FAILED"})
                    raise DocumentTransactionError("WPS_TRANSACTION_REPLACE_FAILED")
                log_event("INFO", "transaction", "source.replace.completed", "源文档原子替换完成", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "source_replace"})
            operation.formatted_source_sha256 = sha256_file(operation.target_path)
            if operation.formatted_source_sha256 != operation.temporary_sha256:
                log_event("ERROR", "transaction", "source.replace.verify_failed", "替换后的源文档校验失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "source_verify", "error_code": "WPS_TRANSACTION_REPLACE_MISMATCH"})
                raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_REQUIRED")
            log_event("DEBUG", "transaction", "source.replace.verified", "替换后的源文档校验完成", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "stage": "source_verify"})
            operation.state = "committed"
            try:
                self._write_journal(operation)
            except DocumentTransactionError:
                operation.state = "commit_started"
                raise
        log_event("INFO", "transaction", "commit.completed", "格式化文档已提交，等待 WPS 重新打开确认", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "file_id": file_identity(operation.target_path)})
        return operation

    def finalize(self, operation_id: str, *, request_id: str = "") -> None:
        with self._lock:
            operation = self.get(operation_id, request_id)
            operation.request_id = request_id or operation.request_id
            if operation.state != "committed":
                log_event("ERROR", "transaction", "finalize.state.invalid", "排版事务当前状态不能完成", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "state": operation.state, "error_code": "WPS_TRANSACTION_INVALID_STATE"})
                raise DocumentTransactionError("WPS_TRANSACTION_INVALID_STATE")
            log_event("INFO", "transaction", "finalize.cleanup.start", "开始清理排版事务备份和日志", {"operation_id_short": operation_id[:12], "request_id": operation.request_id})
            try:
                operation.backup_path.unlink(missing_ok=True)
                operation.temporary_path.unlink(missing_ok=True)
                if operation.conversion_path is not None:
                    operation.conversion_path.unlink(missing_ok=True)
                self._clear_journal()
            except OSError as exc:
                log_event("ERROR", "transaction", "finalize.cleanup.failed", "排版事务清理失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "error_code": "WPS_TRANSACTION_FINALIZE_CLEANUP_FAILED", "error_type": type(exc).__name__})
                raise DocumentTransactionError("WPS_TRANSACTION_FINALIZE_CLEANUP_FAILED") from exc
            operation.state = "finalized"
            self._operations.pop(operation_id, None)
            log_event("INFO", "transaction", "finalize.cleanup.completed", "排版事务备份和日志已清理", {"operation_id_short": operation_id[:12], "request_id": operation.request_id})
        log_event("INFO", "transaction", "finalize.completed", "WPS 已重新打开格式化文档，事务完成", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "file_id": file_identity(operation.target_path)})

    def rollback(
        self,
        operation_id: str,
        *,
        request_id: str = "",
        preserve_conversion: bool = False,
    ) -> None:
        with self._lock:
            operation = self.get(operation_id, request_id)
            operation.request_id = request_id or operation.request_id
            log_event("WARNING", "transaction", "rollback.start", "开始回滚 WPS 排版事务", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "state": operation.state})
            if operation.is_upgrade:
                if operation.state not in {"conversion_pending", "prepared", "commit_started", "committed"}:
                    raise DocumentTransactionError("WPS_TRANSACTION_INVALID_STATE")
                if operation.target_path.is_file():
                    if operation.temporary_sha256 is None or sha256_file(operation.target_path) != operation.temporary_sha256:
                        raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_REQUIRED")
                    log_event("WARNING", "transaction", "upgrade.rollback.target_remove.start", "开始移除未确认的升级 DOCX", {"operation_id_short": operation_id[:12], "request_id": operation.request_id})
                    operation.target_path.unlink()
                    log_event("WARNING", "transaction", "upgrade.rollback.target_remove.completed", "未确认的升级 DOCX 已移除", {"operation_id_short": operation_id[:12], "request_id": operation.request_id})
                if operation.backup_path.is_file():
                    if sha256_file(operation.backup_path) != operation.source_sha256:
                        raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_REQUIRED")
                    if operation.source_path.exists():
                        if sha256_file(operation.source_path) != operation.source_sha256:
                            raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_REQUIRED")
                        operation.backup_path.unlink()
                    else:
                        log_event("WARNING", "transaction", "upgrade.rollback.source_restore.start", "开始恢复旧格式源文件", {"operation_id_short": operation_id[:12], "request_id": operation.request_id})
                        os.replace(operation.backup_path, operation.source_path)
                        log_event("WARNING", "transaction", "upgrade.rollback.source_restore.completed", "旧格式源文件已恢复", {"operation_id_short": operation_id[:12], "request_id": operation.request_id})
                elif not operation.source_path.is_file() or sha256_file(operation.source_path) != operation.source_sha256:
                    raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_REQUIRED")
                operation.temporary_path.unlink(missing_ok=True)
                if operation.conversion_path is not None and not preserve_conversion:
                    operation.conversion_path.unlink(missing_ok=True)
                operation.state = "rolled_back"
                self._operations.pop(operation_id, None)
                self._clear_journal()
                log_event("WARNING", "transaction", "rollback.completed", "旧格式升级事务已回滚", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "file_id": file_identity(operation.source_path)})
                return
            if operation.state == "prepared":
                try:
                    operation.temporary_path.unlink(missing_ok=True)
                except OSError as exc:
                    log_event("ERROR", "transaction", "rollback.temporary_cleanup.failed", "排版临时文档清理失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "error_code": "WPS_TRANSACTION_TEMPORARY_CLEANUP_FAILED", "error_type": type(exc).__name__})
                    raise DocumentTransactionError("WPS_TRANSACTION_TEMPORARY_CLEANUP_FAILED") from exc
            elif operation.state in {"commit_started", "committed"}:
                if not operation.backup_path.is_file():
                    log_event("ERROR", "transaction", "rollback.backup.missing", "回滚所需备份不存在", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "error_code": "WPS_TRANSACTION_BACKUP_MISSING"})
                    raise DocumentTransactionError("WPS_TRANSACTION_BACKUP_MISSING")
                if sha256_file(operation.backup_path) != operation.source_sha256:
                    log_event("ERROR", "transaction", "rollback.backup.mismatch", "回滚备份校验失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "error_code": "WPS_TRANSACTION_RECOVERY_REQUIRED"})
                    raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_REQUIRED")
                source_state = self._file_state(
                    operation.source_path,
                    operation.source_sha256,
                    operation.temporary_sha256,
                )
                if source_state == "formatted_match":
                    try:
                        os.replace(operation.backup_path, operation.source_path)
                    except OSError as exc:
                        log_event("ERROR", "transaction", "rollback.source_replace.failed", "回滚时恢复源文档失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "error_code": "WPS_TRANSACTION_ROLLBACK_REPLACE_FAILED", "error_type": type(exc).__name__})
                        raise DocumentTransactionError("WPS_TRANSACTION_ROLLBACK_REPLACE_FAILED") from exc
                elif source_state == "original_match":
                    try:
                        operation.backup_path.unlink()
                    except OSError as exc:
                        log_event("ERROR", "transaction", "rollback.backup_cleanup.failed", "回滚时备份清理失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "error_code": "WPS_TRANSACTION_BACKUP_CLEANUP_FAILED", "error_type": type(exc).__name__})
                        raise DocumentTransactionError("WPS_TRANSACTION_BACKUP_CLEANUP_FAILED") from exc
                else:
                    log_event("ERROR", "transaction", "rollback.source.ambiguous", "源文档状态不明确，拒绝自动回滚", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "source_state": source_state, "error_code": "WPS_TRANSACTION_RECOVERY_REQUIRED"})
                    raise DocumentTransactionError("WPS_TRANSACTION_RECOVERY_REQUIRED")
                try:
                    operation.temporary_path.unlink(missing_ok=True)
                except OSError as exc:
                    log_event("ERROR", "transaction", "rollback.temporary_cleanup.failed", "回滚时临时文档清理失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "error_code": "WPS_TRANSACTION_TEMPORARY_CLEANUP_FAILED", "error_type": type(exc).__name__})
                    raise DocumentTransactionError("WPS_TRANSACTION_TEMPORARY_CLEANUP_FAILED") from exc
            else:
                log_event("ERROR", "transaction", "rollback.state.invalid", "排版事务当前状态不能回滚", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "state": operation.state, "error_code": "WPS_TRANSACTION_INVALID_STATE"})
                raise DocumentTransactionError("WPS_TRANSACTION_INVALID_STATE")
            operation.state = "rolled_back"
            self._operations.pop(operation_id, None)
            try:
                self._clear_journal()
            except OSError as exc:
                log_event("ERROR", "transaction", "rollback.journal_clear.failed", "回滚事务日志清理失败", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "error_code": "WPS_TRANSACTION_JOURNAL_CLEAR_FAILED", "error_type": type(exc).__name__})
                raise DocumentTransactionError("WPS_TRANSACTION_JOURNAL_CLEAR_FAILED") from exc
        log_event("WARNING", "transaction", "rollback.completed", "WPS 排版事务已回滚", {"operation_id_short": operation_id[:12], "request_id": operation.request_id, "file_id": file_identity(operation.source_path)})

    def rollback_request(self, request_id: str) -> bool:
        if not request_id:
            raise DocumentTransactionError("WPS_TRANSACTION_REQUEST_REQUIRED")
        with self._lock:
            operation = next(
                (
                    candidate
                    for candidate in self._operations.values()
                    if candidate.request_id == request_id
                ),
                None,
            )
            if operation is None:
                log_event(
                    "DEBUG",
                    "transaction",
                    "transaction.request_rollback.not_found",
                    "未找到需要按请求回滚的 WPS 排版事务",
                    {"request_id": request_id},
                )
                return False
            operation_id = operation.operation_id
            state = operation.state
        log_event(
            "WARNING",
            "transaction",
            "transaction.request_rollback.start",
            "开始按请求编号回滚残留的 WPS 排版事务",
            {
                "request_id": request_id,
                "operation_id_short": operation_id[:12],
                "state": state,
            },
        )
        try:
            self.rollback(operation_id, request_id=request_id)
        except Exception as exc:
            log_event(
                "ERROR",
                "transaction",
                "transaction.request_rollback.failed",
                "按请求编号回滚残留的 WPS 排版事务失败",
                {
                    "request_id": request_id,
                    "operation_id_short": operation_id[:12],
                    "state": state,
                    "error_code": _error_code(
                        exc, "WPS_TRANSACTION_REQUEST_ROLLBACK_FAILED"
                    ),
                    "error_type": type(exc).__name__,
                },
            )
            raise
        log_event(
            "WARNING",
            "transaction",
            "transaction.request_rollback.completed",
            "已按请求编号回滚残留的 WPS 排版事务",
            {
                "request_id": request_id,
                "operation_id_short": operation_id[:12],
                "state": state,
            },
        )
        return True
