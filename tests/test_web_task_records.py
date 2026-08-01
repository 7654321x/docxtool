from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path

from docxtool.web.task_records import mark_task_processing, mark_task_terminal, record_task_queued


def _connect_factory(path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _init_db(connect) -> None:
    conn = connect()
    conn.execute(
        """
        CREATE TABLE tasks(
            id TEXT PRIMARY KEY,
            ip TEXT,
            ua TEXT,
            filename TEXT,
            file_size INTEGER,
            doc_type TEXT,
            paragraphs INTEGER,
            headings INTEGER,
            body INTEGER,
            duration_ms INTEGER,
            status TEXT,
            error TEXT,
            log_filename TEXT,
            log_path TEXT,
            output_dir TEXT,
            output_filename TEXT,
            output_path TEXT,
            client_ip TEXT,
            original_filename TEXT,
            safe_download_filename TEXT,
            input_size INTEGER,
            processing_options TEXT,
            preset_id TEXT,
            owner_id TEXT,
            created_at TEXT,
            started_at TEXT,
            done_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def test_record_task_queued_inserts_and_upserts_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "tasks.db")
        _init_db(connect)
        lock = threading.Lock()

        record_task_queued(
            "task-a",
            "203.0.113.9",
            "ua",
            "input.docx",
            123,
            "{}",
            "preset-a",
            "owner-a",
            connect=connect,
            sql_lock=lock,
            now_func=lambda: "2026-08-02 01:00:00",
            safe_download_filename=lambda name: f"formatted-{name}",
        )
        record_task_queued(
            "task-a",
            "203.0.113.10",
            "ua2",
            "input2.docx",
            456,
            "{\"mode\":\"smart\"}",
            "preset-b",
            "owner-b",
            connect=connect,
            sql_lock=lock,
            now_func=lambda: "2026-08-02 01:01:00",
            safe_download_filename=lambda name: f"formatted-{name}",
        )
        conn = connect()
        row = conn.execute("SELECT * FROM tasks WHERE id='task-a'").fetchone()
        conn.close()

    assert row["status"] == "queued"
    assert row["ip"] == "203.0.113.10"
    assert row["filename"] == "input2.docx"
    assert row["safe_download_filename"] == "formatted-input2.docx"
    assert row["processing_options"] == "{\"mode\":\"smart\"}"
    assert row["preset_id"] == "preset-b"
    assert row["owner_id"] == "owner-b"
    assert row["done_at"] == ""


def test_mark_task_processing_and_terminal_update_task_row() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "tasks.db")
        _init_db(connect)
        lock = threading.Lock()
        record_task_queued(
            "task-a",
            "127.0.0.1",
            "",
            "input.docx",
            connect=connect,
            sql_lock=lock,
            now_func=lambda: "queued-time",
            safe_download_filename=lambda name: name,
        )

        mark_task_processing("task-a", connect=connect, sql_lock=lock, now_func=lambda: "processing-time")
        mark_task_terminal(
            "task-a",
            "done",
            "",
            "out.docx",
            "download.docx",
            "task.log",
            "task.log",
            connect=connect,
            sql_lock=lock,
            now_func=lambda: "done-time",
        )
        conn = connect()
        row = conn.execute("SELECT * FROM tasks WHERE id='task-a'").fetchone()
        conn.close()

    assert row["status"] == "done"
    assert row["started_at"] == "processing-time"
    assert row["output_path"] == "out.docx"
    assert row["output_filename"] == "download.docx"
    assert row["log_path"] == "task.log"
    assert row["done_at"] == "done-time"
