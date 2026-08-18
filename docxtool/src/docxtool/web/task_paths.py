"""Task upload/output path helpers and permanent-retention cleanup hooks."""

from __future__ import annotations

import os
import shutil

from docxtool.web.file_utils import sanitize_filename


def startup_cleanup() -> dict:
    """Return a no-op startup cleanup result because accepted user records are permanent."""
    return {"removed": 0, "errors": 0}


def task_tmp_dir(runtime_tmp_dir: str, task_id: str) -> str:
    """Build the task runtime temp directory path from base tmp dir and task id."""
    return os.path.join(runtime_tmp_dir, task_id)


def task_upload_dir(upload_dir: str, task_id: str) -> str:
    """Build the accepted upload directory path from upload base dir and task id."""
    return os.path.join(upload_dir, task_id)


def task_upload_input_path(upload_dir: str, task_id: str, orig_name: str = "") -> str:
    """Build the stored input DOCX path from upload base dir, task id and original name."""
    safe = sanitize_filename(orig_name) or "upload.docx"
    _stem, ext = os.path.splitext(safe)
    if not ext:
        ext = ".docx"
    return os.path.join(task_upload_dir(upload_dir, task_id), f"input{ext}")


def cleanup_incomplete_upload(upload_dir: str, task_id: str, extra_path: str = "") -> None:
    """Remove only paths from an upload that failed before becoming an accepted document."""
    paths = []
    if extra_path:
        paths.append(extra_path)
    task_dir = task_upload_dir(upload_dir, task_id)
    if task_dir not in paths:
        paths.append(task_dir)
    for path in paths:
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass


def cleanup_expired_tmp(now: float | None = None) -> dict:
    """Return a no-op tmp cleanup result because accepted input files are permanent."""
    return {"removed": 0, "errors": 0}


def task_output_dir(output_dir: str, task_id: str) -> str:
    """Build the task output directory path from output base dir and task id."""
    return os.path.join(output_dir, task_id)


def task_output_path(output_dir: str, task_id: str) -> str:
    """Build the generated result DOCX path from output base dir and task id."""
    return os.path.join(task_output_dir(output_dir, task_id), "result.docx")


def ensure_path_within(base_dir: str, path: str) -> str:
    """Return an absolute path if it stays within base_dir, otherwise raise ValueError."""
    base = os.path.abspath(base_dir)
    candidate = os.path.abspath(path)
    if os.path.commonpath([base, candidate]) != base:
        raise ValueError(f"path escapes output directory: {candidate}")
    return candidate


def cleanup_output_path(path: str) -> None:
    """Remove an invalid generated output path without touching accepted user uploads."""
    if not path:
        return
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass


def cleanup_expired_outputs(now: float | None = None) -> dict:
    """Return a no-op output cleanup result because generated user files are permanent."""
    return {"removed": 0, "errors": 0}


def cleanup_expired_task_records(now: float | None = None) -> dict:
    """Return a no-op task-record cleanup result because task history is permanent."""
    return {"removed": 0, "errors": 0}
