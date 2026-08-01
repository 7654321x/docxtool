from pathlib import Path

import pytest

from docxtool.web import app as server
from docxtool.web.task_paths import (
    cleanup_expired_outputs,
    cleanup_expired_task_records,
    cleanup_expired_tmp,
    cleanup_incomplete_upload,
    cleanup_output_path,
    ensure_path_within,
    startup_cleanup,
    task_output_path,
    task_tmp_dir,
    task_upload_input_path,
)


def test_task_paths_build_stable_upload_and_output_paths(tmp_path):
    upload_root = str(tmp_path / "uploads")
    output_root = str(tmp_path / "outputs")
    runtime_root = str(tmp_path / "tmp")

    assert task_tmp_dir(runtime_root, "task-1") == str(Path(runtime_root) / "task-1")
    assert task_upload_input_path(upload_root, "task-1", "测试 文件") == str(
        Path(upload_root) / "task-1" / "input.docx"
    )
    assert task_output_path(output_root, "task-1") == str(Path(output_root) / "task-1" / "result.docx")


def test_task_paths_match_app_facade_for_current_globals(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(server, "OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setattr(server, "RUNTIME_TMP_DIR", str(tmp_path / "runtime"))

    assert server._task_upload_input_path("task-a", "a.docx") == str(
        Path(server.UPLOAD_DIR) / "task-a" / "input.docx"
    )
    assert server._task_output_path("task-a") == str(Path(server.OUTPUT_DIR) / "task-a" / "result.docx")
    assert server._task_tmp_dir("task-a") == str(Path(server.RUNTIME_TMP_DIR) / "task-a")


def test_task_paths_reject_escape_and_cleanup_only_explicit_paths(tmp_path):
    base = tmp_path / "outputs"
    inside = base / "task" / "result.docx"
    inside.parent.mkdir(parents=True)
    inside.write_text("bad output", encoding="utf-8")

    assert ensure_path_within(str(base), str(inside)) == str(inside.resolve())
    with pytest.raises(ValueError):
        ensure_path_within(str(base), str(tmp_path / "other" / "result.docx"))

    cleanup_output_path(str(inside.parent))
    assert not inside.parent.exists()


def test_task_paths_cleanup_incomplete_upload_and_permanent_noops(tmp_path):
    upload_root = tmp_path / "uploads"
    task_dir = upload_root / "task-input"
    task_dir.mkdir(parents=True)
    (task_dir / "input.docx").write_text("partial", encoding="utf-8")

    cleanup_incomplete_upload(str(upload_root), "task-input")

    assert not task_dir.exists()
    assert startup_cleanup() == {"removed": 0, "errors": 0}
    assert cleanup_expired_tmp() == {"removed": 0, "errors": 0}
    assert cleanup_expired_outputs() == {"removed": 0, "errors": 0}
    assert cleanup_expired_task_records() == {"removed": 0, "errors": 0}
