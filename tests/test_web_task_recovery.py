from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from docxtool.web.database_schema import initialize_web_database
from docxtool.web.task_recovery import INTERRUPTED_ERROR_MESSAGE, recover_inflight_tasks_on_startup


def _connect_factory(db_path: Path):
    """传入数据库路径，返回测试用 SQLite 连接工厂。"""

    def connect():
        """无需传入数据，返回带 Row 工厂的 SQLite 连接。"""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _empty_seed(_conn: sqlite3.Connection) -> None:
    """传入初始化连接，测试恢复模块时不插入默认模板。"""
    return None


def _init_recovery_db(tmp_path: Path):
    """传入临时目录，返回初始化后的连接工厂和线程锁。"""
    connect = _connect_factory(tmp_path / "stats.db")
    lock = threading.Lock()
    initialize_web_database(connect, lock, _empty_seed)
    return connect, lock


def _insert_task(conn: sqlite3.Connection, task_id: str, status: str) -> None:
    """传入连接、任务 ID 和状态，插入一条恢复测试任务。"""
    conn.execute(
        "INSERT INTO tasks(id, ip, filename, status, created_at, done_at) VALUES(?,?,?,?,?,?)",
        (task_id, "203.0.113.7", f"{task_id}.docx", status, "2026-08-01 01:00:00", ""),
    )


def test_recover_inflight_tasks_marks_only_queued_and_processing(tmp_path: Path) -> None:
    connect, lock = _init_recovery_db(tmp_path)
    conn = connect()
    try:
        _insert_task(conn, "queued-task", "queued")
        _insert_task(conn, "processing-task", "processing")
        _insert_task(conn, "done-task", "done")
        _insert_task(conn, "failed-task", "failed")
        conn.commit()
    finally:
        conn.close()

    count = recover_inflight_tasks_on_startup(
        connect=connect,
        sql_lock=lock,
        now_func=lambda: "2026-08-02 02:00:00",
    )

    conn = connect()
    try:
        rows = {
            row["id"]: dict(row)
            for row in conn.execute("SELECT id, status, error, done_at FROM tasks").fetchall()
        }
    finally:
        conn.close()

    assert count == 2
    assert rows["queued-task"]["status"] == "interrupted"
    assert rows["processing-task"]["status"] == "interrupted"
    assert rows["queued-task"]["error"] == INTERRUPTED_ERROR_MESSAGE
    assert rows["processing-task"]["done_at"] == "2026-08-02 02:00:00"
    assert rows["done-task"]["status"] == "done"
    assert rows["failed-task"]["status"] == "failed"
    assert rows["done-task"]["done_at"] == ""


def test_recover_inflight_tasks_returns_zero_when_no_active_tasks(tmp_path: Path) -> None:
    connect, lock = _init_recovery_db(tmp_path)

    count = recover_inflight_tasks_on_startup(
        connect=connect,
        sql_lock=lock,
        now_func=lambda: "2026-08-02 02:00:00",
    )

    assert count == 0
