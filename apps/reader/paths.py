"""Reader-owned local data paths, separate from source code and WPS accounts."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class ReaderPaths:
    root: Path
    books_dir: Path
    database_path: Path
    temp_dir: Path

    def ensure_directories(self) -> None:
        self.books_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)


def reader_paths() -> ReaderPaths:
    """Resolve the single local reader data root without touching the filesystem."""
    override = os.environ.get("DOCXTOOL_HOME")
    if override:
        root = Path(override) / "reader"
    elif os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("READER_LOCALAPPDATA_MISSING")
        root = Path(local_app_data) / "DocxTool" / "reader"
    else:
        state_home = os.environ.get("XDG_STATE_HOME")
        if not state_home:
            raise RuntimeError("READER_STATE_HOME_MISSING")
        root = Path(state_home) / "DocxTool" / "reader"
    return ReaderPaths(
        root=root,
        books_dir=root / "books",
        database_path=root / "reader.db",
        temp_dir=root / "temp",
    )
