"""Transactional WPS document replacement lifecycle.

DocxTool renders to a temporary DOCX while WPS keeps the source open. Only
after WPS closes the document does this module replace the source. A backup is
kept until WPS confirms that the formatted file reopened successfully.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import threading
from typing import Dict, Optional
import uuid

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
    source_sha256: str
    temporary_path: Path
    backup_path: Path
    format_result: FormatResult
    state: str = "prepared"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DocumentTransactionManager:
    """Own exactly one active WPS formatting transaction."""

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = Path(log_dir)
        self._operations: Dict[str, FormatOperation] = {}
        self._preparing = False
        self._lock = threading.RLock()

    def _claim_prepare(self) -> None:
        with self._lock:
            if self._preparing or self._operations:
                raise DocumentTransactionError("WPS_FORMAT_BUSY")
            self._preparing = True

    def _release_prepare(self) -> None:
        with self._lock:
            self._preparing = False

    def prepare(self, source_path: str, format_config: Optional[dict] = None) -> FormatOperation:
        source = Path(source_path).expanduser().resolve()
        if source.suffix.lower() != ".docx" or not source.is_file():
            raise DocumentTransactionError("INVALID_DOCX_INPUT")
        self._claim_prepare()
        operation_id = uuid.uuid4().hex
        temporary = source.with_name(f".{source.stem}.docxtool-{operation_id[:12]}.docx")
        backup = source.with_name(f".{source.stem}.docxtool-backup-{operation_id[:12]}.docx")
        try:
            if temporary.exists() or backup.exists():
                raise DocumentTransactionError("WPS_TRANSACTION_PATH_COLLISION")
            source_hash = sha256_file(source)
            log_event("INFO", "transaction", "prepare.start", "开始生成 WPS 排版临时文档", {"operation_id": operation_id[:8], "file_id": file_identity(source)})
            try:
                result = format_current_document(str(source), str(temporary), operation_id=operation_id, log_dir=self.log_dir, format_config=format_config)
            except Exception:
                temporary.unlink(missing_ok=True)
                log_event("ERROR", "transaction", "prepare.failed", "WPS 排版临时文档生成失败", {"operation_id": operation_id[:8], "file_id": file_identity(source)})
                raise
            operation = FormatOperation(operation_id=operation_id, source_path=source, source_sha256=source_hash, temporary_path=temporary, backup_path=backup, format_result=result)
            with self._lock:
                self._operations[operation_id] = operation
            log_event("INFO", "transaction", "prepare.completed", "WPS 排版临时文档已生成，等待宿主关闭原文档", {"operation_id": operation_id[:8], "file_id": file_identity(source)})
            return operation
        finally:
            self._release_prepare()

    def get(self, operation_id: str) -> FormatOperation:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise DocumentTransactionError("WPS_TRANSACTION_NOT_FOUND")
            return operation

    def commit(self, operation_id: str) -> FormatOperation:
        with self._lock:
            operation = self.get(operation_id)
            if operation.state != "prepared":
                raise DocumentTransactionError("WPS_TRANSACTION_INVALID_STATE")
            if not operation.source_path.is_file() or sha256_file(operation.source_path) != operation.source_sha256:
                raise DocumentTransactionError("DOCUMENT_CHANGED")
            if not operation.temporary_path.is_file():
                raise DocumentTransactionError("WPS_FORMAT_OUTPUT_MISSING")
            log_event("INFO", "transaction", "commit.start", "宿主已关闭原文档，开始原子替换", {"operation_id": operation_id[:8], "file_id": file_identity(operation.source_path)})
            shutil.copy2(operation.source_path, operation.backup_path)
            try:
                os.replace(operation.temporary_path, operation.source_path)
            except Exception:
                operation.backup_path.unlink(missing_ok=True)
                raise
            operation.state = "committed"
        log_event("INFO", "transaction", "commit.completed", "格式化文档已替换原文件，等待 WPS 重新打开确认", {"operation_id": operation_id[:8], "file_id": file_identity(operation.source_path)})
        return operation

    def finalize(self, operation_id: str) -> None:
        with self._lock:
            operation = self.get(operation_id)
            if operation.state != "committed":
                raise DocumentTransactionError("WPS_TRANSACTION_INVALID_STATE")
            operation.backup_path.unlink(missing_ok=True)
            operation.state = "finalized"
            self._operations.pop(operation_id, None)
        log_event("INFO", "transaction", "finalize.completed", "WPS 已重新打开格式化文档，事务完成", {"operation_id": operation_id[:8], "file_id": file_identity(operation.source_path)})

    def rollback(self, operation_id: str) -> None:
        with self._lock:
            operation = self.get(operation_id)
            if operation.state == "prepared":
                operation.temporary_path.unlink(missing_ok=True)
            elif operation.state == "committed":
                if not operation.backup_path.is_file():
                    raise DocumentTransactionError("WPS_TRANSACTION_BACKUP_MISSING")
                os.replace(operation.backup_path, operation.source_path)
            else:
                raise DocumentTransactionError("WPS_TRANSACTION_INVALID_STATE")
            operation.state = "rolled_back"
            self._operations.pop(operation_id, None)
        log_event("WARNING", "transaction", "rollback.completed", "WPS 排版事务已回滚", {"operation_id": operation_id[:8], "file_id": file_identity(operation.source_path)})
