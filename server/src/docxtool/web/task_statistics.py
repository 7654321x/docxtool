"""Task result statistics persistence and monitor summaries."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock


ERROR_STATUSES = ("error", "timeout", "failed", "interrupted", "expired")
TASK_STATUSES = frozenset(("queued", "processing", "done", *ERROR_STATUSES))


def log_task_result(
    task_id,
    ip,
    ua,
    filename,
    file_size,
    doc_type,
    paragraphs,
    headings,
    body,
    duration_ms,
    status="done",
    error="",
    log_filename="",
    log_path="",
    output_dir="",
    output_filename="",
    output_path="",
    processing_options="",
    preset_id="",
    error_code="",
    error_message="",
    *,
    connect: Callable,
    sql_lock: Lock,
    now_func: Callable[[], str],
) -> None:
    """传入任务结果、连接工厂、锁和当前时间函数，写入 tasks 与 daily_stats 后返回 None。"""
    now = now_func()
    today = now[:10]
    done_count = 1 if status == "done" else 0
    error_count = 1 if status in ("error", "timeout", "failed") else 0
    with sql_lock:
        conn = connect()
        try:
            conn.execute(
                """INSERT INTO tasks (id,ip,ua,filename,file_size,doc_type,
                   paragraphs,headings,body,duration_ms,status,error,
                   log_filename,log_path,output_dir,output_filename,output_path,
                   client_ip,original_filename,safe_download_filename,input_size,
                   processing_options,preset_id,error_code,error_message,
                   created_at,done_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                   ip=excluded.ip, ua=excluded.ua, filename=excluded.filename,
                   file_size=excluded.file_size, doc_type=excluded.doc_type,
                   paragraphs=excluded.paragraphs, headings=excluded.headings,
                   body=excluded.body, duration_ms=excluded.duration_ms,
                   status=excluded.status, error=excluded.error,
                   log_filename=excluded.log_filename, log_path=excluded.log_path,
                   output_dir=excluded.output_dir, output_filename=excluded.output_filename,
                   output_path=excluded.output_path,
                   client_ip=excluded.client_ip,
                   original_filename=excluded.original_filename,
                   safe_download_filename=excluded.safe_download_filename,
                   input_size=excluded.input_size,
                   processing_options=excluded.processing_options,
                   preset_id=excluded.preset_id,
                   error_code=excluded.error_code,
                   error_message=excluded.error_message,
                   done_at=excluded.done_at""",
                (
                    task_id,
                    ip,
                    ua,
                    filename,
                    file_size,
                    doc_type,
                    paragraphs,
                    headings,
                    body,
                    duration_ms,
                    status,
                    error,
                    log_filename,
                    log_path,
                    output_dir,
                    output_filename,
                    output_path,
                    ip,
                    filename,
                    output_filename,
                    file_size,
                    processing_options,
                    preset_id,
                    error_code,
                    error_message,
                    now,
                    now,
                ),
            )
            conn.execute(
                """INSERT INTO daily_stats (date,total,done,error,total_bytes,total_ms)
                   VALUES (?,1,?,?,?,?)
                   ON CONFLICT(date) DO UPDATE SET total=total+1,
                   done=done+?, error=error+?, total_bytes=total_bytes+?,
                   total_ms=total_ms+?""",
                (
                    today,
                    done_count,
                    error_count,
                    file_size,
                    duration_ms,
                    done_count,
                    error_count,
                    file_size,
                    duration_ms,
                ),
            )
            conn.execute(
                """UPDATE daily_stats SET unique_ips=(
                   SELECT COUNT(DISTINCT ip) FROM tasks WHERE date(created_at)=?)
                   WHERE date=?""",
                (today, today),
            )
            conn.commit()
        finally:
            conn.close()


def get_task_statistics(
    query: dict | None = None,
    *,
    connect: Callable,
    sql_lock: Lock,
    normalize_query: Callable[[dict | None], dict],
    page_count: Callable[[int, int], int],
) -> dict:
    """传入查询参数、连接工厂、锁和分页函数，返回监控页使用的脱敏统计字典。"""
    query = normalize_query(query)
    recent_size = query["recent_size"]
    ip_size = query["ip_size"]
    task_clause, task_params = _task_where(query)
    done_clause = _append_condition(task_clause, "status='done'")
    with sql_lock:
        conn = connect()
        try:
            total = conn.execute(f"SELECT COUNT(*) as c FROM tasks{task_clause}", task_params).fetchone()["c"]
            done = conn.execute(
                f"SELECT COUNT(*) as c FROM tasks{done_clause}",
                task_params,
            ).fetchone()["c"]
            err = _count_error_tasks(conn, task_clause, task_params)
            ips = conn.execute(f"SELECT COUNT(DISTINCT ip) as c FROM tasks{task_clause}", task_params).fetchone()["c"]
            tbytes = conn.execute(f"SELECT COALESCE(SUM(file_size),0) as c FROM tasks{task_clause}", task_params).fetchone()["c"]
            avg_p = conn.execute(
                f"SELECT AVG(paragraphs) as c FROM tasks{done_clause}",
                task_params,
            ).fetchone()["c"] or 0
            avg_ms = conn.execute(
                f"SELECT AVG(duration_ms) as c FROM tasks{done_clause}",
                task_params,
            ).fetchone()["c"] or 0
            recent_pages = page_count(total, recent_size)
            recent_page = min(query["recent_page"], recent_pages)
            recent_offset = (recent_page - 1) * recent_size
            ip_pages = page_count(ips, ip_size)
            ip_page = min(query["ip_page"], ip_pages)
            ip_offset = (ip_page - 1) * ip_size
            query["recent_page"] = recent_page
            query["ip_page"] = ip_page
            recent = conn.execute(
                f"SELECT * FROM tasks{task_clause} ORDER BY rowid DESC LIMIT ? OFFSET ?",
                [*task_params, recent_size, recent_offset],
            ).fetchall()
            days = _load_daily_trend(conn)
            top_ips = _load_top_ips(conn, ip_size, ip_offset)
            banned = conn.execute("SELECT * FROM banned_ips ORDER BY created_at DESC").fetchall()
        finally:
            conn.close()
    return _build_stats_payload(
        total,
        done,
        err,
        ips,
        tbytes,
        avg_p,
        avg_ms,
        query,
        recent,
        recent_page,
        recent_size,
        recent_pages,
        days,
        top_ips,
        ip_page,
        ip_size,
        ip_pages,
        banned,
    )


def _task_where(query: dict) -> tuple[str, list[object]]:
    """Build a parameterized task filter for the new Web task and log pages."""
    clauses: list[str] = []
    params: list[object] = []
    search = str(query.get("task_q", "") or "").strip()[:80]
    status = str(query.get("task_status", "") or "").strip()[:20]
    if search:
        pattern = f"%{search}%"
        clauses.append("(id LIKE ? OR filename LIKE ?)")
        params.extend((pattern, pattern))
    if status in TASK_STATUSES:
        clauses.append("status=?")
        params.append(status)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def _append_condition(clause: str, condition: str) -> str:
    """Append a fixed SQL condition to an optional existing WHERE clause."""
    return f"{clause} AND {condition}" if clause else f" WHERE {condition}"


def _count_error_tasks(conn, clause: str = "", params: list[object] | tuple[object, ...] = ()) -> int:
    """传入 SQLite 连接，返回监控中计为失败的任务数量。"""
    placeholders = ",".join("?" for _ in ERROR_STATUSES)
    return conn.execute(
        f"SELECT COUNT(*) as c FROM tasks{_append_condition(clause, f'status IN ({placeholders})')}",
        [*params, *ERROR_STATUSES],
    ).fetchone()["c"]


def _load_daily_trend(conn) -> list:
    """传入 SQLite 连接，返回按日期聚合的任务趋势行列表。"""
    return conn.execute(
        """
        SELECT date(created_at) as date,
               COUNT(*) as total,
               SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
               SUM(CASE WHEN status IN ('error','timeout','failed','interrupted','expired') THEN 1 ELSE 0 END) as error
        FROM tasks
        GROUP BY date(created_at)
        ORDER BY date(created_at)
        """
    ).fetchall()


def _load_top_ips(conn, ip_size: int, ip_offset: int) -> list[dict]:
    """传入连接、页大小和偏移量，返回 IP 维度聚合后的监控行。"""
    top_rows = conn.execute(
        """
        SELECT t.ip, COUNT(*) as c,
               SUM(CASE WHEN t.status='done' THEN 1 ELSE 0 END) as done,
               SUM(CASE WHEN t.status IN ('error','timeout','failed','interrupted','expired') THEN 1 ELSE 0 END) as error,
               MAX(t.created_at) as last,
               MAX(t.rowid) as last_rowid
        FROM tasks t
        GROUP BY t.ip
        ORDER BY last_rowid DESC, c DESC
        LIMIT ? OFFSET ?
        """,
        [ip_size, ip_offset],
    ).fetchall()
    top_ips = []
    for row in top_rows:
        item = dict(row)
        last = conn.execute(
            "SELECT filename, created_at FROM tasks WHERE ip=? ORDER BY rowid DESC LIMIT 1",
            [item.get("ip", "")],
        ).fetchone()
        item["last_filename"] = last["filename"] if last else ""
        item["last"] = last["created_at"] if last else item.get("last", "")
        top_ips.append(item)
    return top_ips


def _build_stats_payload(
    total,
    done,
    err,
    ips,
    tbytes,
    avg_p,
    avg_ms,
    query,
    recent,
    recent_page,
    recent_size,
    recent_pages,
    days,
    top_ips,
    ip_page,
    ip_size,
    ip_pages,
    banned,
) -> dict:
    """传入统计原始值和分页结果，返回监控页/API 使用的最终字典。"""
    return {
        "total": total,
        "done": done,
        "error": err,
        "unique_ips": ips,
        "total_mb": round(tbytes / 1048576, 1),
        "avg_s": round(avg_ms / 1000, 2) if avg_ms else 0,
        "avg_paragraphs": round(avg_p, 1),
        "rate": round(done / total * 100, 1) if total else 0,
        "query": query,
        "recent": [dict(r) for r in recent],
        "recent_total": total,
        "recent_page": recent_page,
        "recent_size": recent_size,
        "recent_pages": recent_pages,
        "trend": [dict(d) for d in days],
        "top_ips": top_ips,
        "ip_total": ips,
        "ip_page": ip_page,
        "ip_size": ip_size,
        "ip_pages": ip_pages,
        "banned_ips": [dict(r) for r in banned],
    }
