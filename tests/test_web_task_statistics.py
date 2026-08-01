from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from docxtool.web.database_schema import initialize_web_database
from docxtool.web.monitoring import normalize_monitor_query, page_count
from docxtool.web.task_statistics import get_task_statistics, log_task_result


def _connect_factory(db_path: Path):
    """传入数据库路径，返回测试用 SQLite 连接工厂。"""

    def connect():
        """无需传入数据，返回带 Row 工厂的 SQLite 连接。"""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _empty_seed(_conn: sqlite3.Connection) -> None:
    """传入初始化连接，测试统计模块时不写默认模板并返回 None。"""
    return None


def _init_stats_db(tmp_path: Path):
    """传入 pytest 临时目录，返回已初始化的连接工厂和线程锁。"""
    db_path = tmp_path / "stats.db"
    connect = _connect_factory(db_path)
    lock = threading.Lock()
    initialize_web_database(connect, lock, _empty_seed)
    return connect, lock


def _log_sample_task(connect, lock, task_id: str, ip: str, filename: str, status: str = "done") -> None:
    """传入连接工厂、锁和任务字段，写入一条测试统计记录。"""
    log_task_result(
        task_id,
        ip,
        "ua",
        filename,
        1024,
        "NORMAL",
        3,
        1,
        2,
        1200,
        status,
        "err" if status != "done" else "",
        connect=connect,
        sql_lock=lock,
        now_func=lambda: "2026-08-02 01:00:00",
    )


def test_log_task_result_updates_task_row_and_daily_stats(tmp_path: Path) -> None:
    connect, lock = _init_stats_db(tmp_path)

    log_task_result(
        "task-a",
        "203.0.113.7",
        "ua",
        "a.docx",
        2048,
        "NORMAL",
        8,
        2,
        6,
        2500,
        "done",
        "",
        "task-a.log",
        "logs/task-a.log",
        "outputs",
        "a_out.docx",
        "outputs/a_out.docx",
        "{}",
        "preset-a",
        "",
        "",
        connect=connect,
        sql_lock=lock,
        now_func=lambda: "2026-08-02 01:02:03",
    )

    conn = connect()
    try:
        task = conn.execute("SELECT * FROM tasks WHERE id='task-a'").fetchone()
        day = conn.execute("SELECT * FROM daily_stats WHERE date='2026-08-02'").fetchone()
    finally:
        conn.close()

    assert task["status"] == "done"
    assert task["log_filename"] == "task-a.log"
    assert task["safe_download_filename"] == "a_out.docx"
    assert task["processing_options"] == "{}"
    assert task["preset_id"] == "preset-a"
    assert dict(day) == {
        "date": "2026-08-02",
        "total": 1,
        "done": 1,
        "error": 0,
        "total_bytes": 2048,
        "total_ms": 2500,
        "unique_ips": 1,
    }


def test_get_task_statistics_returns_monitor_counts_and_top_ips(tmp_path: Path) -> None:
    connect, lock = _init_stats_db(tmp_path)
    _log_sample_task(connect, lock, "t1", "203.0.113.8", "old.docx", "done")
    _log_sample_task(connect, lock, "t2", "203.0.113.8", "new.docx", "failed")
    _log_sample_task(connect, lock, "t3", "198.51.100.2", "other.docx", "done")

    stats = get_task_statistics(
        {"recent_size": 2, "recent_page": 1, "ip_size": 10, "ip_page": 1},
        connect=connect,
        sql_lock=lock,
        normalize_query=normalize_monitor_query,
        page_count=page_count,
    )

    top = {row["ip"]: row for row in stats["top_ips"]}
    assert stats["total"] == 3
    assert stats["done"] == 2
    assert stats["error"] == 1
    assert stats["unique_ips"] == 2
    assert stats["recent_pages"] == 2
    assert [row["filename"] for row in stats["recent"]] == ["other.docx", "new.docx"]
    assert top["203.0.113.8"]["c"] == 2
    assert top["203.0.113.8"]["done"] == 1
    assert top["203.0.113.8"]["error"] == 1
    assert top["203.0.113.8"]["last_filename"] == "new.docx"


def test_get_task_statistics_clamps_pages_for_empty_database(tmp_path: Path) -> None:
    connect, lock = _init_stats_db(tmp_path)

    stats = get_task_statistics(
        {"recent_page": 99, "ip_page": 99},
        connect=connect,
        sql_lock=lock,
        normalize_query=normalize_monitor_query,
        page_count=page_count,
    )

    assert stats["total"] == 0
    assert stats["recent_page"] == 1
    assert stats["ip_page"] == 1
    assert stats["recent"] == []
    assert stats["top_ips"] == []
