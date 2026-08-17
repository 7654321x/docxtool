"""任务记录表的排队、处理中和终态写入辅助。"""

from __future__ import annotations

from typing import Any, Callable


def record_task_queued(
    task_id: str,
    ip: str,
    ua: str,
    filename: str,
    file_size: int = 0,
    processing_options: str = "",
    preset_id: str = "",
    owner_id: str = "",
    *,
    connect: Callable[[], Any],
    sql_lock,
    now_func: Callable[[], str],
    safe_download_filename: Callable[[str], str],
) -> None:
    """传入任务基础信息和数据库依赖，写入或刷新 queued 状态的任务记录。"""
    now = now_func()
    with sql_lock:
        conn = connect()
        try:
            conn.execute(
                """INSERT INTO tasks (id,ip,ua,filename,file_size,doc_type,
                   paragraphs,headings,body,duration_ms,status,error,
                   log_filename,log_path,output_dir,output_filename,output_path,
                   client_ip,original_filename,safe_download_filename,input_size,
                   processing_options,preset_id,owner_id,
                   created_at,done_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                   ip=excluded.ip, ua=excluded.ua, filename=excluded.filename,
                   file_size=excluded.file_size, status='queued', error='',
                   output_dir='', output_filename='', output_path='',
                   client_ip=excluded.client_ip, original_filename=excluded.original_filename,
                   safe_download_filename=excluded.safe_download_filename,
                   input_size=excluded.input_size,
                   processing_options=excluded.processing_options,
                   preset_id=excluded.preset_id,
                   owner_id=excluded.owner_id,
                   created_at=excluded.created_at, done_at=''""",
                (
                    task_id,
                    ip,
                    ua,
                    filename,
                    file_size,
                    "",
                    0,
                    0,
                    0,
                    0,
                    "queued",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    ip,
                    filename,
                    safe_download_filename(filename),
                    file_size,
                    processing_options,
                    preset_id,
                    owner_id,
                    now,
                    "",
                ),
            )
            conn.commit()
        finally:
            conn.close()


def mark_task_processing(
    task_id: str,
    *,
    connect: Callable[[], Any],
    sql_lock,
    now_func: Callable[[], str],
) -> None:
    """传入任务 ID 和数据库依赖，将任务记录更新为 processing 状态。"""
    now = now_func()
    with sql_lock:
        conn = connect()
        try:
            conn.execute(
                "UPDATE tasks SET status='processing', started_at=?, error='', done_at='' WHERE id=?",
                (now, task_id),
            )
            conn.commit()
        finally:
            conn.close()


def mark_task_terminal(
    task_id: str,
    status: str,
    error: str = "",
    output_path: str = "",
    output_filename: str = "",
    log_path: str = "",
    log_filename: str = "",
    *,
    connect: Callable[[], Any],
    sql_lock,
    now_func: Callable[[], str],
) -> None:
    """传入任务 ID、终态字段和数据库依赖，将任务记录更新为最终状态。"""
    now = now_func()
    with sql_lock:
        conn = connect()
        try:
            conn.execute(
                """UPDATE tasks SET status=?, error=?, output_path=?, output_filename=?,
                   log_path=?, log_filename=?, done_at=? WHERE id=?""",
                (status, error, output_path, output_filename, log_path, log_filename, now, task_id),
            )
            conn.commit()
        finally:
            conn.close()
