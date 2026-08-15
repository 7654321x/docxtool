"""Pure data and hashing helpers for WPS document transactions."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Optional


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
    format_result: Optional[object] = None
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


__all__ = ["DocumentTransactionError", "FormatOperation", "sha256_file"]
