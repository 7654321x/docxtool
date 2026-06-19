"""server — 公文排版 Web 服务。

功能：上传 .docx → 自动排版 → 下载
监控：/monitor（统计面板）/stats（JSON API）
安全：SQL 参数化查询 / UUID 校验 / XSS 转义 / 安全头 / 限流 / 文件大小限制
存储：SQLite（stats.db）
启动：python server.py
访问：http://localhost:9527
"""

import os
import sys
import json
import uuid
import time
import hashlib
import hmac
import socket
import threading
import tempfile
import logging
import html
import ipaddress
from datetime import timezone, timedelta
from email.utils import parsedate_to_datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from collections import OrderedDict
from urllib.parse import unquote, urlparse, parse_qs, quote, urlencode
from urllib.request import Request, urlopen

from importer import DocxImporter
from engine import export_doc
from style_config import (
    StyleRule, PageSettings, configure_logging, get_logger,
    make_document_log_path, set_context_log_path, reset_context_log_path,
)

import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_SQL_LOCK = threading.Lock()
_DB_PATH = os.path.join(BASE_DIR, "stats.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

def _sql():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _sql_init():
    with _SQL_LOCK:
        conn = _sql()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, ip TEXT NOT NULL, ua TEXT DEFAULT '',
                filename TEXT DEFAULT '', file_size INTEGER DEFAULT 0,
                doc_type TEXT DEFAULT '', paragraphs INTEGER DEFAULT 0,
                headings INTEGER DEFAULT 0, body INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0, status TEXT DEFAULT 'pending',
                error TEXT DEFAULT '',
                log_filename TEXT DEFAULT '', log_path TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                done_at TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY, total INTEGER DEFAULT 0,
                done INTEGER DEFAULT 0, error INTEGER DEFAULT 0,
                total_bytes INTEGER DEFAULT 0, total_ms INTEGER DEFAULT 0,
                unique_ips INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS banned_ips (
                ip TEXT PRIMARY KEY,
                reason TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_ip ON tasks(ip);
            CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
            CREATE INDEX IF NOT EXISTS idx_tasks_ip_created ON tasks(ip, created_at);
        """)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "log_filename" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN log_filename TEXT DEFAULT ''")
        if "log_path" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN log_path TEXT DEFAULT ''")
        conn.commit()
        conn.close()

_sql_init()

DEFAULT_MONITOR_PAGE_SIZE = 50
MAX_MONITOR_PAGE_SIZE = 100

def _first_query_value(values: dict, key: str, default=""):
    raw = values.get(key, default) if values else default
    if isinstance(raw, list):
        return raw[0] if raw else default
    return raw

def _clamp_int(value, default: int, min_value: int = 1, max_value: int = MAX_MONITOR_PAGE_SIZE) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(min_value, min(max_value, n))

def _now_local() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

_BEIJING_TZ = timezone(timedelta(hours=8))
_NETWORK_TIME_URLS = (
    "https://www.baidu.com/",
    "https://www.cloudflare.com/",
)

def _parse_http_date_to_beijing(date_header: str):
    dt = parsedate_to_datetime(date_header)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_BEIJING_TZ)

def _fetch_beijing_network_time(timeout: int = 3):
    last_error = None
    for url in _NETWORK_TIME_URLS:
        try:
            req = Request(
                url,
                method="HEAD",
                headers={"User-Agent": "docx-tool-time-check/1.0"},
            )
            with urlopen(req, timeout=timeout) as resp:
                date_header = resp.headers.get("Date")
            if date_header:
                return _parse_http_date_to_beijing(date_header)
            last_error = RuntimeError(f"{url} missing Date header")
        except Exception as exc:
            last_error = exc
    raise RuntimeError(str(last_error) if last_error else "no network time source")

def _startup_time_check_lines() -> list:
    system_time = _now_local()
    try:
        beijing_time = _fetch_beijing_network_time()
    except Exception as exc:
        return [f"时间校验: 未能获取北京网络时间，继续启动。原因: {exc}"]

    beijing_text = beijing_time.strftime("%Y-%m-%d %H:%M:%S")
    if system_time[:16] == beijing_text[:16]:
        return [f"时间校验: 通过，系统时间与北京网络时间相同（{system_time[:16]}）"]
    return [
        "时间校验: 系统时间与北京网络时间不一致，建议检查服务器时区/NTP。",
        f"系统时间为：{system_time[:16]}",
        f"北京时间为：{beijing_text[:16]}",
        "可执行: sudo timedatectl set-timezone Asia/Shanghai",
        "可执行: sudo timedatectl set-ntp true",
    ]

def _monitor_query_from(parsed) -> dict:
    return _normalize_monitor_query(parse_qs(parsed.query))

def _normalize_monitor_query(values: dict = None) -> dict:
    values = values or {}
    return {
        "recent_page": _clamp_int(_first_query_value(values, "recent_page", 1), 1),
        "recent_size": _clamp_int(_first_query_value(values, "recent_size", DEFAULT_MONITOR_PAGE_SIZE), DEFAULT_MONITOR_PAGE_SIZE),
        "ip_page": _clamp_int(_first_query_value(values, "ip_page", 1), 1),
        "ip_size": _clamp_int(_first_query_value(values, "ip_size", DEFAULT_MONITOR_PAGE_SIZE), DEFAULT_MONITOR_PAGE_SIZE),
    }

def _where_sql(clauses) -> str:
    return " WHERE " + " AND ".join(clauses) if clauses else ""

def _page_count(total: int, size: int) -> int:
    return max(1, (int(total) + int(size) - 1) // int(size))

def log_sql(task_id, ip, ua, filename, file_size, doc_type,
            paragraphs, headings, body, duration_ms, status="done", error="",
            log_filename="", log_path=""):
    now = _now_local()
    today = now[:10]
    with _SQL_LOCK:
        conn = _sql()
        conn.execute("""INSERT INTO tasks (id,ip,ua,filename,file_size,doc_type,
                       paragraphs,headings,body,duration_ms,status,error,
                       log_filename,log_path,created_at,done_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                       ip=excluded.ip, ua=excluded.ua, filename=excluded.filename,
                       file_size=excluded.file_size, doc_type=excluded.doc_type,
                       paragraphs=excluded.paragraphs, headings=excluded.headings,
                       body=excluded.body, duration_ms=excluded.duration_ms,
                       status=excluded.status, error=excluded.error,
                       log_filename=excluded.log_filename, log_path=excluded.log_path,
                       done_at=excluded.done_at""",
                      (task_id, ip, ua, filename, file_size, doc_type,
                       paragraphs, headings, body, duration_ms, status, error,
                       log_filename, log_path, now, now))
        conn.execute("""INSERT INTO daily_stats (date,total,done,error,total_bytes,total_ms)
                       VALUES (?,1,?,?,?,?)
                       ON CONFLICT(date) DO UPDATE SET total=total+1,
                       done=done+?, error=error+?, total_bytes=total_bytes+?,
                       total_ms=total_ms+?""",
                     (today, 1 if status == "done" else 0,
                      1 if status == "error" else 0, file_size, duration_ms,
                      1 if status == "done" else 0, 1 if status == "error" else 0,
                      file_size, duration_ms))
        conn.execute("""UPDATE daily_stats SET unique_ips=(
                       SELECT COUNT(DISTINCT ip) FROM tasks WHERE date(created_at)=?)
                       WHERE date=?""", (today, today))
        conn.commit()
        conn.close()

def record_task_queued(task_id: str, ip: str, ua: str, filename: str, file_size: int = 0):
    now = _now_local()
    with _SQL_LOCK:
        conn = _sql()
        conn.execute("""INSERT INTO tasks (id,ip,ua,filename,file_size,doc_type,
                       paragraphs,headings,body,duration_ms,status,error,
                       log_filename,log_path,created_at,done_at)
                       VALUES (?,?,?,?,?, '',0,0,0,0,'queued','','','',?,'')
                       ON CONFLICT(id) DO UPDATE SET
                       ip=excluded.ip, ua=excluded.ua, filename=excluded.filename,
                       file_size=excluded.file_size, status='queued', error='',
                       created_at=excluded.created_at, done_at=''""",
                     (task_id, ip, ua, filename, file_size, now))
        conn.commit()
        conn.close()

def get_sql_stats(query: dict = None):
    query = _normalize_monitor_query(query)
    recent_size = query["recent_size"]
    ip_size = query["ip_size"]
    with _SQL_LOCK:
        conn = _sql()
        total = conn.execute("SELECT COUNT(*) as c FROM tasks").fetchone()["c"]
        done = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status='done'").fetchone()["c"]
        err = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status='error'").fetchone()["c"]
        ips = conn.execute("SELECT COUNT(DISTINCT ip) as c FROM tasks").fetchone()["c"]
        tbytes = conn.execute("SELECT COALESCE(SUM(file_size),0) as c FROM tasks").fetchone()["c"]
        tms = conn.execute("SELECT COALESCE(SUM(duration_ms),0) as c FROM tasks").fetchone()["c"]
        avg_p = conn.execute("SELECT AVG(paragraphs) as c FROM tasks WHERE status='done'").fetchone()["c"] or 0
        avg_ms = conn.execute("SELECT AVG(duration_ms) as c FROM tasks WHERE status='done'").fetchone()["c"] or 0
        recent_pages = _page_count(total, recent_size)
        recent_page = min(query["recent_page"], recent_pages)
        recent_offset = (recent_page - 1) * recent_size
        ip_pages = _page_count(ips, ip_size)
        ip_page = min(query["ip_page"], ip_pages)
        ip_offset = (ip_page - 1) * ip_size
        query["recent_page"] = recent_page
        query["ip_page"] = ip_page
        recent = conn.execute(
            "SELECT * FROM tasks ORDER BY rowid DESC LIMIT ? OFFSET ?",
            [recent_size, recent_offset],
        ).fetchall()
        days = conn.execute(f"""
            SELECT date(created_at) as date,
                   COUNT(*) as total,
                   SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as error
            FROM tasks
            GROUP BY date(created_at)
            ORDER BY date(created_at)
        """).fetchall()
        top_rows = conn.execute(f"""
            SELECT t.ip, COUNT(*) as c,
                   SUM(CASE WHEN t.status='done' THEN 1 ELSE 0 END) as done,
                   SUM(CASE WHEN t.status='error' THEN 1 ELSE 0 END) as error,
                   MAX(t.created_at) as last,
                   MAX(t.rowid) as last_rowid
            FROM tasks t
            GROUP BY t.ip
            ORDER BY last_rowid DESC, c DESC
            LIMIT ? OFFSET ?
        """, [ip_size, ip_offset]).fetchall()
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
        banned = conn.execute("SELECT * FROM banned_ips ORDER BY created_at DESC").fetchall()
        conn.close()
    return {
        "total": total, "done": done, "error": err, "unique_ips": ips,
        "total_mb": round(tbytes/1048576, 1),
        "avg_s": round(avg_ms/1000, 2) if avg_ms else 0,
        "avg_paragraphs": round(avg_p, 1),
        "rate": round(done/total*100, 1) if total else 0,
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

PORT = int(os.environ.get("PORT", "9527"))
BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
APP_VERSION = "2026.06.01"
STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S")
DEFAULT_ADMIN_TOKEN = "7654321xxx"
DEFAULT_PROXY_SECRET = "docxtool-proxy-20260601-9ec0d6e2443a4f5f9784f0f04bb62917"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN)
PROXY_SECRET = os.environ.get("PROXY_SECRET", DEFAULT_PROXY_SECRET)
FRONTEND_ORIGIN = ""  # 例如 "https://xxx.pages.dev"；留空表示允许任意来源，方便临时测试。
MAX_SIZE = 10 * 1024 * 1024
MAX_WORKERS = 4
MAX_QUEUE = MAX_WORKERS * 2
PROCESS_TIMEOUT = 30
RATE_WINDOW = 2
FILE_TTL = 86400
MAX_TASKS = 200
DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS = 3600
DEFAULT_UPLOAD_LIMIT_COUNT = 10

RATE_LIMIT = {}
RATE_LOCK = threading.Lock()
TASKS = OrderedDict()
TASKS_LOCK = threading.Lock()
TASK_QUEUE = OrderedDict()
QUEUE_COND = threading.Condition()
WORKERS_STARTED = False
WORKERS_LOCK = threading.Lock()
WORKER_THREADS = []

OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def _startup_cleanup():
    import glob as _glob
    tmp = tempfile.gettempdir()
    count = 0
    for f in _glob.glob(os.path.join(tmp, "tmp*.docx")):
        try: os.unlink(f); count += 1
        except: pass
    if count: logger.info(f"[Startup] cleaned {count} temp files")

configure_logging(LOG_DIR, to_file=True)
logger = get_logger()
logging.getLogger("docx_tool").setLevel(logging.DEBUG)
for h in logging.getLogger("docx_tool").handlers:
    if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
        h.setLevel(logging.WARNING)

_startup_cleanup()

def _read_exact(rfile, length: int, timeout: int = 10) -> bytes:
    data = b""; remaining = length; t0 = time.time()
    while remaining > 0:
        if time.time() - t0 > timeout: raise TimeoutError(f"read timeout")
        chunk = rfile.read(remaining)
        if not chunk: time.sleep(0.01); continue
        data += chunk; remaining -= len(chunk)
    return data

def _allow(ip: str) -> bool:
    now = time.time()
    with RATE_LOCK:
        last = RATE_LIMIT.get(ip, 0)
        if now - last < RATE_WINDOW: return False
        RATE_LIMIT[ip] = now
    return True

def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(str(value or "").strip())
        return True
    except ValueError:
        return False

def _is_ip_banned(ip: str) -> bool:
    if not ip:
        return False
    with _SQL_LOCK:
        conn = _sql()
        row = conn.execute("SELECT 1 FROM banned_ips WHERE ip=?", (ip,)).fetchone()
        conn.close()
    return row is not None

def _ban_ip(ip: str, reason: str = "") -> None:
    if not _is_ip(ip):
        raise ValueError("invalid ip")
    with _SQL_LOCK:
        conn = _sql()
        conn.execute("""INSERT INTO banned_ips(ip, reason, created_at)
                        VALUES(?,?,datetime('now','localtime'))
                        ON CONFLICT(ip) DO UPDATE SET
                        reason=excluded.reason, created_at=excluded.created_at""",
                     (ip, reason or "manual"))
        conn.commit()
        conn.close()

def _unban_ip(ip: str) -> None:
    with _SQL_LOCK:
        conn = _sql()
        conn.execute("DELETE FROM banned_ips WHERE ip=?", (ip,))
        conn.commit()
        conn.close()

def _banned_ips():
    with _SQL_LOCK:
        conn = _sql()
        rows = conn.execute("SELECT * FROM banned_ips ORDER BY created_at DESC").fetchall()
        conn.close()
    return [dict(r) for r in rows]

def _ip_activity(ip: str, limit: int = 100):
    with _SQL_LOCK:
        conn = _sql()
        rows = conn.execute("""SELECT * FROM tasks WHERE ip=?
                               ORDER BY created_at DESC, done_at DESC
                               LIMIT ?""", (ip, limit)).fetchall()
        conn.close()
    return [dict(r) for r in rows]

def _ip_upload_count(ip: str, window_seconds: int = 0) -> int:
    with _SQL_LOCK:
        conn = _sql()
        if window_seconds and window_seconds > 0:
            row = conn.execute("""SELECT COUNT(*) as c FROM tasks
                                  WHERE ip=? AND created_at>=datetime('now','localtime', ?)""",
                               (ip, f"-{int(window_seconds)} seconds")).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE ip=?", (ip,)).fetchone()
        conn.close()
    return int(row["c"] if row else 0)

def _upload_limit_exceeded(ip: str) -> bool:
    settings = _limit_settings()
    if not settings["enabled"]:
        return False
    return _ip_upload_count(ip, settings["window_seconds"]) >= settings["count"]

def _settings_get(key: str, default: str = "") -> str:
    with _SQL_LOCK:
        conn = _sql()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close()
    return row["value"] if row else default

def _settings_set(key: str, value: str) -> None:
    with _SQL_LOCK:
        conn = _sql()
        conn.execute("""INSERT INTO settings(key,value) VALUES(?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                     (key, str(value)))
        conn.commit()
        conn.close()

def _limit_settings() -> dict:
    enabled = _settings_get("upload_limit_enabled", "0") == "1"
    try:
        window_seconds = int(_settings_get("upload_limit_window_seconds", str(DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS)))
    except ValueError:
        window_seconds = DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS
    try:
        count = int(_settings_get("upload_limit_count", str(DEFAULT_UPLOAD_LIMIT_COUNT)))
    except ValueError:
        count = DEFAULT_UPLOAD_LIMIT_COUNT
    return {
        "enabled": enabled,
        "window_seconds": max(1, window_seconds),
        "count": max(1, count),
    }

def _save_limit_settings(enabled: bool, window_seconds: int, count: int) -> None:
    _settings_set("upload_limit_enabled", "1" if enabled else "0")
    _settings_set("upload_limit_window_seconds", str(max(1, int(window_seconds))))
    _settings_set("upload_limit_count", str(max(1, int(count))))

def _active_count() -> int:
    with TASKS_LOCK:
        return sum(1 for t in TASKS.values() if t.get("status") == "processing")

def _queued_count() -> int:
    with QUEUE_COND:
        return len(TASK_QUEUE)

def _task_load() -> int:
    return _active_count() + _queued_count()

def _task_queue_info(task_id: str) -> dict:
    with QUEUE_COND:
        ids = list(TASK_QUEUE.keys())
    if task_id not in ids:
        return {"queue_position": 0, "queue_ahead": 0, "message": ""}
    idx = ids.index(task_id)
    return {
        "queue_position": idx + 1,
        "queue_ahead": idx,
        "message": f"排队中，前方还有 {idx} 个任务",
    }

def _public_task_state(task_id: str) -> dict:
    with TASKS_LOCK:
        task = dict(TASKS.get(task_id, {}))
    if not task:
        return {}
    task.pop("output", None)
    status = task.get("status", "")
    if status == "queued":
        task.update(_task_queue_info(task_id))
    elif status == "processing":
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "正在排版"})
    elif status == "done":
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "排版完成"})
    elif status == "error":
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "排版失败"})
    return task

def _enqueue_task(task_id: str, input_path: str, orig_name: str, ip: str, ua: str) -> dict:
    now = time.time()
    try:
        file_size = os.path.getsize(input_path) if input_path and os.path.exists(input_path) else 0
    except OSError:
        file_size = 0
    record_task_queued(task_id, ip, ua, orig_name, file_size)
    with TASKS_LOCK:
        TASKS[task_id] = {"status": "queued", "time": now, "queued_at": now}
    with QUEUE_COND:
        TASK_QUEUE[task_id] = (input_path, orig_name, ip, ua)
        info = _task_queue_info(task_id)
        QUEUE_COND.notify()
    return info

def _worker_loop():
    while True:
        with QUEUE_COND:
            while not TASK_QUEUE:
                QUEUE_COND.wait()
            task_id, payload = TASK_QUEUE.popitem(last=False)
        input_path, orig_name, ip, ua = payload
        with TASKS_LOCK:
            task = TASKS.get(task_id, {})
            task["status"] = "processing"
            task["started_at"] = time.time()
            task["queue_ahead"] = 0
            task["queue_position"] = 0
            TASKS[task_id] = task
        _process_task(task_id, input_path, orig_name, ip, ua)

def _ensure_workers_started():
    global WORKERS_STARTED
    with WORKERS_LOCK:
        if WORKERS_STARTED:
            return
        for i in range(MAX_WORKERS):
            t = threading.Thread(target=_worker_loop, name=f"docx-worker-{i+1}", daemon=True)
            t.start()
            WORKER_THREADS.append(t)
        WORKERS_STARTED = True

def _process_task(task_id: str, input_path: str, orig_name: str = "upload.docx", ip: str = "", ua: str = ""):
    t0 = time.time(); output_path = None
    log_path = make_document_log_path(orig_name, log_dir=LOG_DIR, suffix=task_id[:8])
    log_filename = os.path.basename(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [INFO ] docx_tool | [Task] {task_id[:8]} log created file={orig_name}\n")
    token = set_context_log_path(log_path)
    with TASKS_LOCK:
        t = TASKS.get(task_id, {})
        t["log_filename"] = log_filename
        t["log_url"] = f"/log/{task_id}"
        TASKS[task_id] = t
    try:
        logger.info(f"[Task] {task_id[:8]} start file={orig_name} ip={ip} log={log_filename}")
        rules = StyleRule.from_config(); settings = PageSettings.from_config()
        importer = DocxImporter(); doc_data = importer.load(input_path, rules)
        base = os.path.splitext(orig_name)[0]
        output_path = os.path.join(OUTPUT_DIR, f"{base}_排版文件.docx")
        export_doc(doc_data, rules, settings, output_path, numbered_bold_enabled=True)
        duration = round(time.time() - t0, 2)
        hc = sum(1 for pd in doc_data.paragraphs if pd.type_id.startswith("heading"))
        bc = sum(1 for pd in doc_data.paragraphs if pd.type_id == "body")
        log_sql(task_id, ip, ua, orig_name, os.path.getsize(input_path),
                doc_data.doc_mode or "UNKNOWN", len(doc_data.paragraphs),
                hc, bc, int(duration*1000), "done",
                log_filename=log_filename, log_path=log_path)
        logger.info(f"[Stats] recorded task={task_id[:8]} status=done ip={ip} file={orig_name}")
        with TASKS_LOCK:
            t = TASKS.get(task_id, {}); t["status"] = "done"; t["output"] = output_path
            t["duration"] = duration; t["paragraphs"] = len(doc_data.paragraphs)
            t["log_filename"] = log_filename; t["log_url"] = f"/log/{task_id}"
            t["time"] = time.time(); TASKS[task_id] = t
        logger.info(f"[Task] {task_id[:8]} done {duration}s")
    except Exception as e:
        with TASKS_LOCK:
            t = TASKS.get(task_id, {}); t["status"] = "error"; t["error"] = str(e)[:200]
            t["log_filename"] = log_filename; t["log_url"] = f"/log/{task_id}"
            TASKS[task_id] = t
        try:
            log_sql(task_id, ip, ua, orig_name, 0, "", 0, 0, 0, 0, "error", str(e)[:200],
                    log_filename=log_filename, log_path=log_path)
        except Exception:
            logger.exception(f"[Stats] failed to record error task={task_id[:8]} ip={ip} file={orig_name}")
        logger.exception(f"[Task] {task_id[:8]} error: {e}")
    finally:
        reset_context_log_path(token)
        if os.path.exists(input_path):
            try: os.unlink(input_path)
            except: pass

def _cleanup_expired_outputs(now: float = None) -> dict:
    now = now or time.time()
    removed = 0
    errors = 0
    if not os.path.isdir(OUTPUT_DIR):
        return {"removed": 0, "errors": 0}
    for f in os.listdir(OUTPUT_DIR):
        path = os.path.join(OUTPUT_DIR, f)
        try:
            if os.path.isfile(path) and now - os.path.getmtime(path) > FILE_TTL:
                os.unlink(path)
                removed += 1
        except Exception:
            errors += 1
    return {"removed": removed, "errors": errors}

def _cleaner_loop():
    while True:
        time.sleep(60)
        result = _cleanup_expired_outputs()
        if result["removed"]:
            logger.info(f"[Cleaner] removed {result['removed']} expired files")

threading.Thread(target=_cleaner_loop, daemon=True).start()

def _error_payload(code: str, message: str) -> dict:
    return {"error": message, "code": code}

def _cookie_value(cookie_header: str, name: str) -> str:
    for part in str(cookie_header or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.strip().split("=", 1)
        if key == name:
            return value
    return ""

def _admin_authorized(parsed, headers, cookie_header: str = "") -> bool:
    if not ADMIN_TOKEN:
        return False
    qs = parse_qs(parsed.query)
    token = (qs.get("token") or [""])[0]
    header_token = headers.get("X-Admin-Token", "") if headers else ""
    cookie_token = _cookie_value(cookie_header, "admin_token")
    return ADMIN_TOKEN in (token, header_token, cookie_token)

def _file_api_authorized(headers) -> bool:
    host = (headers.get("Host", "") if headers else "").split(",", 1)[0].strip().lower()
    if host in {f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"}:
        return True
    if not PROXY_SECRET:
        return False
    header_token = headers.get("X-Proxy-Secret", "") if headers else ""
    return hmac.compare_digest(header_token, PROXY_SECRET)

def _admin_token_from(parsed) -> str:
    if not ADMIN_TOKEN:
        return ""
    return (parse_qs(parsed.query).get("token") or [""])[0]

def _admin_url(path: str, token: str = "") -> str:
    if not token:
        return path
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}token={quote(token, safe='')}"

def _admin_hidden_input(token: str = "") -> str:
    if not token:
        return ""
    return f'<input type="hidden" name="token" value="{_html_escape(token)}">'

def _health_payload() -> dict:
    return {"ok": True, "status": "ok"}

def _dir_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".ready-", dir=path)
        os.close(fd)
        os.unlink(tmp)
        return True
    except Exception:
        return False

def _ready_payload() -> dict:
    checks = {"database": False, "output_dir": False, "log_dir": False}
    try:
        with _SQL_LOCK:
            conn = _sql()
            conn.execute("SELECT 1").fetchone()
            conn.close()
        checks["database"] = True
    except Exception:
        checks["database"] = False
    checks["output_dir"] = _dir_writable(OUTPUT_DIR)
    checks["log_dir"] = _dir_writable(LOG_DIR)
    return {"ok": all(checks.values()), "checks": checks}

def _version_payload() -> dict:
    return {
        "version": APP_VERSION,
        "started_at": STARTED_AT,
        "bind_host": BIND_HOST,
        "file_ttl_seconds": FILE_TTL,
        "max_upload_mb": MAX_SIZE // 1048576,
        "max_workers": MAX_WORKERS,
        "max_queue": MAX_QUEUE,
        "proxy_secret_required": True,
        "proxy_secret_configured": bool(PROXY_SECRET),
        "queued": _queued_count(),
        "processing": _active_count(),
    }

def _server_bind_address() -> tuple:
    return (BIND_HOST, PORT)

def _startup_urls() -> dict:
    base = f"http://{BIND_HOST}:{PORT}"
    return {
        "tool": base,
        "monitor": f"{base}{_admin_url('/monitor', ADMIN_TOKEN)}",
        "tunnel_command": f"cloudflared tunnel --url {base}",
    }

def _monitor_url(admin_token: str, query: dict, **overrides) -> str:
    q = dict(query or {})
    q.update(overrides)
    values = {}
    if admin_token:
        values["token"] = admin_token
    for key in ("recent_page", "recent_size", "ip_page", "ip_size"):
        value = q.get(key, "")
        if value != "":
            values[key] = value
    return "/monitor?" + urlencode(values)

def _pager_html(stats: dict, admin_token: str, page_key: str, pages_key: str) -> str:
    query = stats.get("query", _normalize_monitor_query())
    page = int(stats.get(page_key, 1))
    pages = int(stats.get(pages_key, 1))
    prev_page = max(1, page - 1)
    next_page = min(pages, page + 1)
    prev_cls = " disabled" if page <= 1 else ""
    next_cls = " disabled" if page >= pages else ""
    prev_href = _monitor_url(admin_token, query, **{page_key: prev_page})
    next_href = _monitor_url(admin_token, query, **{page_key: next_page})
    return (
        f'<div class="pager">'
        f'<a class="{prev_cls}" href="{prev_href}">上一页</a>'
        f'<span>第 {page} / {pages} 页</span>'
        f'<a class="{next_cls}" href="{next_href}">下一页</a>'
        f'</div>'
    )

def _status_badge(status: str):
    mapping = {
        "done": ("完成", "done"),
        "error": ("失败", "error"),
        "queued": ("排队中", "queued"),
        "processing": ("处理中", "processing"),
    }
    return mapping.get(status or "", (status or "-", "processing"))

def _monitor_html(stats: dict, admin_token: str = "") -> str:
    limit = _limit_settings()
    limit_checked = " checked" if limit["enabled"] else ""
    limit_state = "已开启" if limit["enabled"] else "已关闭"
    token_input = _admin_hidden_input(admin_token)
    query = stats.get("query", _normalize_monitor_query())
    recent_pager = _pager_html(stats, admin_token, "recent_page", "recent_pages")
    ip_pager = _pager_html(stats, admin_token, "ip_page", "ip_pages")
    rows = []
    for item in stats.get("recent", []):
        st = item.get("status", "")
        tag, cls = _status_badge(st)
        rows.append(
            f"<tr><td>{_html_escape(str(item.get('created_at','')))[:16]}</td>"
            f"<td class=fn>{_html_escape(str(item.get('filename','-')))[:40]}</td>"
            f"<td>{_html_escape(item.get('ip','-'))}</td>"
            f"<td>{(item.get('file_size',0)/1024):.0f}KB</td>"
            f"<td>{item.get('doc_type','-')}</td>"
            f"<td>{item.get('paragraphs',0)}</td>"
            f"<td>{((item.get('duration_ms',0) or 0)/1000):.1f}s</td>"
            f"<td><span class=\"tag {cls}\">{tag}</span></td>"
            f"<td><a href=\"{_admin_url('/log/' + _html_escape(item.get('id','')), admin_token)}\" target=\"_blank\">日志</a></td></tr>")
    ips = "".join(
        f"<tr><td class=mono>{_html_escape(r.get('ip','-'))}</td>"
            f"<td>{r.get('c',0)}</td><td class=ok>{r.get('done',0)}</td><td class=badtxt>{r.get('error',0)}</td>"
            f"<td class=mono>{_html_escape(str(r.get('last','')))[:16]}</td>"
            f"<td class=fn>{_html_escape(r.get('last_filename','-'))[:32]}</td>"
        f"<td><a href=\"{_admin_url('/ip?addr=' + quote(str(r.get('ip','')), safe=''), admin_token)}\" target=\"_blank\">明细</a>"
        f" · <a href=\"{_admin_url('/ban?ip=' + quote(str(r.get('ip','')), safe=''), admin_token)}\" onclick=\"return confirm('确认封禁该 IP？')\">封禁</a></td></tr>"
        for r in stats.get("top_ips", []))
    banned_rows = "".join(
        f"<tr><td class=mono>{_html_escape(r.get('ip','-'))}</td>"
        f"<td>{_html_escape(r.get('reason',''))}</td>"
        f"<td class=mono>{_html_escape(str(r.get('created_at','')))[:16]}</td>"
        f"<td><a href=\"{_admin_url('/unban?ip=' + quote(str(r.get('ip','')), safe=''), admin_token)}\">解封</a></td></tr>"
        for r in stats.get("banned_ips", []))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>监控面板 · 公文排版</title>
<style>
:root{{--red:#b71c1c;--bg:#f5f4f0;--paper:#fff;--border:#e0dcd5}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Microsoft YaHei","Noto Sans CJK SC","WenQuanYi Micro Hei","PingFang SC",Arial,sans-serif;background:var(--bg);color:#222;padding:20px 24px;max-width:1100px;margin:0 auto}}
.topbar{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}}
h1{{font-size:22px;color:var(--red)}}
.nav{{font-size:13px}}.nav a{{color:var(--red);text-decoration:none;margin-left:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:20px}}
.stat{{background:var(--paper);border:1px solid var(--border);padding:16px;text-align:center}}
.stat .n{{font-size:28px;font-weight:700;color:var(--red)}}
.stat .l{{font-size:12px;color:#888;margin-top:2px}}
.stat.good .n{{color:#2e7d32}}.stat.bad .n{{color:#c62828}}
.section{{margin-bottom:24px}}
.section h2{{font-size:16px;border-bottom:2px solid var(--border);padding-bottom:6px;margin-bottom:12px;display:flex;justify-content:space-between}}
.section h2 span{{font-size:12px;color:#999;font-weight:400}}
table{{width:100%;border-collapse:collapse;background:var(--paper);border:1px solid var(--border)}}
th{{background:#f8f6f2;font-size:12px;color:#666;text-align:left;padding:8px 10px;font-weight:500}}
td{{font-size:13px;padding:7px 10px;border-top:1px solid #f4f2ee}}
.fn{{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block}}
.mono{{font-family:Consolas,"Noto Sans Mono CJK SC","WenQuanYi Micro Hei",monospace;font-size:12px}}
.ok{{color:#2e7d32}}.badtxt{{color:#c62828}}
.tag{{display:inline-block;padding:2px 6px;border-radius:2px;font-size:11px;font-weight:600}}
.tag.done{{background:#e8f5e9;color:#2e7d32}}
.tag.error{{background:#ffebee;color:#c62828}}
.tag.queued{{background:#fff8e1;color:#8a5a00}}
.tag.processing{{background:#e3f2fd;color:#1565c0}}
.limit-box{{background:var(--paper);border:1px solid var(--border);padding:12px 14px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}}
.limit-box label{{font-size:13px;color:#444;display:flex;gap:6px;align-items:center}}
.limit-box input[type=number]{{width:90px;padding:5px 6px;border:1px solid var(--border);background:#fff}}
.limit-box button{{padding:6px 12px;border:0;background:var(--red);color:#fff;cursor:pointer}}
.limit-box a{{color:var(--red);text-decoration:none;font-size:13px}}
.pager{{display:flex;gap:12px;align-items:center;justify-content:flex-end;margin-top:8px;font-size:13px;color:#666}}
.pager a{{color:var(--red);text-decoration:none}}
.pager a.disabled{{pointer-events:none;color:#bbb}}
.hint{{font-size:12px;color:#777}}
</style></head>
<body>
<div class="topbar"><h1>公文排版 · 监控面板</h1>
<div class="nav"><a href="/">返回工具</a><a href="{_admin_url('/stats', admin_token)}" target="_blank">JSON API</a><a href="{_admin_url('/cleanup', admin_token)}">清理过期文件</a></div></div>
<div class="grid">
<div class="stat"><div class="n">{stats.get('total',0)}</div><div class="l">总任务</div></div>
<div class="stat good"><div class="n">{stats.get('done',0)}</div><div class="l">成功</div></div>
<div class="stat {"bad" if stats.get('error',0) else ""}"><div class="n">{stats.get('error',0)}</div><div class="l">失败</div></div>
<div class="stat good"><div class="n">{stats.get('rate',0)}%</div><div class="l">成功率</div></div>
<div class="stat"><div class="n">{stats.get('unique_ips',0)}</div><div class="l">独立 IP</div></div>
<div class="stat"><div class="n">{stats.get('total_mb',0)} MB</div><div class="l">总数据量</div></div>
<div class="stat"><div class="n">{stats.get('avg_s',0)}s</div><div class="l">平均耗时</div></div>
<div class="stat"><div class="n">{stats.get('avg_paragraphs',0)}</div><div class="l">平均段数</div></div>
</div>
<div class="section"><h2>显示设置 <span>控制每页显示数量</span></h2>
<form class="limit-box" method="get" action="/monitor">
{token_input}
<label>最近任务/页<input type="number" min="1" max="{MAX_MONITOR_PAGE_SIZE}" name="recent_size" value="{query['recent_size']}"></label>
<label>活跃 IP/页<input type="number" min="1" max="{MAX_MONITOR_PAGE_SIZE}" name="ip_size" value="{query['ip_size']}"></label>
<button type="submit">应用</button>
<a href="{_admin_url('/monitor', admin_token)}">恢复默认</a>
<span class="hint">默认每页 50 条，最多 {MAX_MONITOR_PAGE_SIZE} 条。</span>
</form></div>
<div class="section"><h2>上传限额 <span>{limit_state}</span></h2>
<form class="limit-box" method="get" action="/limit">
{token_input}
<label><input type="checkbox" name="enabled" value="1"{limit_checked}>启用限额</label>
<label>时间窗口（秒）<input type="number" min="1" name="window_seconds" value="{limit['window_seconds']}"></label>
<label>允许次数<input type="number" min="1" name="count" value="{limit['count']}"></label>
<button type="submit">保存</button>
<span class="hint">开启后，同一 IP 在 {limit['window_seconds']} 秒内最多排版 {limit['count']} 个文件。</span>
</form></div>
<div class="section"><h2>最近任务 <span>{len(stats.get('recent',[]))} / {stats.get('recent_total',0)} 条</span></h2>
<table><thead><tr><th>时间</th><th>文件名</th><th>IP</th><th>大小</th><th>类型</th><th>段数</th><th>耗时</th><th>状态</th><th>日志</th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="9">暂无数据</td></tr>'}</tbody></table>{recent_pager}</div>
<div class="section"><h2>活跃 IP <span>{len(stats.get('top_ips',[]))} / {stats.get('ip_total',0)} 个</span></h2>
<table><thead><tr><th>IP</th><th>上传</th><th>成功</th><th>失败</th><th>最近活跃</th><th>最近文件</th><th>操作</th></tr></thead>
<tbody>{ips or '<tr><td colspan="7">暂无数据</td></tr>'}</tbody></table>{ip_pager}</div>
<div class="section"><h2>封禁 IP <span>{len(stats.get('banned_ips',[]))} 个</span></h2>
<table><thead><tr><th>IP</th><th>原因</th><th>封禁时间</th><th>操作</th></tr></thead>
<tbody>{banned_rows or '<tr><td colspan="4">暂无封禁</td></tr>'}</tbody></table></div>
<script>
setInterval(() => {{
  if (document.hidden) return;
  const active = document.activeElement;
  if (active && ['INPUT', 'SELECT', 'TEXTAREA'].includes(active.tagName)) return;
  window.location.reload();
}}, 15000);
</script>
</body></html>"""


def _ip_detail_html(ip: str, admin_token: str = "") -> str:
    rows = []
    for item in _ip_activity(ip):
        st = item.get("status", "")
        tag = "完成" if st == "done" else "失败"
        cls = "done" if st == "done" else "error"
        rows.append(
            f"<tr><td class=mono>{_html_escape(str(item.get('created_at','')))[:19]}</td>"
            f"<td class=fn>{_html_escape(item.get('filename','-'))[:60]}</td>"
            f"<td>{(item.get('file_size',0)/1024):.0f}KB</td>"
            f"<td>{item.get('paragraphs',0)}</td>"
            f"<td>{((item.get('duration_ms',0) or 0)/1000):.1f}s</td>"
            f"<td><span class=\"tag {cls}\">{tag}</span></td>"
            f"<td><a href=\"{_admin_url('/log/' + _html_escape(item.get('id','')), admin_token)}\" target=\"_blank\">日志</a></td></tr>")
    total = _ip_upload_count(ip)
    last_hour = _ip_upload_count(ip, 3600)
    banned = _is_ip_banned(ip)
    action = (f"<a href=\"{_admin_url('/unban?ip=' + quote(ip, safe=''), admin_token)}\">解封 IP</a>"
              if banned else
              f"<a href=\"{_admin_url('/ban?ip=' + quote(ip, safe=''), admin_token)}\" onclick=\"return confirm('确认封禁该 IP？')\">封禁 IP</a>")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>IP 明细 · {html.escape(ip)}</title>
<style>
body{{font-family:"Microsoft YaHei","Noto Sans CJK SC","WenQuanYi Micro Hei","PingFang SC",Arial,sans-serif;background:#f5f4f0;color:#222;padding:20px 24px;max-width:1100px;margin:0 auto}}
h1{{font-size:22px;color:#b71c1c;margin-bottom:12px}}.nav{{font-size:13px;margin-bottom:18px}}.nav a{{color:#b71c1c;text-decoration:none;margin-right:16px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}}
.card{{background:#fff;border:1px solid #e0dcd5;padding:14px;text-align:center}}.n{{font-size:24px;font-weight:700;color:#b71c1c}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e0dcd5}}th{{background:#f8f6f2;text-align:left;padding:8px 10px;color:#666;font-size:12px}}td{{font-size:13px;padding:7px 10px;border-top:1px solid #f4f2ee}}
.mono{{font-family:Consolas,"Noto Sans Mono CJK SC","WenQuanYi Micro Hei",monospace;font-size:12px}}.fn{{max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block}}
.tag{{display:inline-block;padding:2px 6px;border-radius:2px;font-size:11px;font-weight:600}}.tag.done{{background:#e8f5e9;color:#2e7d32}}.tag.error{{background:#ffebee;color:#c62828}}
</style></head><body>
<div class="nav"><a href="{_admin_url('/monitor', admin_token)}">返回监控面板</a>{action}</div>
<h1>IP 上传明细：<span class="mono">{html.escape(ip)}</span></h1>
<div class="cards"><div class="card"><div class="n">{total}</div><div>总上传次数</div></div>
<div class="card"><div class="n">{last_hour}</div><div>最近 1 小时</div></div>
<div class="card"><div class="n">{"已封禁" if banned else "正常"}</div><div>当前状态</div></div></div>
<table><thead><tr><th>时间</th><th>文件名</th><th>大小</th><th>段数</th><th>耗时</th><th>状态</th><th>日志</th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="7">暂无上传记录</td></tr>'}</tbody></table>
</body></html>"""


# ── 安全工具 ──
import re as _re

def _is_safe_uuid(s: str) -> bool:
    return bool(_re.match(r'^[0-9a-fA-F-]{32,36}$', s or ""))

def _sanitize_filename(name: str) -> str:
    """移除路径分隔符和危险字符，防止目录穿越。"""
    return _re.sub(r'[/\\:*?"<>|]', '_', os.path.basename(name or "download.docx"))

def _html_escape(text: str) -> str:
    return html.escape(str(text or ""))

def _split_ip_header(value: str):
    return [p.strip() for p in str(value or "").split(",") if p.strip()]

def _is_ipv4(value: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(value.strip()), ipaddress.IPv4Address)
    except ValueError:
        return False

def _client_ip(headers, client_address) -> str:
    """Prefer an IPv4 client address from proxy headers, falling back to IPv6."""
    candidates = []
    for name in ("CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP"):
        candidates.extend(_split_ip_header(headers.get(name, "")))
    if client_address:
        candidates.append(client_address[0])
    for ip in candidates:
        if _is_ipv4(ip):
            return ip
    return candidates[0] if candidates else ""


class Handler(BaseHTTPRequestHandler):

    def _set_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")

    def _set_cors_headers(self):
        origin = self.headers.get("Origin", "")
        allow_origin = FRONTEND_ORIGIN or origin or "*"
        self.send_header("Access-Control-Allow-Origin", allow_origin)
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename, X-Admin-Token, X-Proxy-Secret, X-Docxtool-Proxy")
        self.send_header("Access-Control-Max-Age", "86400")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self._set_security_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/health":
            self._json(_health_payload())
        elif path == "/ready":
            ready = _ready_payload()
            self._json(ready, 200 if ready.get("ok") else 503)
        elif path == "/version":
            self._json(_version_payload())
        elif path == "/stats":
            if not self._require_admin(parsed): return
            self._json(get_sql_stats(_monitor_query_from(parsed)))
        elif path == "/monitor":
            if not self._require_admin(parsed): return
            query = _monitor_query_from(parsed)
            self._text(_monitor_html(get_sql_stats(query), _admin_token_from(parsed)), "text/html")
        elif path == "/ip":
            if not self._require_admin(parsed): return
            self._handle_ip_detail(parsed)
        elif path == "/ban":
            if not self._require_admin(parsed): return
            self._handle_ban(parsed)
        elif path == "/unban":
            if not self._require_admin(parsed): return
            self._handle_unban(parsed)
        elif path == "/limit":
            if not self._require_admin(parsed): return
            self._handle_limit(parsed)
        elif path == "/cleanup":
            if not self._require_admin(parsed): return
            self._handle_cleanup(parsed)
        elif path.startswith("/status/") or path.startswith("/api/status/"):
            if not self._require_file_api(): return
            self._handle_status(path.split("/")[-1])
        elif path.startswith("/download/") or path.startswith("/api/download/"):
            if not self._require_file_api(): return
            self._handle_download(path.split("/")[-1])
        elif path.startswith("/log/"):
            if not self._require_admin(parsed): return
            self._handle_log(path.split("/")[-1])
        else:
            self.send_error(404)

    def do_PUT(self):
        path = urlparse(self.path).path
        if path == "/upload" or path == "/api/upload":
            if not self._require_file_api(): return
            self._handle_upload_raw()
        else:
            self.send_error(404)

    def _serve_html(self):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        try:
            with open(p, "r", encoding="utf-8") as f:
                self._text(f.read(), "text/html")
        except FileNotFoundError:
            self.send_error(404)

    def _require_admin(self, parsed) -> bool:
        if _admin_authorized(parsed, self.headers, self.headers.get("Cookie", "")):
            return True
        self._json_error("UNAUTHORIZED", "需要管理员权限", 403)
        return False

    def _require_file_api(self) -> bool:
        if _file_api_authorized(self.headers):
            return True
        self._json_error("PROXY_REQUIRED", "请从前端页面访问", 403)
        return False

    def _handle_upload_raw(self):
        ip = _client_ip(self.headers, self.client_address)
        if _is_ip_banned(ip):
            logger.warning(f"[Security] banned ip blocked: {ip}")
            self._json_error("IP_BANNED", "该 IP 已被禁止访问", 403); return
        if _upload_limit_exceeded(ip):
            logger.warning(f"[Security] upload limit exceeded: {ip}")
            self._json_error("UPLOAD_LIMIT_EXCEEDED", "当前 IP 在该时间段内排版次数已达上限，请稍后再试", 429); return
        if not _allow(ip):
            self._json_error("RATE_LIMITED", "请求过于频繁，请稍后再试", 429); return
        if _task_load() >= MAX_QUEUE:
            self._json_error("QUEUE_FULL", "服务器繁忙，请稍后再试", 503); return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > MAX_SIZE:
                self._json_error("FILE_TOO_LARGE", "文件过大或无内容", 413); return
            try: file_data = _read_exact(self.rfile, length)
            except TimeoutError: self._json_error("UPLOAD_TIMEOUT", "文件上传超时", 408); return
            if len(file_data) != length:
                self._json_error("INCOMPLETE_UPLOAD", "读取不完整", 400); return
            if not file_data.startswith(b"PK"):
                self._json_error("INVALID_DOCX", "无效的文件格式，请上传 .docx", 400); return
            task_id = str(uuid.uuid4())
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
                f.write(file_data); input_path = f.name
            raw_name = unquote(self.headers.get("X-Filename", "upload.docx"))
            h = hashlib.md5(file_data).hexdigest()
            logger.info(f"[Upload] size={len(file_data)} expect={length} md5={h} task={task_id[:8]}")
            _ensure_workers_started()
            info = _enqueue_task(task_id, input_path, raw_name, ip, self.headers.get("User-Agent", ""))
            self._json({"task_id": task_id, "status": "queued", **info})
        except Exception as e:
            self._json_error("INTERNAL_ERROR", str(e)[:200], 500)

    def _handle_status(self, task_id: str):
        if not _is_safe_uuid(task_id):
            self._json_error("INVALID_TASK_ID", "无效的任务 ID", 400); return
        task = _public_task_state(task_id)
        if not task: self._json_error("TASK_NOT_FOUND", "任务不存在或已过期", 404)
        else: self._json(task)

    def _handle_download(self, task_id: str):
        if not _is_safe_uuid(task_id):
            self._json_error("INVALID_TASK_ID", "无效的任务 ID", 400); return
        with TASKS_LOCK: task = TASKS.get(task_id)
        if not task or task.get("status") != "done": self._json_error("FILE_NOT_READY", "文件未就绪", 400); return
        path = task.get("output", "")
        if not path or not os.path.exists(path): self._json_error("FILE_EXPIRED", "文件已过期", 410); return
        with open(path, "rb") as f: content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.send_header("Content-Disposition", "attachment; filename=formatted.docx")
        self.send_header("Content-Length", str(len(content)))
        self._set_cors_headers()
        self._set_security_headers()
        self.end_headers(); self.wfile.write(content)

    def _redirect(self, target: str):
        self.send_response(303)
        self.send_header("Location", target)
        self._set_security_headers()
        self.end_headers()

    def _query_ip(self, parsed):
        qs = parse_qs(parsed.query)
        return (qs.get("ip") or qs.get("addr") or [""])[0].strip()

    def _handle_ip_detail(self, parsed):
        ip = self._query_ip(parsed)
        if not _is_ip(ip):
            self._json_error("INVALID_IP", "无效的 IP", 400); return
        self._text(_ip_detail_html(ip, _admin_token_from(parsed)), "text/html")

    def _handle_ban(self, parsed):
        ip = self._query_ip(parsed)
        if not _is_ip(ip):
            self._json_error("INVALID_IP", "无效的 IP", 400); return
        reason = (parse_qs(parsed.query).get("reason") or ["monitor"])[0][:120]
        _ban_ip(ip, reason)
        logger.warning(f"[Security] ip banned: {ip} reason={reason}")
        self._redirect(_admin_url("/monitor", _admin_token_from(parsed)))

    def _handle_unban(self, parsed):
        ip = self._query_ip(parsed)
        if not _is_ip(ip):
            self._json_error("INVALID_IP", "无效的 IP", 400); return
        _unban_ip(ip)
        logger.warning(f"[Security] ip unbanned: {ip}")
        self._redirect(_admin_url("/monitor", _admin_token_from(parsed)))

    def _handle_limit(self, parsed):
        qs = parse_qs(parsed.query)
        enabled = (qs.get("enabled") or ["0"])[0] == "1"
        try:
            window_seconds = int((qs.get("window_seconds") or [str(DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS)])[0])
        except ValueError:
            window_seconds = DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS
        try:
            count = int((qs.get("count") or [str(DEFAULT_UPLOAD_LIMIT_COUNT)])[0])
        except ValueError:
            count = DEFAULT_UPLOAD_LIMIT_COUNT
        _save_limit_settings(enabled, window_seconds, count)
        logger.warning(
            f"[Security] upload limit settings updated: enabled={enabled} "
            f"window_seconds={max(1, window_seconds)} count={max(1, count)}"
        )
        self._redirect(_admin_url("/monitor", _admin_token_from(parsed)))

    def _handle_cleanup(self, parsed):
        result = _cleanup_expired_outputs()
        logger.warning(f"[Cleaner] manual cleanup removed={result['removed']} errors={result['errors']}")
        self._redirect(_admin_url("/monitor", _admin_token_from(parsed)))

    def _handle_log(self, task_id: str):
        if not _is_safe_uuid(task_id):
            self._json_error("INVALID_TASK_ID", "无效的任务 ID", 400); return
        path = ""
        with TASKS_LOCK:
            task = TASKS.get(task_id)
            if task:
                filename = task.get("log_filename", "")
                if filename:
                    path = os.path.join(LOG_DIR, filename)
        if not path:
            with _SQL_LOCK:
                conn = _sql()
                row = conn.execute("SELECT log_path FROM tasks WHERE id=?", (task_id,)).fetchone()
                conn.close()
            path = row["log_path"] if row else ""
        if not path:
            self._json_error("LOG_NOT_FOUND", "日志不存在", 404); return
        root = os.path.abspath(LOG_DIR)
        path = os.path.abspath(path)
        if not path.startswith(root + os.sep) or not os.path.exists(path):
            self._json_error("LOG_NOT_FOUND", "日志不存在或已过期", 404); return
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            self._text(f.read(), "text/plain")

    def _text(self, body: str, mime: str):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._set_cors_headers()
        self._set_security_headers()
        self.end_headers(); self.wfile.write(data)

    def _json(self, obj: dict, status: int = 200):
        data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._set_cors_headers()
        self._set_security_headers()
        self.end_headers(); self.wfile.write(data)

    def _json_error(self, code: str, message: str, status: int):
        self._json(_error_payload(code, message), status)

    def log_message(self, fmt, *args): pass


def main():
    _ensure_workers_started()
    server = ThreadingHTTPServer(_server_bind_address(), Handler)
    server.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    urls = _startup_urls()
    print(f"排版工具:   {urls['tool']}")
    print(f"监控面板:   {urls['monitor']}")
    print(f"隧道命令:   {urls['tunnel_command']}")
    print(f"后台密码:   {ADMIN_TOKEN}")
    print(f"线程池: {MAX_WORKERS} | 队列: {MAX_QUEUE} | 上限: {MAX_SIZE//1048576}MB")
    print(f"限流: {RATE_WINDOW}s/IP | 文件TTL: {FILE_TTL}s")
    for line in _startup_time_check_lines():
        print(line)
    print("外网访问:   Pages 前端填写 BACKEND_BASE_URL 后访问 docxtool.pages.dev")
    print("Ctrl+C 停止")
    try: server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止"); server.server_close()

if __name__ == "__main__":
    main()
