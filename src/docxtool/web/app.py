"""server — 公文排版 Web 服务。

功能：上传 .docx → 自动排版 → 下载
监控：/monitor（统计面板）/stats（JSON API）
安全：SQL 参数化查询 / UUID 校验 / XSS 转义 / 安全头 / 限流 / 文件大小限制
存储：SQLite（默认 var/data/stats.db）
启动：python server.py
访问：http://localhost:9527
"""

import os
import sys
import json
import base64
import binascii
import multiprocessing as mp
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
import shutil
import re as _re
from queue import Empty
from datetime import timezone, timedelta
from email.utils import parsedate_to_datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from collections import OrderedDict
from urllib.parse import unquote, urlparse, parse_qs, quote, urlencode
from urllib.request import Request, urlopen

from docxtool.document.importer import DocxImporter
from docxtool.document.engine import export_doc
from docxtool.security import DocxIntegrityError, validate_docx_integrity
from docxtool.security.docx_validator import DocxValidationError, detect_docx_complexity, validate_docx_upload
from docxtool.document.style_config import (
    StyleRule, PageSettings, load_rules_and_settings, configure_logging, get_logger,
    make_document_log_path, set_context_log_path, reset_context_log_path,
    ConfigValidationError, validate_format_config,
)
from docxtool.paths import project_path, resource_path, runtime_dir
from docxtool.storage.database import connect as _db_connect, default_database_path
from docxtool.auth import hash_password, verify_password, validate_password, validate_username

BASE_DIR = str(project_path())
_SQL_LOCK = threading.Lock()
_DB_PATH = default_database_path()
LOG_DIR = str(runtime_dir("logs", "LOG_DIR"))
RUNTIME_DIR = str(runtime_dir("runtime", "RUNTIME_DIR"))
RUNTIME_TMP_DIR = os.path.join(RUNTIME_DIR, "tmp")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(RUNTIME_TMP_DIR, exist_ok=True)
DEFAULT_ADMIN_TOKEN = "7654321xxx"
DEFAULT_PROXY_SECRET = "docxtool-proxy-20260601-9ec0d6e2443a4f5f9784f0f04bb62917"
ADMIN_SESSION_COOKIE = "docxtool_admin_session"
ANONYMOUS_USER_COOKIE = "docxtool_anon_user"
ANONYMOUS_USER_COOKIE_MAX_AGE = 2 * 365 * 24 * 60 * 60
USER_SESSION_COOKIE = "docxtool_user_session"
USER_SESSION_MAX_AGE = 30 * 24 * 60 * 60
USER_SESSION_DAYS = 30
USER_SESSION_REFRESH_SECONDS = 300
ADMIN_CSRF_HEADER = "X-CSRF-Token"
DEFAULT_ADMIN_SESSION_TTL_SECONDS = 12 * 60 * 60

_WEAK_SECRETS = {
    "",
    "123456",
    "admin",
    "change-me-admin-token",
    "change-me-proxy-secret",
    "change-me-in-production",
    DEFAULT_ADMIN_TOKEN,
    DEFAULT_PROXY_SECRET,
}

def _parse_bool(value: str, default: bool = True) -> bool:
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default

def _parse_int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default

def _is_local_origin_host(hostname: str) -> bool:
    return hostname in {"localhost", "127.0.0.1", "::1"}

def parse_frontend_origin(value: str, production_mode: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("FRONTEND_ORIGIN must use http or https")
    if not parsed.hostname:
        raise ValueError("FRONTEND_ORIGIN must include host")
    if parsed.username or parsed.password:
        raise ValueError("FRONTEND_ORIGIN must not include username or password")
    if parsed.query:
        raise ValueError("FRONTEND_ORIGIN must not include query")
    if parsed.fragment:
        raise ValueError("FRONTEND_ORIGIN must not include fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("FRONTEND_ORIGIN must not include path")
    if production_mode and parsed.scheme != "https" and not _is_local_origin_host(parsed.hostname):
        raise ValueError("FRONTEND_ORIGIN must use https in production")

    normalized = f"{parsed.scheme}://{parsed.netloc}"
    return normalized.rstrip("/")

def resolve_cookie_secure(origin: str, explicit_value: str = None, production_mode: bool = False) -> bool:
    if explicit_value is None or str(explicit_value).strip() == "":
        return str(origin or "").startswith("https://")

    secure = _parse_bool(explicit_value, False)
    if production_mode and str(origin or "").startswith("https://") and not secure:
        raise ValueError("COOKIE_SECURE=false is not allowed with HTTPS FRONTEND_ORIGIN in production")
    return secure

def cors_headers_for_request(origin_header: str, frontend_origin: str = None) -> dict:
    origin = str(origin_header or "").strip()
    configured_origin = FRONTEND_ORIGIN if frontend_origin is None else str(frontend_origin or "").strip()
    allow_origin = ""

    if configured_origin:
        if origin == configured_origin:
            allow_origin = configured_origin
    elif origin:
        parsed = urlparse(origin)
        if parsed.scheme in {"http", "https"} and _is_local_origin_host(parsed.hostname):
            allow_origin = origin.rstrip("/")

    if not allow_origin:
        return {}

    return {
        "Access-Control-Allow-Origin": allow_origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": (
            "Content-Type, X-Filename, X-Proxy-Secret, X-Docxtool-Proxy, "
            "X-Preset-Id, X-Preset-Name, X-Template-Type, X-Processing-Mode, "
            "X-Format-Config, X-Format-Config-Encoding, X-CSRF-Token"
        ),
        "Access-Control-Max-Age": "86400",
    }

def _sql():
    return _db_connect(_DB_PATH)

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
                output_dir TEXT DEFAULT '', output_filename TEXT DEFAULT '',
                output_path TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                started_at TEXT DEFAULT '',
                finished_at TEXT DEFAULT '',
                client_ip TEXT DEFAULT '',
                error_code TEXT DEFAULT '',
                error_message TEXT DEFAULT '',
                progress INTEGER DEFAULT 0,
                message TEXT DEFAULT '',
                processing_options TEXT DEFAULT '',
                preset_id TEXT DEFAULT '',
                original_filename TEXT DEFAULT '',
                safe_download_filename TEXT DEFAULT '',
                input_size INTEGER DEFAULT 0,
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
            CREATE TABLE IF NOT EXISTS presets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                config_json TEXT NOT NULL,
                is_system INTEGER DEFAULT 0,
                is_default INTEGER DEFAULT 0,
                owner_id TEXT DEFAULT '',
                visibility TEXT DEFAULT 'public',
                version INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS admin_sessions (
                session_id TEXT PRIMARY KEY,
                csrf_token TEXT NOT NULL,
                user_agent TEXT DEFAULT '',
                remote_ip TEXT DEFAULT '',
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL, username_norm TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, display_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active', created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL, last_login_at INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf_token TEXT NOT NULL,
                created_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL, user_agent TEXT NOT NULL DEFAULT '', remote_ip TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_ip ON tasks(ip);
            CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
            CREATE INDEX IF NOT EXISTS idx_tasks_ip_created ON tasks(ip, created_at);
            CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires ON admin_sessions(expires_at);
        """)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "log_filename" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN log_filename TEXT DEFAULT ''")
        if "log_path" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN log_path TEXT DEFAULT ''")
        if "output_dir" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN output_dir TEXT DEFAULT ''")
        if "output_filename" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN output_filename TEXT DEFAULT ''")
        if "output_path" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN output_path TEXT DEFAULT ''")
        if "started_at" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN started_at TEXT DEFAULT ''")
        if "finished_at" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN finished_at TEXT DEFAULT ''")
        if "client_ip" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN client_ip TEXT DEFAULT ''")
        if "error_code" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN error_code TEXT DEFAULT ''")
        if "error_message" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN error_message TEXT DEFAULT ''")
        if "progress" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN progress INTEGER DEFAULT 0")
        if "message" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN message TEXT DEFAULT ''")
        if "processing_options" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN processing_options TEXT DEFAULT ''")
        if "preset_id" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN preset_id TEXT DEFAULT ''")
        if "original_filename" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN original_filename TEXT DEFAULT ''")
        if "safe_download_filename" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN safe_download_filename TEXT DEFAULT ''")
        if "input_size" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN input_size INTEGER DEFAULT 0")
        if "owner_id" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN owner_id TEXT DEFAULT ''")
        preset_cols = {r["name"] for r in conn.execute("PRAGMA table_info(presets)").fetchall()}
        if "is_system" not in preset_cols:
            conn.execute("ALTER TABLE presets ADD COLUMN is_system INTEGER DEFAULT 0")
        if "is_default" not in preset_cols:
            conn.execute("ALTER TABLE presets ADD COLUMN is_default INTEGER DEFAULT 0")
        if "version" not in preset_cols:
            conn.execute("ALTER TABLE presets ADD COLUMN version INTEGER DEFAULT 1")
        if "created_at" not in preset_cols:
            conn.execute("ALTER TABLE presets ADD COLUMN created_at TEXT DEFAULT (datetime('now','localtime'))")
        if "updated_at" not in preset_cols:
            conn.execute("ALTER TABLE presets ADD COLUMN updated_at TEXT DEFAULT (datetime('now','localtime'))")
        if "owner_id" not in preset_cols:
            conn.execute("ALTER TABLE presets ADD COLUMN owner_id TEXT DEFAULT ''")
        if "visibility" not in preset_cols:
            conn.execute("ALTER TABLE presets ADD COLUMN visibility TEXT DEFAULT 'public'")
        conn.execute("UPDATE presets SET owner_id='' WHERE owner_id IS NULL")
        conn.execute("UPDATE presets SET visibility='public' WHERE visibility IS NULL OR visibility=''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_presets_owner_visibility ON presets(owner_id, visibility)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner_created ON tasks(owner_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at)")
        conn.commit()
        _seed_default_presets(conn)
        conn.close()

def _default_preset_config() -> dict:
    rules = StyleRule.from_config()
    styles = []
    for rule in rules:
        default_rule = StyleRule.default_for_row(rule.row_index)
        styles.append({
            "name": rule.level_name,
            "font": rule.font,
            "size": rule.font_size_label or default_rule.font_size_label,
            "bold": rule.bold,
            "pattern": rule.numbering_pattern,
            "lang": rule.language,
            "indent": rule.first_line_indent,
            "align": rule.alignment,
            "spacing_before": rule.spacing_before,
            "spacing_after": rule.spacing_after,
            "left_indent": rule.left_indent,
            "right_indent": rule.right_indent,
            "page_break_before": rule.page_break_before,
        })
    settings = PageSettings.from_config()
    config = {
        "schema_version": 1,
        "styles": styles,
        "page": {
            "width_cm": settings.page_width_cm,
            "height_cm": settings.page_height_cm,
            "margin_top_cm": settings.margin_top_cm,
            "margin_bottom_cm": settings.margin_bottom_cm,
            "margin_left_cm": settings.margin_left_cm,
            "margin_right_cm": settings.margin_right_cm,
            "lines_per_page": settings.lines_per_page,
            "chars_per_line": settings.chars_per_line,
            "line_spacing_pt": settings.line_spacing_value,
            "space_before_line": settings.space_before_line,
            "space_after_line": settings.space_after_line,
            "grid_alignment": settings.grid_alignment,
        },
        "features": {
            "numbered_bold_enabled": True,
            "punctuation_enabled": True,
        },
    }
    config.update(_core_feature_config_defaults())
    return config

def _core_feature_config_defaults() -> dict:
    return {
        "punctuation": {
            "enabled": False,
            "mode": "safe",
            "scope": {"body": True, "tables": False, "headers": False, "footers": False},
        },
        "classification": {
            "enabled": True,
            "minimum_auto_format_confidence": 0.85,
        },
        "numbering": {
            "enabled": False,
            "mode": "safe",
        },
        "page_number": {
            "enabled": True,
            "style": "dash",
            "position": "outside",
            "font_name": "宋体",
            "font_size_pt": 14,
            "bold": False,
            "first_page": True,
            "section_numbering": "continue",
            "offset_from_text_mm": 7,
        },
        "signature_block": {
            "mode": "without_seal",
        },
        "table_format": {
            "enabled": False,
            "smart_alignment": False,
        },
        "cleanup": {
            "enabled": False,
            "mode": "safe",
        },
    }

def _seed_default_presets(conn):
    try:
        row = conn.execute("SELECT 1 FROM presets WHERE id=?", ("official_document",)).fetchone()
        if row:
            return
        config_json = json.dumps(_default_preset_config(), ensure_ascii=False)
        now = _now_local()
        conn.execute(
            """INSERT INTO presets
               (id, name, description, config_json, is_system, is_default, version, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                "official_document",
                "党政机关公文格式",
                "默认公文格式，适合通知、报告、请示、汇报等正式材料。",
                config_json,
                1,
                1,
                1,
                now,
                now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()

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
            log_filename="", log_path="", output_dir="", output_filename="", output_path="",
            processing_options="", preset_id="", error_code="", error_message=""):
    now = _now_local()
    today = now[:10]
    with _SQL_LOCK:
        conn = _sql()
        conn.execute("""INSERT INTO tasks (id,ip,ua,filename,file_size,doc_type,
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
                      (task_id, ip, ua, filename, file_size, doc_type,
                       paragraphs, headings, body, duration_ms, status, error,
                       log_filename, log_path, output_dir, output_filename, output_path,
                       ip, filename, output_filename, file_size, processing_options, preset_id,
                       error_code, error_message, now, now))
        conn.execute("""INSERT INTO daily_stats (date,total,done,error,total_bytes,total_ms)
                       VALUES (?,1,?,?,?,?)
                       ON CONFLICT(date) DO UPDATE SET total=total+1,
                       done=done+?, error=error+?, total_bytes=total_bytes+?,
                       total_ms=total_ms+?""",
                     (today, 1 if status == "done" else 0,
                      1 if status in ("error", "timeout", "failed") else 0, file_size, duration_ms,
                      1 if status == "done" else 0, 1 if status in ("error", "timeout", "failed") else 0,
                      file_size, duration_ms))
        conn.execute("""UPDATE daily_stats SET unique_ips=(
                       SELECT COUNT(DISTINCT ip) FROM tasks WHERE date(created_at)=?)
                       WHERE date=?""", (today, today))
        conn.commit()
        conn.close()

def record_task_queued(task_id: str, ip: str, ua: str, filename: str, file_size: int = 0,
                       processing_options: str = "", preset_id: str = "", owner_id: str = ""):
    now = _now_local()
    with _SQL_LOCK:
        conn = _sql()
        conn.execute("""INSERT INTO tasks (id,ip,ua,filename,file_size,doc_type,
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
                     (task_id, ip, ua, filename, file_size, "", 0, 0, 0, 0, "queued", "",
                      "", "", "", "", "", ip, filename, _safe_download_filename(filename), file_size,
                      processing_options, preset_id, owner_id, now, ""))
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
        err = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status IN ('error','timeout','failed','interrupted','expired')").fetchone()["c"]
        ips = conn.execute("SELECT COUNT(DISTINCT ip) as c FROM tasks").fetchone()["c"]
        tbytes = conn.execute("SELECT COALESCE(SUM(file_size),0) as c FROM tasks").fetchone()["c"]
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
        days = conn.execute("""
            SELECT date(created_at) as date,
                   COUNT(*) as total,
                   SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
                   SUM(CASE WHEN status IN ('error','timeout','failed','interrupted','expired') THEN 1 ELSE 0 END) as error
            FROM tasks
            GROUP BY date(created_at)
            ORDER BY date(created_at)
        """).fetchall()
        top_rows = conn.execute("""
            SELECT t.ip, COUNT(*) as c,
                   SUM(CASE WHEN t.status='done' THEN 1 ELSE 0 END) as done,
                   SUM(CASE WHEN t.status IN ('error','timeout','failed','interrupted','expired') THEN 1 ELSE 0 END) as error,
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

def _load_secret(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip()
    return value or default

ADMIN_TOKEN = _load_secret("ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN)
PROXY_SECRET = _load_secret("PROXY_SECRET", DEFAULT_PROXY_SECRET)
PRODUCTION_MODE = _parse_bool(os.environ.get("PRODUCTION_MODE", "false"), False)
try:
    FRONTEND_ORIGIN = parse_frontend_origin(os.environ.get("FRONTEND_ORIGIN", ""), PRODUCTION_MODE)
    COOKIE_SECURE = resolve_cookie_secure(FRONTEND_ORIGIN, os.environ.get("COOKIE_SECURE"), PRODUCTION_MODE)
except ValueError as exc:
    raise SystemExit(f"[配置错误] {exc}") from exc
USER_SESSION_DAYS = max(1, min(365, _parse_int_env("DOCXTOOL_USER_SESSION_DAYS", 30)))
USER_SESSION_MAX_AGE = USER_SESSION_DAYS * 24 * 60 * 60
MAX_SIZE = _parse_int_env("MAX_UPLOAD_SIZE_MB", 10) * 1024 * 1024
UPLOAD_READ_TIMEOUT_SECONDS = _parse_int_env("UPLOAD_READ_TIMEOUT_SECONDS", 15)
UPLOAD_READ_CHUNK_SIZE = 64 * 1024
MAX_WORKERS = 4
MAX_QUEUE = MAX_WORKERS * 2
PROCESS_TIMEOUT = _parse_int_env("PROCESS_TIMEOUT_SECONDS", 60)
RATE_WINDOW = 2
FILE_RETENTION_DAYS = max(1, _parse_int_env("FILE_RETENTION_DAYS", 7))
FILE_TTL = FILE_RETENTION_DAYS * 24 * 60 * 60
MAX_TASKS = _parse_int_env("MAX_TASKS", 200)
TASK_RETENTION_HOURS = max(
    FILE_RETENTION_DAYS * 24,
    _parse_int_env("TASK_RETENTION_HOURS", FILE_RETENTION_DAYS * 24),
)
MAX_CACHED_TASKS = _parse_int_env("MAX_CACHED_TASKS", 500)
CLEANUP_INTERVAL_MINUTES = _parse_int_env("CLEANUP_INTERVAL_MINUTES", 30)
DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS = 3600
DEFAULT_UPLOAD_LIMIT_COUNT = 10
MAX_FORMAT_CONFIG_HEADER_BYTES = 96 * 1024
MAX_FORMAT_CONFIG_JSON_BYTES = 64 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = _parse_int_env("MAX_DOCX_UNCOMPRESSED_MB", 100) * 1024 * 1024
MAX_DOCX_FILE_COUNT = _parse_int_env("MAX_DOCX_FILE_COUNT", 1000)
MAX_DOCX_XML_BYTES = _parse_int_env("MAX_DOCX_XML_SIZE_MB", 20) * 1024 * 1024
MAX_DOCX_MEDIA_BYTES = _parse_int_env("MAX_DOCX_MEDIA_SIZE_MB", 30) * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = _parse_int_env("MAX_DOCX_COMPRESSION_RATIO", 100)
TRUST_PROXY_HEADERS = _parse_bool(os.environ.get("TRUST_PROXY_HEADERS", "true"), True)
TRUSTED_PROXY_IPS = {
    ip.strip()
    for ip in os.environ.get("TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
    if ip.strip()
}

def _validate_secrets_or_exit() -> None:
    admin = ADMIN_TOKEN.strip()
    proxy = PROXY_SECRET.strip()
    if not admin or not proxy:
        raise SystemExit("[配置错误] ADMIN_TOKEN 和 PROXY_SECRET 不能为空。")
    if len(admin) < 16 or admin in _WEAK_SECRETS:
        raise SystemExit("[配置错误] ADMIN_TOKEN 使用了示例/弱密钥，请替换为随机长密钥后再启动。")
    if len(proxy) < 16 or proxy in _WEAK_SECRETS:
        raise SystemExit("[配置错误] PROXY_SECRET 使用了示例/弱密钥，请替换为随机长密钥后再启动。")
    if admin == proxy:
        raise SystemExit("[配置错误] ADMIN_TOKEN 和 PROXY_SECRET 不能相同。")

RATE_LIMIT = {}
RATE_LOCK = threading.Lock()
AUTH_RATE_LIMIT = OrderedDict()
TASKS = OrderedDict()
TASKS_LOCK = threading.Lock()
TASK_QUEUE = OrderedDict()
QUEUE_COND = threading.Condition()
WORKERS_STARTED = False
WORKERS_LOCK = threading.Lock()
WORKER_THREADS = []

OUTPUT_DIR = str(runtime_dir("outputs", "OUTPUT_DIR"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

def _startup_cleanup():
    result = _cleanup_expired_tmp()
    if result["removed"]:
        logger.info(f"[Startup] cleaned {result['removed']} expired project input files")

def _task_tmp_dir(task_id: str) -> str:
    return os.path.join(RUNTIME_TMP_DIR, task_id)

def _task_tmp_input_path(task_id: str, orig_name: str = "") -> str:
    safe = _sanitize_filename(orig_name) or "upload.docx"
    stem, ext = os.path.splitext(safe)
    if not ext:
        ext = ".docx"
    return os.path.join(_task_tmp_dir(task_id), f"input{ext}")

def _cleanup_task_tmp(task_id: str, extra_path: str = "") -> None:
    paths = []
    if extra_path:
        paths.append(extra_path)
    task_dir = _task_tmp_dir(task_id)
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

def _cleanup_expired_tmp(now: float = None) -> dict:
    now = now or time.time()
    removed = 0
    errors = 0
    if not os.path.isdir(RUNTIME_TMP_DIR):
        return {"removed": 0, "errors": 0}
    for root, dirs, files in os.walk(RUNTIME_TMP_DIR, topdown=False):
        for name in files:
            path = os.path.join(root, name)
            try:
                if now - os.path.getmtime(path) > FILE_TTL:
                    os.unlink(path)
                    removed += 1
            except Exception:
                errors += 1
        for name in dirs:
            path = os.path.join(root, name)
            try:
                if os.path.isdir(path) and not os.listdir(path):
                    os.rmdir(path)
            except Exception:
                errors += 1
    return {"removed": removed, "errors": errors}

def _prune_task_cache() -> None:
    with TASKS_LOCK:
        cache_limit = max(1, min(MAX_TASKS, MAX_CACHED_TASKS))
        if len(TASKS) <= cache_limit:
            return
        keep = OrderedDict()
        recent = list(TASKS.items())
        active = [(k, v) for k, v in recent if v.get("status") in {"queued", "processing"}]
        done = [(k, v) for k, v in recent if v.get("status") not in {"queued", "processing"}]
        ordered = active + done
        for key, value in ordered[-cache_limit:]:
            keep[key] = value
        TASKS.clear()
        TASKS.update(keep)

def _recover_inflight_tasks_on_startup() -> int:
    now = _now_local()
    with _SQL_LOCK:
        conn = _sql()
        rows = conn.execute(
            "SELECT id, status FROM tasks WHERE status IN ('queued', 'processing')"
        ).fetchall()
        if rows:
            conn.execute(
                "UPDATE tasks SET status='interrupted', error='服务重启后任务中断', done_at=? WHERE status IN ('queued', 'processing')",
                (now,),
            )
            conn.commit()
        conn.close()
    return len(rows)

configure_logging(LOG_DIR, to_file=True)
logger = get_logger()
logging.getLogger("docx_tool").setLevel(logging.DEBUG)
for h in logging.getLogger("docx_tool").handlers:
    if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
        h.setLevel(logging.WARNING)

def _read_exact(rfile, length: int, timeout: int = 10) -> bytes:
    data = b""
    remaining = length
    t0 = time.time()
    while remaining > 0:
        if time.time() - t0 > timeout:
            raise TimeoutError("read timeout")
        chunk = rfile.read(remaining)
        if not chunk:
            time.sleep(0.01)
            continue
        data += chunk
        remaining -= len(chunk)
    return data

def _read_exact_to_file(rfile, path: str, length: int, timeout: int = 10, chunk_size: int = UPLOAD_READ_CHUNK_SIZE) -> int:
    if length <= 0:
        raise TimeoutError("invalid length")
    total = 0
    remaining = length
    started = time.time()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        while remaining > 0:
            if time.time() - started > timeout:
                raise TimeoutError("read timeout")
            chunk = rfile.read(min(chunk_size, remaining))
            if not chunk:
                time.sleep(0.01)
                continue
            f.write(chunk)
            total += len(chunk)
            remaining -= len(chunk)
    return total

def _stream_file(path: str, writer, chunk_size: int = 1024 * 1024) -> None:
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            writer.write(chunk)

def _allow(ip: str) -> bool:
    now = time.time()
    with RATE_LOCK:
        last = RATE_LIMIT.get(ip, 0)
        if now - last < RATE_WINDOW:
            return False
        RATE_LIMIT[ip] = now
        return True


def _auth_rate_allow(scope: str, key: str, window: int, limit: int) -> tuple[bool, int]:
    now = time.time()
    bucket_key = f"{scope}:{key}"
    with RATE_LOCK:
        values = [stamp for stamp in AUTH_RATE_LIMIT.get(bucket_key, []) if now - stamp < window]
        if len(values) >= limit:
            return False, max(1, int(window - (now - values[0])))
        values.append(now)
        AUTH_RATE_LIMIT[bucket_key] = values
        AUTH_RATE_LIMIT.move_to_end(bucket_key)
        while len(AUTH_RATE_LIMIT) > 4096:
            AUTH_RATE_LIMIT.popitem(last=False)
    return True, 0

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

def _public_task_state(task_id: str, owner_id: str = "") -> dict:
    with TASKS_LOCK:
        task = dict(TASKS.get(task_id, {}))
    if task and owner_id and task.get("owner_id", "") != owner_id:
        task = {}
    if not task:
        with _SQL_LOCK:
            conn = _sql()
            row = conn.execute("SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner_id)).fetchone()
            conn.close()
        if not row:
            return {}
        task = dict(row)
    for key in ("output", "output_path", "output_dir", "download_name", "error_message"):
        task.pop(key, None)
    status = task.get("status", "")
    if status == "queued":
        task.update(_task_queue_info(task_id))
    elif status == "processing":
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "正在排版"})
    elif status == "done":
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "排版完成"})
    elif status in ("error", "timeout", "failed"):
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "排版失败"})
    elif status == "interrupted":
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "任务已中断"})
    elif status == "expired":
        task.update({"queue_position": 0, "queue_ahead": 0, "message": "任务已过期"})
    return task

def _task_output_dir(task_id: str) -> str:
    return os.path.join(OUTPUT_DIR, task_id)

def _task_output_path(task_id: str) -> str:
    return os.path.join(_task_output_dir(task_id), "result.docx")

def _ensure_path_within(base_dir: str, path: str) -> str:
    base = os.path.abspath(base_dir)
    candidate = os.path.abspath(path)
    if os.path.commonpath([base, candidate]) != base:
        raise ValueError(f"path escapes output directory: {candidate}")
    return candidate

def _cleanup_output_path(path: str) -> None:
    if not path:
        return
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass

def _task_processing_options(format_config: dict = None, request_meta: dict = None) -> str:
    payload = {
        "request_meta": request_meta or {},
        "features": {},
    }
    if isinstance(format_config, dict):
        payload["features"] = {
            "format_config_present": True,
            "style_count": len(format_config.get("styles", []) or []),
        }
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return ""

def _mark_task_processing(task_id: str) -> None:
    now = _now_local()
    with _SQL_LOCK:
        conn = _sql()
        conn.execute(
            "UPDATE tasks SET status='processing', started_at=?, error='', done_at='' WHERE id=?",
            (now, task_id),
        )
        conn.commit()
        conn.close()

def _mark_task_terminal(task_id: str, status: str, error: str = "", output_path: str = "", output_filename: str = "", log_path: str = "", log_filename: str = "") -> None:
    now = _now_local()
    with _SQL_LOCK:
        conn = _sql()
        conn.execute(
            "UPDATE tasks SET status=?, error=?, output_path=?, output_filename=?, log_path=?, log_filename=?, done_at=? WHERE id=?",
            (status, error, output_path, output_filename, log_path, log_filename, now, task_id),
        )
        conn.commit()
        conn.close()

def _enqueue_task(task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                  format_config: dict = None, request_meta: dict = None,
                  compatibility_warnings: list[str] = None, owner_id: str = "") -> dict:
    now = time.time()
    try:
        file_size = os.path.getsize(input_path) if input_path and os.path.exists(input_path) else 0
    except OSError:
        file_size = 0
    request_meta = request_meta or {}
    processing_options = _task_processing_options(format_config, request_meta)
    preset_id = str(request_meta.get("preset_id", "") or "")
    with QUEUE_COND:
        active = _active_count()
        queued = len(TASK_QUEUE)
        if active + queued >= MAX_QUEUE:
            raise OverflowError("QUEUE_FULL: 服务器繁忙，请稍后再试")
        record_task_queued(task_id, ip, ua, orig_name, file_size, processing_options=processing_options, preset_id=preset_id, owner_id=owner_id)
        TASK_QUEUE[task_id] = (input_path, orig_name, ip, ua, format_config, request_meta or {})
        info = _task_queue_info(task_id)
        QUEUE_COND.notify()
    with TASKS_LOCK:
        TASKS[task_id] = {
            "status": "queued",
            "time": now,
            "queued_at": now,
            "uses_format_config": bool(format_config),
            "preset_name": request_meta.get("preset_name", ""),
            "preset_id": preset_id,
            "processing_mode": request_meta.get("processing_mode", ""),
            "filename": orig_name,
            "ip": ip,
            "processing_options": processing_options,
            "compatibility_warnings": list(compatibility_warnings or []),
            "owner_id": owner_id,
        }
    _prune_task_cache()
    return info

def _task_process_body(task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                       format_config: dict = None, request_meta: dict = None) -> dict:
    """Run the actual DOCX pipeline and return a structured result."""
    t0 = time.time()
    request_meta = request_meta or {}
    log_path = make_document_log_path(orig_name, log_dir=LOG_DIR, suffix=task_id[:8])
    log_filename = os.path.basename(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [INFO ] docx_tool | [Task] {task_id[:8]} log created file={orig_name}\n")
    token = set_context_log_path(log_path)
    try:
        rules, settings, features = load_rules_and_settings(format_config)
        rules = rules or [StyleRule.default_for_row(i) for i in range(10)]
        settings = settings or PageSettings()
        features = features or {}
        features.setdefault("numbered_bold_enabled", True)
        features.setdefault("punctuation_enabled", True)
        features.setdefault("page_number_enabled", True)
        for key, value in _core_feature_config_defaults().items():
            features.setdefault(key, value)
        body_rule = rules[5] if len(rules) > 5 else StyleRule.default_for_row(5)
        letterhead_summary = features.get("letterhead", {})
        letterhead_agencies = letterhead_summary.get("agencies", [])
        logger.info(
            f"[Task] {task_id[:8]} start file={orig_name} ip={ip} log={log_filename} "
            f"preset={request_meta.get('preset_name','')} mode={request_meta.get('processing_mode','smart')} "
            f"frontend_config={bool(format_config)} body={body_rule.font}/{body_rule.font_size_label} "
            f"margins=top{settings.margin_top_cm} bottom{settings.margin_bottom_cm} "
            f"left{settings.margin_left_cm} right{settings.margin_right_cm} "
            f"line_spacing={settings.line_spacing_value} numbered_bold_enabled={features['numbered_bold_enabled']} "
            f"letterhead_enabled={bool(letterhead_summary.get('enabled', False))} "
            f"letterhead_mode={letterhead_summary.get('issuance_mode', 'single')} "
            f"letterhead_agencies={len(letterhead_agencies) if isinstance(letterhead_agencies, list) else 0} "
            f"letterhead_scope={letterhead_summary.get('joint_mark_scope', 'all_agencies')}"
        )
        importer = DocxImporter()
        try:
            doc_data = importer.load(input_path, rules, features=features)
        except TypeError:
            doc_data = importer.load(input_path, rules)
        output_dir = _ensure_path_within(OUTPUT_DIR, _task_output_dir(task_id))
        os.makedirs(output_dir, exist_ok=True)
        output_path = _ensure_path_within(output_dir, _task_output_path(task_id))
        download_name = _safe_download_filename(orig_name)
        try:
            export_stats = export_doc(
                doc_data,
                rules,
                settings,
                output_path,
                numbered_bold_enabled=features["numbered_bold_enabled"],
                page_number_enabled=features["page_number_enabled"],
                numbering_options=features.get("numbering"),
                page_number_options=features.get("page_number"),
                signature_block_options=features.get("signature_block"),
                table_format_options=features.get("table_format"),
                cleanup_options=features.get("cleanup"),
                letterhead_options=features.get("letterhead"),
            )
        except TypeError:
            export_stats = export_doc(
                doc_data,
                rules,
                settings,
                output_path,
                numbered_bold_enabled=features["numbered_bold_enabled"],
            )
        export_stats = export_stats or {}
        try:
            validate_docx_integrity(output_path)
        except DocxIntegrityError as exc:
            logger.error(
                f"[Task] {task_id[:8]} generated DOCX integrity check failed "
                f"code={exc.code} detail={exc.message}"
            )
            duration = round(time.time() - t0, 2)
            return {
                "status": "error",
                "log_filename": log_filename,
                "log_path": log_path,
                "output_dir": output_dir,
                "output_filename": "",
                "output_path": "",
                "duration_s": duration,
                "duration_ms": int(duration * 1000),
                "doc_mode": doc_data.doc_mode or "UNKNOWN",
                "paragraphs": len(doc_data.paragraphs),
                "headings": sum(1 for pd in doc_data.paragraphs if pd.type_id.startswith("heading")),
                "body": sum(1 for pd in doc_data.paragraphs if pd.type_id == "body"),
                "error": "生成的 DOCX 未通过完整性检查",
                "error_code": "OUTPUT_DOCX_INVALID",
                "error_message": f"{exc.code}: {exc.message}"[:500],
            }
        duration = round(time.time() - t0, 2)
        hc = sum(1 for pd in doc_data.paragraphs if pd.type_id.startswith("heading"))
        bc = sum(1 for pd in doc_data.paragraphs if pd.type_id == "body")
        return {
            "status": "done",
            "log_filename": log_filename,
            "log_path": log_path,
            "output_dir": output_dir,
            "output_filename": download_name,
            "output_path": output_path,
            "duration_s": duration,
            "duration_ms": int(duration * 1000),
            "doc_mode": doc_data.doc_mode or "UNKNOWN",
            "paragraphs": len(doc_data.paragraphs),
            "headings": hc,
            "body": bc,
            "error": "",
            "error_code": "",
            "error_message": "",
            "compatibility_warnings": list(export_stats.get("compatibility_warnings", []) or []),
        }
    except Exception as exc:
        logger.exception(f"[Task] {task_id[:8]} error: {exc}")
        return {
            "status": "error",
            "log_filename": log_filename,
            "log_path": log_path,
            "output_dir": "",
            "output_filename": "",
            "output_path": "",
            "duration_s": round(time.time() - t0, 2),
            "duration_ms": 0,
            "doc_mode": "",
            "paragraphs": 0,
            "headings": 0,
            "body": 0,
            "error": str(exc)[:200],
            "error_code": "TASK_PROCESSING_ERROR",
            "error_message": str(exc)[:500],
        }
    finally:
        reset_context_log_path(token)

def _task_process_entry(result_queue, task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                        format_config: dict = None, request_meta: dict = None) -> None:
    try:
        result = _task_process_body(task_id, input_path, orig_name, ip, ua, format_config, request_meta)
    except Exception as exc:
        result = {
            "status": "error",
            "log_filename": "",
            "log_path": "",
            "output_dir": "",
            "output_filename": "",
            "output_path": "",
            "duration_s": 0,
            "duration_ms": 0,
            "doc_mode": "",
            "paragraphs": 0,
            "headings": 0,
            "body": 0,
            "error": f"{type(exc).__name__}: {exc}"[:200],
            "error_code": "TASK_PROCESSING_ERROR",
            "error_message": f"{type(exc).__name__}: {exc}"[:500],
        }
    try:
        result_queue.put(result)
    except Exception:
        pass

def _task_process_direct(task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                         format_config: dict = None, request_meta: dict = None) -> dict:
    return _task_process_body(task_id, input_path, orig_name, ip, ua, format_config, request_meta)

def _task_process_subprocess(task_id: str, input_path: str, orig_name: str, ip: str, ua: str,
                             format_config: dict = None, request_meta: dict = None) -> dict:
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    process = ctx.Process(
        target=_task_process_entry,
        args=(result_queue, task_id, input_path, orig_name, ip, ua, format_config, request_meta),
        daemon=True,
    )
    process.start()
    process.join(PROCESS_TIMEOUT)
    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            try:
                process.kill()
            except Exception:
                pass
            process.join(5)
        _cleanup_output_path(_task_output_dir(task_id))
        return {
            "status": "timeout",
            "log_filename": "",
            "log_path": "",
            "output_dir": "",
            "output_filename": "",
            "output_path": "",
            "duration_s": PROCESS_TIMEOUT,
            "duration_ms": PROCESS_TIMEOUT * 1000,
            "doc_mode": "",
            "paragraphs": 0,
            "headings": 0,
            "body": 0,
            "error": f"排版超时：超过 {PROCESS_TIMEOUT} 秒",
            "error_code": "TASK_TIMEOUT",
            "error_message": f"排版超时：超过 {PROCESS_TIMEOUT} 秒",
        }
    try:
        result = result_queue.get(timeout=2)
    except Empty:
        result = {
            "status": "error",
            "log_filename": "",
            "log_path": "",
            "output_dir": "",
            "output_filename": "",
            "output_path": "",
            "duration_s": 0,
            "duration_ms": 0,
            "doc_mode": "",
            "paragraphs": 0,
            "headings": 0,
            "body": 0,
            "error": f"子进程未返回结果，退出码={process.exitcode}",
            "error_code": "TASK_PROCESSING_ERROR",
            "error_message": f"子进程未返回结果，退出码={process.exitcode}",
        }
    if result.get("status") != "done":
        _cleanup_output_path(_task_output_dir(task_id))
    return result

def _record_task_result(task_id: str, input_path: str, orig_name: str, ip: str, ua: str, result: dict) -> None:
    status = result.get("status", "error")
    log_filename = result.get("log_filename", "")
    log_path = result.get("log_path", "")
    output_dir = result.get("output_dir", "")
    output_filename = result.get("output_filename", "")
    output_path = result.get("output_path", "")
    file_size = os.path.getsize(input_path) if input_path and os.path.exists(input_path) else 0
    duration_ms = int(result.get("duration_ms", 0) or 0)
    error = result.get("error", "") if status != "done" else ""
    error_code = result.get("error_code", "") if status != "done" else ""
    error_message = result.get("error_message", error) if status != "done" else ""
    sql_status = "done" if status == "done" else ("timeout" if status == "timeout" else "error")
    task_payload = {}
    with TASKS_LOCK:
        task_payload = dict(TASKS.get(task_id, {}))
    processing_options = task_payload.get("processing_options", "")
    preset_id = task_payload.get("preset_id", "")

    try:
        log_sql(
            task_id, ip, ua, orig_name, file_size,
            result.get("doc_mode", "") if status == "done" else "",
            int(result.get("paragraphs", 0) or 0),
            int(result.get("headings", 0) or 0),
            int(result.get("body", 0) or 0),
            duration_ms,
            sql_status,
            error,
            log_filename=log_filename,
            log_path=log_path,
            output_dir=output_dir,
            output_filename=output_filename,
            output_path=output_path,
            processing_options=processing_options,
            preset_id=preset_id,
            error_code=error_code,
            error_message=error_message,
        )
    except Exception:
        logger.exception(f"[Stats] failed to record task={task_id[:8]} ip={ip} file={orig_name}")

    if status != "done":
        _cleanup_output_path(_task_output_dir(task_id))

    with TASKS_LOCK:
        task = TASKS.get(task_id, {})
        existing_warnings = list(task.get("compatibility_warnings", []) or [])
        result_warnings = list(result.get("compatibility_warnings", []) or [])
        task["compatibility_warnings"] = list(dict.fromkeys(existing_warnings + result_warnings))
        task["status"] = status
        task["finished_at"] = time.time()
        task["duration"] = round((duration_ms or 0) / 1000, 2)
        task["paragraphs"] = int(result.get("paragraphs", 0) or 0)
        task["log_filename"] = log_filename
        task["log_url"] = f"/log/{task_id}"
        task["output_dir"] = output_dir
        task["output_filename"] = output_filename
        task["output_path"] = output_path
        task["download_name"] = output_filename
        task["safe_download_filename"] = output_filename
        task["original_filename"] = orig_name
        task["client_ip"] = ip
        if status == "done":
            task["output"] = output_path
            task["error"] = ""
            task["error_code"] = ""
            task["error_message"] = ""
        else:
            task["error"] = error
            task["error_code"] = error_code
            task["error_message"] = error_message
        task["time"] = time.time()
        TASKS[task_id] = task
    _prune_task_cache()

    if status == "done":
        logger.info(f"[Stats] recorded task={task_id[:8]} status=done ip={ip} file={orig_name}")
        logger.info(f"[Task] {task_id[:8]} done {result.get('duration_s', 0)}s")
    elif status == "timeout":
        logger.warning(f"[Task] {task_id[:8]} timeout after {PROCESS_TIMEOUT}s file={orig_name}")
    else:
        logger.warning(f"[Task] {task_id[:8]} failed file={orig_name} err={error}")

def _worker_loop():
    while True:
        with QUEUE_COND:
            while not TASK_QUEUE:
                QUEUE_COND.wait()
            task_id, payload = TASK_QUEUE.popitem(last=False)
        input_path, orig_name, ip, ua, format_config, request_meta = payload
        _mark_task_processing(task_id)
        with TASKS_LOCK:
            task = TASKS.get(task_id, {})
            task["status"] = "processing"
            task["started_at"] = time.time()
            task["queue_ahead"] = 0
            task["queue_position"] = 0
            TASKS[task_id] = task
        _process_task(task_id, input_path, orig_name, ip, ua, format_config, request_meta)

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

def _process_task(task_id: str, input_path: str, orig_name: str = "upload.docx", ip: str = "", ua: str = "",
                  format_config: dict = None, request_meta: dict = None):
    if threading.current_thread() is threading.main_thread():
        result = _task_process_direct(task_id, input_path, orig_name, ip, ua, format_config, request_meta)
    else:
        result = _task_process_subprocess(task_id, input_path, orig_name, ip, ua, format_config, request_meta)
    _record_task_result(task_id, input_path, orig_name, ip, ua, result)

def _cleanup_expired_outputs(now: float = None) -> dict:
    now = now or time.time()
    removed = 0
    errors = 0
    if not os.path.isdir(OUTPUT_DIR):
        return {"removed": 0, "errors": 0}
    for root, dirs, files in os.walk(OUTPUT_DIR, topdown=False):
        for name in files:
            path = os.path.join(root, name)
            try:
                if now - os.path.getmtime(path) > FILE_TTL:
                    os.unlink(path)
                    removed += 1
            except Exception:
                errors += 1
        for name in dirs:
            path = os.path.join(root, name)
            try:
                if os.path.isdir(path) and not os.listdir(path):
                    os.rmdir(path)
            except Exception:
                errors += 1
    return {"removed": removed, "errors": errors}

def _cleanup_expired_task_records(now: float = None) -> dict:
    now = now or time.time()
    threshold = time.strftime(
        "%Y-%m-%d %H:%M:%S",
        time.localtime(now - max(1, TASK_RETENTION_HOURS) * 3600),
    )
    removed = 0
    errors = 0
    with _SQL_LOCK:
        conn = _sql()
        rows = conn.execute(
            """
            SELECT id, output_path, output_dir, log_path
            FROM tasks
            WHERE created_at <= ?
              AND status IN ('done', 'error', 'timeout', 'failed', 'interrupted', 'expired')
            ORDER BY created_at ASC
            """,
            (threshold,),
        ).fetchall()
        for row in rows:
            try:
                output_path = row["output_path"] or ""
                output_dir = row["output_dir"] or ""
                log_path = row["log_path"] or ""
                if output_path:
                    _cleanup_output_path(output_path)
                if output_dir and output_dir != output_path:
                    _cleanup_output_path(output_dir)
                if log_path:
                    _cleanup_output_path(log_path)
                conn.execute("DELETE FROM tasks WHERE id=?", (row["id"],))
                removed += 1
            except Exception:
                errors += 1
        conn.commit()
        conn.close()
    return {"removed": removed, "errors": errors}

def _cleaner_loop():
    while True:
        time.sleep(max(60, CLEANUP_INTERVAL_MINUTES * 60))
        tmp_result = _cleanup_expired_tmp()
        file_result = _cleanup_expired_outputs()
        db_result = _cleanup_expired_task_records()
        if tmp_result["removed"] or file_result["removed"] or db_result["removed"]:
            logger.info(
                f"[Cleaner] removed inputs={tmp_result['removed']} files={file_result['removed']} tasks={db_result['removed']}"
            )

threading.Thread(target=_cleaner_loop, daemon=True).start()

def _error_payload(code: str, message: str, field: str = "", reason: str = "") -> dict:
    payload = {"error": message, "code": code}
    if field:
        payload["field"] = field
    if reason:
        payload["reason"] = reason
    return payload

def _cookie_value(cookie_header: str, name: str) -> str:
    for part in str(cookie_header or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.strip().split("=", 1)
        if key == name:
            return value
    return ""

def _session_cookie_settings() -> str:
    parts = [
        f"{ADMIN_SESSION_COOKIE}={{session_id}}",
        "HttpOnly",
        "Path=/",
        "SameSite=Strict",
        f"Max-Age={DEFAULT_ADMIN_SESSION_TTL_SECONDS}",
    ]
    if COOKIE_SECURE:
        parts.append("Secure")
    return "; ".join(parts)

def _anonymous_user_signing_key() -> bytes:
    secret = (PROXY_SECRET or DEFAULT_PROXY_SECRET).encode("utf-8")
    return hmac.new(secret, b"docxtool-anonymous-user-v1", hashlib.sha256).digest()

def _anonymous_user_signature(payload: str) -> str:
    digest = hmac.new(_anonymous_user_signing_key(), payload.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

def _create_anonymous_user(now: int = None) -> dict:
    issued_at = _now_unix() if now is None else int(now)
    owner_id = f"usr_{uuid.uuid4().hex}"
    payload = f"v1.{issued_at}.{owner_id}"
    token = f"{payload}.{_anonymous_user_signature(payload)}"
    return {
        "owner_id": owner_id,
        "token": token,
        "issued_at": issued_at,
        "expires_at": issued_at + ANONYMOUS_USER_COOKIE_MAX_AGE,
    }

def _parse_anonymous_user(token: str, now: int = None) -> dict:
    parts = str(token or "").strip().split(".")
    if len(parts) != 4 or parts[0] != "v1":
        return {}
    version, issued_raw, owner_id, signature = parts
    if not _re.fullmatch(r"usr_[0-9a-f]{32}", owner_id):
        return {}
    try:
        issued_at = int(issued_raw)
    except (TypeError, ValueError):
        return {}
    current = _now_unix() if now is None else int(now)
    if issued_at > current + 300 or current - issued_at > ANONYMOUS_USER_COOKIE_MAX_AGE:
        return {}
    payload = f"{version}.{issued_at}.{owner_id}"
    expected = _anonymous_user_signature(payload)
    if not signature or not hmac.compare_digest(signature, expected):
        return {}
    return {
        "owner_id": owner_id,
        "token": token,
        "issued_at": issued_at,
        "expires_at": issued_at + ANONYMOUS_USER_COOKIE_MAX_AGE,
    }

def _anonymous_user_cookie_header(token: str) -> str:
    parts = [
        f"{ANONYMOUS_USER_COOKIE}={token}",
        "HttpOnly",
        "Path=/",
        "SameSite=Lax",
        f"Max-Age={ANONYMOUS_USER_COOKIE_MAX_AGE}",
    ]
    if COOKIE_SECURE:
        parts.append("Secure")
    return "; ".join(parts)


def _anonymous_user_cookie_clear_header() -> str:
    parts = [f"{ANONYMOUS_USER_COOKIE}=", "HttpOnly", "Path=/", "SameSite=Lax", "Max-Age=0"]
    if COOKIE_SECURE:
        parts.append("Secure")
    return "; ".join(parts)

def _anonymous_user_from_headers(headers, cookie_header: str = "") -> tuple[dict, str]:
    token = _cookie_value(cookie_header, ANONYMOUS_USER_COOKIE)
    if not token and headers:
        token = _cookie_value(headers.get("Cookie", ""), ANONYMOUS_USER_COOKIE)
    identity = _parse_anonymous_user(token)
    if identity:
        return identity, ""
    identity = _create_anonymous_user()
    return identity, _anonymous_user_cookie_header(identity["token"])

def _anonymous_template_origin_allowed(headers) -> bool:
    origin = str(headers.get("Origin", "") if headers else "").strip().rstrip("/")
    if not origin:
        return False
    if FRONTEND_ORIGIN:
        return hmac.compare_digest(origin, FRONTEND_ORIGIN)
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    request_host = str(headers.get("Host", "") if headers else "").strip().lower()
    if request_host and parsed.netloc.lower() == request_host:
        return True
    return _is_local_origin_host(parsed.hostname)


def _user_session_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("ascii", "ignore")).hexdigest()


def _user_cookie_header(token: str, clear: bool = False, persistent: bool = True) -> str:
    parts = [f"{USER_SESSION_COOKIE}={'' if clear else token}", "HttpOnly", "Path=/", "SameSite=Lax"]
    if clear:
        parts.append("Max-Age=0")
    elif persistent:
        parts.append(f"Max-Age={USER_SESSION_MAX_AGE}")
    if COOKIE_SECURE:
        parts.append("Secure")
    return "; ".join(parts)


def _create_user_session(user_id: str, user_agent: str = "", remote_ip: str = "") -> dict:
    token = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
    csrf_token = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
    now = _now_unix()
    expires = now + USER_SESSION_MAX_AGE
    with _SQL_LOCK:
        conn = _sql()
        conn.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (now,))
        conn.execute("INSERT INTO user_sessions(session_hash,user_id,csrf_token,created_at,last_seen_at,expires_at,user_agent,remote_ip) VALUES (?,?,?,?,?,?,?,?)",
                     (_user_session_hash(token), user_id, csrf_token, now, now, expires, user_agent[:300], remote_ip[:80]))
        conn.commit()
        conn.close()
    return {"token": token, "csrf_token": csrf_token, "expires_at": expires}


def _user_session_from_headers(headers) -> dict:
    token = _cookie_value(headers.get("Cookie", "") if headers else "", USER_SESSION_COOKIE)
    if not token or len(token) < 32:
        return {}
    now = _now_unix()
    session_hash = _user_session_hash(token)
    with _SQL_LOCK:
        conn = _sql()
        row = conn.execute("SELECT s.*, u.username, u.display_name, u.status FROM user_sessions s JOIN users u ON u.id=s.user_id WHERE s.session_hash=? AND s.expires_at>?", (session_hash, now)).fetchone()
        if not row or row["status"] != "active":
            conn.execute("DELETE FROM user_sessions WHERE session_hash=?", (session_hash,))
            conn.commit()
        if row and row["status"] == "active" and now - int(row["last_seen_at"] or 0) >= USER_SESSION_REFRESH_SECONDS:
            conn.execute("UPDATE user_sessions SET last_seen_at=? WHERE session_hash=?", (now, session_hash))
            conn.commit()
        conn.close()
    if not row or row["status"] != "active":
        return {}
    return {"user_id": row["user_id"], "owner_id": row["user_id"], "username": row["username"], "display_name": row["display_name"], "csrf_token": row["csrf_token"], "token": token, "expires_at": row["expires_at"]}


def _delete_user_session(headers) -> None:
    session = _user_session_from_headers(headers)
    if not session:
        return
    with _SQL_LOCK:
        conn = _sql()
        conn.execute("DELETE FROM user_sessions WHERE session_hash=?", (_user_session_hash(session["token"]),))
        conn.commit()
        conn.close()


def _principal(headers, client_address=None) -> dict:
    cookie_header = headers.get("Cookie", "") if headers else ""
    had_user_session_cookie = bool(_cookie_value(cookie_header, USER_SESSION_COOKIE))
    session = _user_session_from_headers(headers)
    if session:
        return {"owner_id": session["user_id"], "authenticated": True, "invalid_user_session": False, **session}
    identity, cookie = _anonymous_user_from_headers(headers, cookie_header)
    return {"owner_id": identity["owner_id"], "authenticated": False, "user_id": None, "username": None, "display_name": None, "csrf_token": None, "cookie": cookie,
            "invalid_user_session": had_user_session_cookie,
            "has_identity_cookie": bool(_cookie_value(cookie_header, USER_SESSION_COOKIE) or _cookie_value(cookie_header, ANONYMOUS_USER_COOKIE))}


def _auth_origin_allowed(headers) -> bool:
    return _anonymous_template_origin_allowed(headers)


def _auth_csrf_allowed(headers, principal) -> bool:
    if not principal.get("authenticated"):
        return False
    value = str(headers.get("X-CSRF-Token", "") or "").strip()
    return bool(value and hmac.compare_digest(value, principal.get("csrf_token", "")))


def _migrate_anonymous_owner(conn, anonymous_id: str, user_id: str) -> None:
    if not _re.fullmatch(r"usr_[0-9a-f]{32}", str(anonymous_id or "")):
        return
    conn.execute("UPDATE tasks SET owner_id=? WHERE owner_id=?", (user_id, anonymous_id))
    existing_names = {
        str(row["name"]).casefold()
        for row in conn.execute(
            "SELECT name FROM presets WHERE owner_id=? AND visibility='private'",
            (user_id,),
        ).fetchall()
    }
    migrating = conn.execute(
        "SELECT id,name FROM presets WHERE owner_id=? AND visibility='private' ORDER BY created_at,id",
        (anonymous_id,),
    ).fetchall()
    for row in migrating:
        original = str(row["name"] or "个人模板")
        candidate = original
        suffix = 2
        while candidate.casefold() in existing_names:
            candidate = f"{original}（导入 {suffix}）"
            suffix += 1
        if candidate != original:
            conn.execute("UPDATE presets SET name=? WHERE id=?", (candidate, row["id"]))
        existing_names.add(candidate.casefold())
    conn.execute("UPDATE presets SET owner_id=? WHERE owner_id=? AND visibility='private'", (user_id, anonymous_id))


def _migrate_anonymous_resources(anonymous_id: str, user_id: str) -> None:
    with _SQL_LOCK:
        conn = _sql()
        conn.execute("BEGIN IMMEDIATE")
        _migrate_anonymous_owner(conn, anonymous_id, user_id)
        conn.commit()
        conn.close()

def _now_unix() -> int:
    return int(time.time())

def _prune_expired_admin_sessions(conn=None) -> None:
    own = False
    if conn is None:
        own = True
        conn = _sql()
    try:
        conn.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (_now_unix(),))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()

def _create_admin_session(user_agent: str = "", remote_ip: str = "") -> dict:
    session_id = uuid.uuid4().hex
    csrf_token = uuid.uuid4().hex + uuid.uuid4().hex
    now = _now_unix()
    expires_at = now + DEFAULT_ADMIN_SESSION_TTL_SECONDS
    with _SQL_LOCK:
        conn = _sql()
        _prune_expired_admin_sessions(conn)
        conn.execute(
            """INSERT INTO admin_sessions
               (session_id, csrf_token, user_agent, remote_ip, created_at, last_seen_at, expires_at)
               VALUES (?,?,?,?,?,?,?)""",
            (session_id, csrf_token, user_agent or "", remote_ip or "", now, now, expires_at),
        )
        conn.commit()
        conn.close()
    return {"session_id": session_id, "csrf_token": csrf_token, "expires_at": expires_at}

def _get_admin_session(session_id: str) -> dict:
    session_id = str(session_id or "").strip()
    if not session_id:
        return {}
    with _SQL_LOCK:
        conn = _sql()
        _prune_expired_admin_sessions(conn)
        row = conn.execute("SELECT * FROM admin_sessions WHERE session_id=?", (session_id,)).fetchone()
        if row:
            now = _now_unix()
            conn.execute("UPDATE admin_sessions SET last_seen_at=?, expires_at=? WHERE session_id=?",
                         (now, now + DEFAULT_ADMIN_SESSION_TTL_SECONDS, session_id))
            conn.commit()
        conn.close()
    return dict(row) if row else {}

def _delete_admin_session(session_id: str) -> None:
    session_id = str(session_id or "").strip()
    if not session_id:
        return
    with _SQL_LOCK:
        conn = _sql()
        conn.execute("DELETE FROM admin_sessions WHERE session_id=?", (session_id,))
        conn.commit()
        conn.close()

def _legacy_admin_token_from(parsed, headers, cookie_header: str = "") -> str:
    qs = parse_qs(parsed.query)
    token = (qs.get("token") or [""])[0]
    if token:
        return token
    header_token = headers.get("X-Admin-Token", "") if headers else ""
    if header_token:
        return header_token
    cookie_token = _cookie_value(cookie_header, "admin_token")
    return cookie_token

def _admin_authorized(parsed, headers, cookie_header: str = "") -> bool:
    token = _legacy_admin_token_from(parsed, headers, cookie_header)
    return bool(token and hmac.compare_digest(token, ADMIN_TOKEN))

def _admin_session_from_headers(headers, cookie_header: str = "") -> dict:
    cookie_value = _cookie_value(cookie_header, ADMIN_SESSION_COOKIE)
    if not cookie_value and headers:
        cookie_value = _cookie_value(headers.get("Cookie", ""), ADMIN_SESSION_COOKIE)
    return _get_admin_session(cookie_value)

def _admin_request_context(parsed, headers, cookie_header: str = "") -> dict:
    session = _admin_session_from_headers(headers, cookie_header)
    if session:
        return {"authorized": True, "session": session, "legacy_token": False}
    token = _legacy_admin_token_from(parsed, headers, cookie_header)
    if token and hmac.compare_digest(token, ADMIN_TOKEN):
        return {"authorized": True, "session": {}, "legacy_token": True}
    return {"authorized": False, "session": {}, "legacy_token": False}

def _file_api_authorized(headers, client_address=None) -> bool:
    header_token = headers.get("X-Proxy-Secret", "") if headers else ""
    if _compare_secret(header_token, PROXY_SECRET):
        return True
    # In production, Nginx also appears as a local peer. Do not let that
    # trusted-proxy topology turn a direct public request into an authorized
    # file API call; only the Worker-injected secret is sufficient.
    if PRODUCTION_MODE:
        return False
    host = headers.get("Host", "") if headers else ""
    if _is_local_host(host):
        return True
    return bool(client_address and client_address[0] in {"127.0.0.1", "::1"})

class FormatConfigRequestError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: str = "",
        reason: str = "",
        status: int = 400,
    ):
        self.code = code
        self.message = message
        self.field = field
        self.reason = reason
        self.status = status
        super().__init__(f"{code}: {message}")


def _format_config_error(code: str, message: str, *, field: str = "", reason: str = "") -> FormatConfigRequestError:
    return FormatConfigRequestError(
        code,
        message,
        field=field,
        reason=reason,
        status=413 if code == "FORMAT_CONFIG_TOO_LARGE" else 400,
    )

def _decode_format_config(headers) -> dict:
    raw = headers.get("X-Format-Config", "") if headers else ""
    if not raw:
        return None
    encoding = (headers.get("X-Format-Config-Encoding", "") if headers else "").strip().lower()
    if len(raw.encode("ascii", "ignore")) > MAX_FORMAT_CONFIG_HEADER_BYTES:
        raise _format_config_error("FORMAT_CONFIG_TOO_LARGE", "配置请求头过大", reason="配置请求头过大")
    if encoding != "base64url-json":
        raise _format_config_error("FORMAT_CONFIG_INVALID", "不支持的配置编码", reason="不支持的配置编码")
    try:
        padding = "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode((raw + padding).encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise _format_config_error("FORMAT_CONFIG_INVALID", "配置解码失败", reason="配置解码失败") from exc
    if len(decoded) > MAX_FORMAT_CONFIG_JSON_BYTES:
        raise _format_config_error("FORMAT_CONFIG_TOO_LARGE", "配置内容过大", reason="配置内容过大")
    try:
        config = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _format_config_error("FORMAT_CONFIG_INVALID", "配置 JSON 无效", reason="配置 JSON 无效") from exc
    if not isinstance(config, dict):
        raise _format_config_error("FORMAT_CONFIG_INVALID", "配置必须是 JSON 对象", reason="配置必须是 JSON 对象")
    if "styles" not in config or "page" not in config:
        raise _format_config_error("FORMAT_CONFIG_INVALID", "配置缺少 styles 或 page", reason="配置缺少 styles 或 page")
    try:
        return validate_format_config(config)
    except ConfigValidationError as exc:
        field = getattr(exc, "field", "")
        reason = getattr(exc, "reason", "") or "配置无效"
        message = f"{field}: {reason}" if field else reason
        raise _format_config_error(exc.code, message, field=field, reason=reason) from exc
    except ValueError as exc:
        raise _format_config_error("FORMAT_CONFIG_INVALID", "配置无效", reason="配置无效") from exc

def _upload_request_meta(headers) -> dict:
    return {
        "processing_mode": headers.get("X-Processing-Mode", "smart") if headers else "smart",
        "preset_id": headers.get("X-Preset-Id", "") if headers else "",
        "preset_name": unquote(headers.get("X-Preset-Name", "")) if headers else "",
        "template_type": headers.get("X-Template-Type", "") if headers else "",
    }

def _admin_token_from(parsed) -> str:
    return (parse_qs(parsed.query).get("token") or [""])[0]

def _admin_url(path: str, token: str = "") -> str:
    return path

def _admin_hidden_input(token: str = "") -> str:
    if not token:
        return ""
    return f'<input type="hidden" name="token" value="{_html_escape(token)}">'

def _csrf_hidden_input(csrf_token: str = "") -> str:
    if not csrf_token:
        return ""
    return f'<input type="hidden" name="csrf_token" value="{_html_escape(csrf_token)}">'

def _csrf_header_value(headers) -> str:
    return headers.get(ADMIN_CSRF_HEADER, "") if headers else ""

def _admin_cookie_header(session_id: str) -> str:
    cookie = _session_cookie_settings()
    return cookie.format(session_id=session_id)

def _validate_admin_csrf(headers, cookie_header: str = "") -> bool:
    session = _admin_session_from_headers(headers, cookie_header)
    if not session:
        return False
    csrf_header = _csrf_header_value(headers)
    return bool(csrf_header and hmac.compare_digest(csrf_header, session.get("csrf_token", "")))

def _route_path(path: str) -> str:
    path = path or ""
    return path[4:] if path.startswith("/api/") else path

def _json_dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

def _parse_json_body(body: bytes) -> dict:
    if not body:
        return {}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON_INVALID: 请求体不是有效的 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("JSON_INVALID: 请求体必须是 JSON 对象")
    return parsed

def _normalize_template_name(name: str) -> str:
    cleaned = _re.sub(r"\s+", " ", str(name or "")).strip()
    if not cleaned:
        raise ValueError("TEMPLATE_NAME_REQUIRED: 模板名称不能为空")
    if len(cleaned) > 80:
        raise ValueError("TEMPLATE_NAME_TOO_LONG: 模板名称不能超过 80 个字符")
    return cleaned

def _normalize_template_id(value: str) -> str:
    cleaned = _re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        raise ValueError("TEMPLATE_ID_INVALID: 模板 ID 无效")
    if len(cleaned) > 80:
        raise ValueError("TEMPLATE_ID_TOO_LONG: 模板 ID 不能超过 80 个字符")
    return cleaned

def _validate_template_config(config_obj: dict) -> dict:
    if not isinstance(config_obj, dict):
        raise ValueError("TEMPLATE_CONFIG_INVALID: config_json 必须是 JSON 对象")
    rules, settings, features = load_rules_and_settings(config_obj)
    styles = []
    for rule in rules:
        styles.append({
            "name": rule.level_name,
            "font": rule.font,
            "size": rule.font_size_label,
            "bold": rule.bold,
            "pattern": rule.numbering_pattern,
            "lang": rule.language,
            "indent": rule.first_line_indent,
            "align": rule.alignment,
            "spacing_before": rule.spacing_before,
            "spacing_after": rule.spacing_after,
            "left_indent": rule.left_indent,
            "right_indent": rule.right_indent,
            "page_break_before": rule.page_break_before,
        })
    normalized = {
        "schema_version": int(config_obj.get("schema_version", 1) or 1),
        "styles": styles,
        "page": {
            "width_cm": settings.page_width_cm,
            "height_cm": settings.page_height_cm,
            "margin_top_cm": settings.margin_top_cm,
            "margin_bottom_cm": settings.margin_bottom_cm,
            "margin_left_cm": settings.margin_left_cm,
            "margin_right_cm": settings.margin_right_cm,
            "lines_per_page": settings.lines_per_page,
            "chars_per_line": settings.chars_per_line,
            "line_spacing_pt": settings.line_spacing_value,
            "space_before_line": settings.space_before_line,
            "space_after_line": settings.space_after_line,
            "grid_alignment": settings.grid_alignment,
        },
        "features": {
            "numbered_bold_enabled": bool(features.get("numbered_bold_enabled", True)),
            "punctuation_enabled": bool(features.get("punctuation_enabled", True)),
        },
    }
    for key in (
        "punctuation",
        "classification",
        "numbering",
        "page_number",
        "signature_block",
        "table_format",
        "cleanup",
    ):
        normalized[key] = features.get(key, _core_feature_config_defaults()[key])
    for key in ("mode", "processing_mode", "preset_id", "preset_name", "template_type", "source", "output_suffix", "global"):
        if key in config_obj:
            normalized[key] = config_obj[key]
    return normalized

def _preset_row_to_dict(row, include_config: bool = False) -> dict:
    data = dict(row)
    data["is_system"] = bool(data.get("is_system"))
    data["is_default"] = bool(data.get("is_default"))
    data["visibility"] = data.get("visibility") or "public"
    data.pop("owner_id", None)
    if include_config:
        try:
            data["config_json"] = json.loads(data.get("config_json") or "{}")
        except json.JSONDecodeError:
            data["config_json"] = {}
    else:
        data.pop("config_json", None)
    return data

def _list_presets(owner_id: str = "") -> list:
    with _SQL_LOCK:
        conn = _sql()
        rows = conn.execute(
            """SELECT id, name, description, is_system, is_default, visibility,
                      version, created_at, updated_at
               FROM presets
               WHERE is_system=1 OR visibility='public' OR (visibility='private' AND owner_id=?)
               ORDER BY is_default DESC, is_system DESC, updated_at DESC, name ASC""",
            (owner_id or "",),
        ).fetchall()
        conn.close()
    return [_preset_row_to_dict(row, include_config=False) for row in rows]

def _get_preset(preset_id: str, owner_id: str = "", public_only: bool = False) -> dict:
    with _SQL_LOCK:
        conn = _sql()
        if public_only:
            row = conn.execute(
                "SELECT * FROM presets WHERE id=? AND (is_system=1 OR visibility='public')",
                (preset_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT * FROM presets
                   WHERE id=? AND (is_system=1 OR visibility='public' OR (visibility='private' AND owner_id=?))""",
                (preset_id, owner_id or ""),
            ).fetchone()
        conn.close()
    if not row:
        return {}
    return _preset_row_to_dict(row, include_config=True)

def _insert_preset(name: str, description: str, config_json: dict, is_system: bool = False,
                   is_default: bool = False, preset_id: str = "", owner_id: str = "",
                   visibility: str = "public") -> dict:
    preset_id = _normalize_template_id(preset_id) if preset_id else f"tpl_{uuid.uuid4().hex[:12]}"
    name = _normalize_template_name(name)
    normalized = _validate_template_config(config_json)
    payload = _json_dumps(normalized)
    visibility = "private" if visibility == "private" else "public"
    owner_id = str(owner_id or "").strip() if visibility == "private" else ""
    if visibility == "private" and not _re.fullmatch(r"usr_[0-9a-f]{32}", owner_id):
        raise ValueError("TEMPLATE_OWNER_INVALID: 模板所有者无效")
    now = _now_local()
    with _SQL_LOCK:
        conn = _sql()
        row = conn.execute(
            """SELECT id FROM presets
               WHERE lower(name)=lower(?) AND id<>? AND visibility=? AND owner_id=?""",
            (name, preset_id, visibility, owner_id),
        ).fetchone()
        if row:
            conn.close()
            raise ValueError("TEMPLATE_NAME_CONFLICT: 已存在同名模板，请先重命名")
        existing = conn.execute("SELECT * FROM presets WHERE id=?", (preset_id,)).fetchone()
        if existing:
            conn.close()
            raise ValueError("TEMPLATE_ID_CONFLICT: 模板 ID 已存在")
        conn.execute(
            """INSERT INTO presets
               (id, name, description, config_json, is_system, is_default, owner_id, visibility,
                version, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                preset_id,
                name,
                description or "",
                payload,
                1 if is_system else 0,
                1 if is_default else 0,
                owner_id,
                visibility,
                1,
                now,
                now,
            ),
        )
        conn.commit()
        conn.close()
    return _get_preset(preset_id, owner_id=owner_id, public_only=visibility == "public")

def _update_preset(preset_id: str, name: str, description: str, config_json: dict,
                   owner_id: str = "", public_only: bool = True) -> dict:
    preset_id = _normalize_template_id(preset_id)
    name = _normalize_template_name(name)
    normalized = _validate_template_config(config_json)
    payload = _json_dumps(normalized)
    now = _now_local()
    with _SQL_LOCK:
        conn = _sql()
        if public_only:
            row = conn.execute(
                "SELECT * FROM presets WHERE id=? AND (is_system=1 OR visibility='public')",
                (preset_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM presets WHERE id=? AND visibility='private' AND owner_id=?",
                (preset_id, owner_id or ""),
            ).fetchone()
        if not row:
            conn.close()
            raise ValueError("TEMPLATE_NOT_FOUND: 模板不存在")
        if row["is_system"] and not bool(row["is_default"]):
            # 系统模板仍允许更新内容，但保留标记
            pass
        dup = conn.execute(
            """SELECT id FROM presets
               WHERE lower(name)=lower(?) AND id<>? AND visibility=? AND owner_id=?""",
            (name, preset_id, row["visibility"] or "public", row["owner_id"] or ""),
        ).fetchone()
        if dup:
            conn.close()
            raise ValueError("TEMPLATE_NAME_CONFLICT: 已存在同名模板，请先重命名")
        version = int(row["version"] or 1) + 1
        conn.execute(
            """UPDATE presets SET
               name=?, description=?, config_json=?, version=?, updated_at=?
               WHERE id=?""",
            (name, description or "", payload, version, now, preset_id),
        )
        conn.commit()
        conn.close()
    return _get_preset(preset_id, owner_id=owner_id, public_only=public_only)

def _delete_preset(preset_id: str, owner_id: str = "", public_only: bool = True) -> dict:
    preset_id = _normalize_template_id(preset_id)
    with _SQL_LOCK:
        conn = _sql()
        if public_only:
            row = conn.execute(
                "SELECT * FROM presets WHERE id=? AND (is_system=1 OR visibility='public')",
                (preset_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM presets WHERE id=? AND visibility='private' AND owner_id=?",
                (preset_id, owner_id or ""),
            ).fetchone()
        if not row:
            conn.close()
            raise ValueError("TEMPLATE_NOT_FOUND: 模板不存在")
        if row["is_system"]:
            conn.close()
            raise ValueError("TEMPLATE_SYSTEM_LOCKED: 系统模板不能删除")
        conn.execute("DELETE FROM presets WHERE id=?", (preset_id,))
        conn.commit()
        conn.close()
    return {"deleted": True, "id": preset_id}

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
        "max_tasks": MAX_TASKS,
        "task_retention_hours": TASK_RETENTION_HOURS,
        "max_cached_tasks": MAX_CACHED_TASKS,
        "cleanup_interval_minutes": CLEANUP_INTERVAL_MINUTES,
        "max_upload_mb": MAX_SIZE // 1048576,
        "upload_read_timeout_seconds": UPLOAD_READ_TIMEOUT_SECONDS,
        "process_timeout_seconds": PROCESS_TIMEOUT,
        "max_docx_uncompressed_mb": MAX_DOCX_UNCOMPRESSED_BYTES // 1048576,
        "max_docx_file_count": MAX_DOCX_FILE_COUNT,
        "max_docx_xml_mb": MAX_DOCX_XML_BYTES // 1048576,
        "max_docx_media_mb": MAX_DOCX_MEDIA_BYTES // 1048576,
        "max_docx_compression_ratio": MAX_DOCX_COMPRESSION_RATIO,
        "max_workers": MAX_WORKERS,
        "max_queue": MAX_QUEUE,
        "proxy_secret_required": True,
        "proxy_secret_configured": bool(PROXY_SECRET),
        "frontend_origin": FRONTEND_ORIGIN,
        "queued": _queued_count(),
        "processing": _active_count(),
    }

def _server_bind_address() -> tuple:
    return (BIND_HOST, PORT)

def _startup_urls() -> dict:
    base = f"http://{BIND_HOST}:{PORT}"
    return {
        "tool": base,
        "admin_login": f"{base}/admin/login",
        "monitor": f"{base}/monitor",
        "tunnel_command": f"cloudflared tunnel --url {base}",
    }

def _monitor_url(admin_token: str, query: dict, **overrides) -> str:
    q = dict(query or {})
    q.update(overrides)
    values = {}
    for key in ("recent_page", "recent_size", "ip_page", "ip_size"):
        value = q.get(key, "")
        if value != "":
            values[key] = value
    return "/monitor?" + urlencode(values) if values else "/monitor"

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
        "timeout": ("超时", "error"),
        "failed": ("失败", "error"),
        "interrupted": ("中断", "error"),
        "expired": ("过期", "error"),
        "queued": ("排队中", "queued"),
        "processing": ("处理中", "processing"),
    }
    return mapping.get(status or "", (status or "-", "processing"))

def _monitor_html(stats: dict, admin_token: str = "") -> str:
    limit = _limit_settings()
    limit_checked = " checked" if limit["enabled"] else ""
    limit_state = "已开启" if limit["enabled"] else "已关闭"
    csrf_input = _csrf_hidden_input(admin_token)
    query = stats.get("query", _normalize_monitor_query())
    recent_pager = _pager_html(stats, admin_token, "recent_page", "recent_pages")
    ip_pager = _pager_html(stats, admin_token, "ip_page", "ip_pages")
    ready = _ready_payload()
    version = _version_payload()
    ready_state = "在线" if ready.get("ok") else "需检查"
    ready_class = "online" if ready.get("ok") else "offline"
    trend = stats.get("trend", [])
    max_trend = max([int(item.get("total", 0) or 0) for item in trend] + [1])
    rows = []
    for item in stats.get("recent", []):
        st = item.get("status", "")
        tag, cls = _status_badge(st)
        rows.append(
            f"<tr><td class=mono>{_html_escape(str(item.get('created_at','')))[:16]}</td>"
            f"<td class=fn title=\"{_html_escape(str(item.get('filename','-')))}\">{_html_escape(str(item.get('filename','-')))[:40]}</td>"
            f"<td class=mono>{_html_escape(item.get('ip','-'))}</td>"
            f"<td>{(item.get('file_size',0)/1024):.0f} KB</td>"
            f"<td>{_html_escape(item.get('doc_type','-'))}</td>"
            f"<td>{item.get('paragraphs',0)}</td>"
            f"<td>{((item.get('duration_ms',0) or 0)/1000):.1f}s</td>"
            f"<td><span class=\"status-tag {cls}\">{tag}</span></td>"
            f"<td><a class=\"table-action\" href=\"{_admin_url('/log/' + _html_escape(item.get('id','')), admin_token)}\" target=\"_blank\">查看日志</a></td></tr>")
    ips = "".join(
        f"<tr><td class=mono>{_html_escape(r.get('ip','-'))}</td>"
            f"<td>{r.get('c',0)}</td><td class=ok>{r.get('done',0)}</td><td class=badtxt>{r.get('error',0)}</td>"
            f"<td class=mono>{_html_escape(str(r.get('last','')))[:16]}</td>"
            f"<td class=fn title=\"{_html_escape(r.get('last_filename','-'))}\">{_html_escape(r.get('last_filename','-'))[:32]}</td>"
        f"<td class=actions><a class=\"table-action\" href=\"{_admin_url('/ip?addr=' + quote(str(r.get('ip','')), safe=''), admin_token)}\" target=\"_blank\">明细</a>"
        f"<form method=\"post\" action=\"/ban\" onsubmit=\"return confirm('确认封禁该 IP？')\">{csrf_input}<input type=\"hidden\" name=\"ip\" value=\"{_html_escape(r.get('ip',''))}\"><input type=\"hidden\" name=\"reason\" value=\"monitor\"><button class=\"link-danger\" type=\"submit\">封禁</button></form></td></tr>"
        for r in stats.get("top_ips", []))
    banned_rows = "".join(
        f"<tr><td class=mono>{_html_escape(r.get('ip','-'))}</td>"
        f"<td>{_html_escape(r.get('reason',''))}</td>"
        f"<td class=mono>{_html_escape(str(r.get('created_at','')))[:16]}</td>"
        f"<td><form method=\"post\" action=\"/unban\">{csrf_input}<input type=\"hidden\" name=\"ip\" value=\"{_html_escape(r.get('ip',''))}\"><button class=\"link-danger\" type=\"submit\">解封</button></form></td></tr>"
        for r in stats.get("banned_ips", []))
    trend_bars = "".join(
        f"<div class=\"trend-row\"><span class=\"trend-date\">{_html_escape(item.get('date', '-'))}</span>"
        f"<div class=\"trend-track\"><i class=\"trend-done\" style=\"width:{max(2, int(item.get('done', 0) or 0) / max_trend * 100):.1f}%\"></i>"
        f"<i class=\"trend-error\" style=\"width:{max(0, int(item.get('error', 0) or 0) / max_trend * 100):.1f}%\"></i></div>"
        f"<span class=\"trend-count\">{item.get('total', 0)}<small>项</small></span></div>"
        for item in trend[-14:]) or '<div class="empty-state">暂无趋势数据，完成任务后将在此显示。</div>'
    check_items = "".join(
        f"<li class={'check-ok' if value else 'check-bad'}><span></span>{_html_escape(label)}<b>{'正常' if value else '异常'}</b></li>"
        for label, value in (("数据库", ready.get("checks", {}).get("database")), ("输出目录", ready.get("checks", {}).get("output_dir")), ("日志目录", ready.get("checks", {}).get("log_dir")))
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>工作台 · 公文智能排版</title>
<style>
:root{{--bg:#07101f;--panel:#0d1a2e;--panel2:#111f35;--line:rgba(160,181,215,.17);--muted:#8fa2be;--text:#edf4ff;--gold:#f6c85f;--gold-soft:rgba(246,200,95,.12);--blue:#74b9ff;--green:#55d6a0;--red:#fb7185}}
*{{margin:0;padding:0;box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{font-family:"Microsoft YaHei","Noto Sans CJK SC","WenQuanYi Micro Hei","PingFang SC",Arial,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
a{{color:inherit;text-decoration:none}}button,input{{font:inherit}}
.shell{{display:grid;grid-template-columns:224px minmax(0,1fr);min-height:100vh}}
.sidebar{{position:sticky;top:0;height:100vh;padding:24px 16px;border-right:1px solid var(--line);background:linear-gradient(180deg,#0b1729,#07101f);display:flex;flex-direction:column}}
.brand{{display:flex;align-items:center;gap:11px;padding:0 8px 25px;border-bottom:1px solid var(--line)}}
.brand-mark{{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,#f6c85f,#e89c3a);color:#152238;font-weight:900;font-size:18px}}
.brand strong{{display:block;font-size:14px;letter-spacing:.02em}}.brand small{{display:block;color:var(--muted);font-size:11px;margin-top:3px}}
.nav-label{{color:#637a9c;font-size:10px;letter-spacing:.12em;margin:24px 10px 8px;text-transform:uppercase}}
.side-nav{{display:grid;gap:5px}}.side-nav a{{display:flex;align-items:center;gap:10px;padding:11px 12px;border:1px solid transparent;border-radius:10px;color:#b8c8df;font-size:13px;transition:.18s}}
.side-nav a:hover,.side-nav a.active{{background:var(--gold-soft);border-color:rgba(246,200,95,.2);color:#ffe7a4}}
.nav-index{{width:22px;color:var(--gold);font-family:Consolas,monospace;font-size:11px}}
.side-footer{{margin-top:auto;padding:13px 10px;border-top:1px solid var(--line);color:var(--muted);font-size:11px;line-height:1.7}}
.side-footer b{{color:#cfe0f8;font-weight:600}}
.main{{min-width:0;padding:22px 30px 40px}}
.topbar{{display:flex;justify-content:space-between;align-items:center;gap:18px;padding-bottom:18px;border-bottom:1px solid var(--line)}}
.eyebrow{{color:var(--gold);font-size:11px;letter-spacing:.12em;text-transform:uppercase;margin-bottom:5px}}h1{{font-size:24px;letter-spacing:.01em}}
.top-actions{{display:flex;align-items:center;gap:9px;flex-wrap:wrap;justify-content:flex-end}}
.service-pill{{display:inline-flex;align-items:center;gap:7px;padding:8px 11px;border:1px solid rgba(85,214,160,.25);background:rgba(85,214,160,.08);border-radius:999px;color:#a7f3d0;font-size:12px}}
.service-pill.offline{{border-color:rgba(251,113,133,.3);background:rgba(251,113,133,.08);color:#fecdd3}}.service-dot{{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px rgba(85,214,160,.12)}}.offline .service-dot{{background:var(--red);box-shadow:0 0 0 4px rgba(251,113,133,.12)}}
.top-link,.top-button{{padding:8px 11px;border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.04);color:#b9c9df;font-size:12px;cursor:pointer}}.top-link:hover,.top-button:hover{{border-color:rgba(246,200,95,.4);color:#ffe7a4}}
.alert{{display:flex;gap:12px;align-items:flex-start;padding:12px 14px;margin:18px 0;border:1px solid rgba(251,113,133,.3);border-radius:10px;background:rgba(251,113,133,.09);color:#fecdd3;font-size:12px;line-height:1.6}}
.section{{scroll-margin-top:20px;margin-top:24px}}.section-heading{{display:flex;justify-content:space-between;align-items:flex-end;gap:14px;margin-bottom:12px}}.section-heading h2{{font-size:16px}}.section-heading p{{color:var(--muted);font-size:12px;margin-top:4px}}.section-meta{{color:var(--muted);font-size:12px}}
.metric-grid{{display:grid;grid-template-columns:repeat(8,minmax(100px,1fr));gap:9px}}
.metric{{min-width:0;padding:15px 14px;border:1px solid var(--line);border-radius:10px;background:linear-gradient(145deg,rgba(18,35,59,.9),rgba(10,24,42,.9))}}.metric .value{{font-size:24px;color:#f6d985;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.metric .label{{color:var(--muted);font-size:11px;margin-top:6px}}.metric.good .value{{color:var(--green)}}.metric.bad .value{{color:#ff9cab}}
.work-grid{{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(270px,.8fr);gap:14px}}.panel{{min-width:0;border:1px solid var(--line);border-radius:12px;background:linear-gradient(145deg,rgba(14,30,51,.96),rgba(9,21,37,.96));overflow:hidden}}.panel-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:17px 18px;border-bottom:1px solid var(--line)}}.panel-head h3{{font-size:14px}}.panel-head p{{color:var(--muted);font-size:11px;margin-top:4px}}.panel-body{{padding:17px 18px}}
.health-list{{display:grid;gap:9px}}.health-list li{{list-style:none;display:flex;align-items:center;gap:9px;color:#b9c9df;font-size:12px}}.health-list li span{{width:7px;height:7px;border-radius:50%;background:var(--green)}}.health-list li.check-bad span{{background:var(--red)}}.health-list li b{{margin-left:auto;font-size:11px;color:var(--green);font-weight:600}}.health-list li.check-bad b{{color:#ff9cab}}
.runtime-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px}}.runtime-item{{padding:10px;border-radius:8px;background:rgba(255,255,255,.04);border:1px solid rgba(160,181,215,.1)}}.runtime-item b{{display:block;font-size:15px;color:#e6effd}}.runtime-item span{{display:block;color:var(--muted);font-size:10px;margin-top:4px}}
.trend{{display:grid;gap:8px}}.trend-row{{display:grid;grid-template-columns:86px minmax(0,1fr) 42px;gap:10px;align-items:center}}.trend-date,.trend-count{{color:var(--muted);font-size:11px}}.trend-count{{text-align:right;color:#dce8fa}}.trend-count small{{color:var(--muted);margin-left:2px}}.trend-track{{height:12px;display:flex;gap:2px;background:rgba(255,255,255,.06);border-radius:99px;overflow:hidden}}.trend-track i{{display:block;height:100%;min-width:0}}.trend-done{{background:var(--green)}}.trend-error{{background:var(--red)}}
.legend{{display:flex;gap:14px;margin-top:15px;color:var(--muted);font-size:11px}}.legend i{{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px}}.legend .done{{background:var(--green)}}.legend .error{{background:var(--red)}}
.table-wrap{{overflow-x:auto}}table{{width:100%;min-width:840px;border-collapse:collapse}}th{{padding:10px 11px;text-align:left;color:#7890b2;font-size:10px;font-weight:600;letter-spacing:.04em;white-space:nowrap;background:rgba(4,13,25,.4)}}td{{padding:10px 11px;border-top:1px solid rgba(160,181,215,.09);color:#c8d6e9;font-size:12px;white-space:nowrap}}tr:hover td{{background:rgba(246,200,95,.045)}}.fn{{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.mono{{font-family:Consolas,"Noto Sans Mono CJK SC","WenQuanYi Micro Hei",monospace;font-size:11px}}.ok{{color:var(--green)}}.badtxt{{color:#ff9cab}}.status-tag{{display:inline-flex;padding:4px 7px;border-radius:5px;font-size:10px;font-weight:700}}.status-tag.done{{background:rgba(85,214,160,.12);color:#a7f3d0}}.status-tag.error{{background:rgba(251,113,133,.12);color:#fecdd3}}.status-tag.queued{{background:rgba(246,200,95,.12);color:#ffe7a4}}.status-tag.processing{{background:rgba(116,185,255,.12);color:#bfdbfe}}.table-action{{color:#9bc8ff;font-size:11px}}.table-action:hover{{color:#ffe7a4}}.actions{{display:flex;align-items:center;gap:10px}}.actions form{{margin:0}}.link-danger{{border:0;background:transparent;color:#ff9cab;padding:0;cursor:pointer;font-size:11px}}.link-danger:hover{{color:#fff}}
.control-grid{{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,.8fr);gap:14px}}.control-form{{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap}}.control-form label{{display:grid;gap:6px;color:#9eb1cb;font-size:11px}}.control-form input[type=number]{{width:100px;height:36px;border:1px solid var(--line);border-radius:7px;background:#081529;color:#edf4ff;padding:0 9px}}.control-form input[type=checkbox]{{accent-color:var(--gold)}}.primary-btn{{height:36px;padding:0 13px;border:1px solid rgba(246,200,95,.35);border-radius:7px;background:var(--gold-soft);color:#ffe7a4;cursor:pointer;font-size:12px}}.primary-btn:hover{{background:rgba(246,200,95,.2)}}.danger-btn{{height:36px;padding:0 13px;border:1px solid rgba(251,113,133,.3);border-radius:7px;background:rgba(251,113,133,.08);color:#fecdd3;cursor:pointer;font-size:12px}}
.empty-state{{padding:24px 10px;text-align:center;color:var(--muted);font-size:12px}}.pager{{display:flex;gap:12px;align-items:center;justify-content:flex-end;padding:12px 18px 16px;color:var(--muted);font-size:11px}}.pager a{{color:#9bc8ff}}.pager a.disabled{{pointer-events:none;color:#536985}}.hint{{color:var(--muted);font-size:11px;line-height:1.6}}
@media(max-width:1180px){{.metric-grid{{grid-template-columns:repeat(4,minmax(120px,1fr))}}}}
@media(max-width:900px){{.shell{{display:block}}.sidebar{{position:static;height:auto;padding:14px 18px;display:block;border-right:0;border-bottom:1px solid var(--line)}}.brand{{padding-bottom:12px;border-bottom:0}}.nav-label,.side-footer{{display:none}}.side-nav{{display:flex;overflow-x:auto;padding-top:8px;scrollbar-width:none}}.side-nav::-webkit-scrollbar{{display:none}}.side-nav a{{white-space:nowrap;padding:8px 10px}}.main{{padding:18px}}.work-grid,.control-grid{{grid-template-columns:1fr}}}}
@media(max-width:560px){{.main{{padding:14px}}.topbar{{align-items:flex-start;flex-direction:column}}.top-actions{{justify-content:flex-start}}h1{{font-size:21px}}.metric-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.metric .value{{font-size:21px}}.panel-head,.panel-body{{padding:14px}}.section{{margin-top:18px}}}}
</style></head>
<body>
<div class="shell">
<aside class="sidebar"><a class="brand" href="/"><span class="brand-mark">文</span><span><strong>公文智能排版</strong><small>管理员工作台</small></span></a>
<div class="nav-label">WORKSPACE</div><nav class="side-nav">
<a class="active" href="#overview"><span class="nav-index">01</span>总览</a><a href="#tasks"><span class="nav-index">02</span>任务中心</a><a href="#security"><span class="nav-index">03</span>安全与访问</a><a href="#runtime"><span class="nav-index">04</span>运行设置</a><a href="#logs"><span class="nav-index">05</span>日志查询</a>
</nav><div class="side-footer">当前服务<br><b>Python · 9527</b><br>数据目录受项目路径管理</div></aside>
<main class="main">
<header class="topbar"><div><div class="eyebrow">ADMIN WORKSPACE / {html.escape(str(version.get('version', '')))}</div><h1>运行总览</h1></div><div class="top-actions"><span class="service-pill {ready_class}"><i class="service-dot"></i>服务{ready_state}</span><button class="top-button" type="button" onclick="window.location.reload()">刷新</button><a class="top-link" href="/">返回工具</a><a class="top-link" href="/stats" target="_blank">JSON</a><form method="post" action="/admin/logout">{csrf_input}<button class="top-button" type="submit">退出</button></form></div></header>
{('<div class="alert"><strong>运行检查</strong><span>数据库、输出目录或日志目录存在异常，请先检查运行环境，再处理任务。</span></div>') if not ready.get('ok') else ''}
<section id="overview" class="section"><div class="section-heading"><div><h2>关键指标</h2><p>排版服务当前累计运行数据</p></div><span class="section-meta">自动刷新 · 15 秒</span></div><div class="metric-grid">
<div class="metric"><div class="value">{stats.get('total',0)}</div><div class="label">总任务</div></div><div class="metric good"><div class="value">{stats.get('done',0)}</div><div class="label">成功任务</div></div><div class="metric bad"><div class="value">{stats.get('error',0)}</div><div class="label">失败任务</div></div><div class="metric good"><div class="value">{stats.get('rate',0)}%</div><div class="label">成功率</div></div><div class="metric"><div class="value">{version.get('queued',0)}</div><div class="label">当前排队</div></div><div class="metric"><div class="value">{version.get('processing',0)}</div><div class="label">当前处理</div></div><div class="metric"><div class="value">{stats.get('avg_s',0)}s</div><div class="label">平均耗时</div></div><div class="metric"><div class="value">{stats.get('unique_ips',0)}</div><div class="label">独立 IP</div></div>
</div></section>
<section class="section"><div class="work-grid"><div class="panel"><div class="panel-head"><div><h3>任务趋势</h3><p>按日期统计成功与失败任务</p></div><span class="section-meta">最近 {len(trend[-14:])} 个记录日</span></div><div class="panel-body"><div class="trend">{trend_bars}</div><div class="legend"><span><i class="done"></i>成功</span><span><i class="error"></i>失败</span></div></div></div><div class="panel"><div class="panel-head"><div><h3>运行状态</h3><p>服务依赖和处理队列</p></div><span class="service-pill {ready_class}">{ready_state}</span></div><div class="panel-body"><ul class="health-list">{check_items}</ul><div class="runtime-grid"><div class="runtime-item"><b>{version.get('max_workers',0)}</b><span>工作线程</span></div><div class="runtime-item"><b>{version.get('max_queue',0)}</b><span>队列上限</span></div><div class="runtime-item"><b>{version.get('max_upload_mb',0)} MB</b><span>单文件上限</span></div><div class="runtime-item"><b>{version.get('process_timeout_seconds',0)}s</b><span>处理超时</span></div></div></div></div></div></section>
<section id="tasks" class="section"><div class="section-heading"><div><h2>任务中心</h2><p>优先处理失败任务，点击日志查看完整排版过程</p></div><span class="section-meta">{len(stats.get('recent',[]))} / {stats.get('recent_total',0)} 条</span></div><div class="panel"><div class="table-wrap"><table><thead><tr><th>时间</th><th>文件名</th><th>来源 IP</th><th>大小</th><th>类型</th><th>段数</th><th>耗时</th><th>状态</th><th>操作</th></tr></thead><tbody>{"".join(rows) or '<tr><td colspan="9"><div class="empty-state">暂无任务，用户上传 DOCX 后将在此显示。</div></td></tr>'}</tbody></table></div>{recent_pager}</div></section>
<section id="security" class="section"><div class="section-heading"><div><h2>安全与访问</h2><p>查看访问活跃度并处理异常来源</p></div><span class="section-meta">{stats.get('ip_total',0)} 个活跃 IP · {len(stats.get('banned_ips',[]))} 个封禁</span></div><div class="work-grid"><div class="panel"><div class="panel-head"><div><h3>活跃 IP</h3><p>按最近访问时间排序</p></div></div><div class="table-wrap"><table><thead><tr><th>IP</th><th>上传</th><th>成功</th><th>失败</th><th>最近活跃</th><th>最近文件</th><th>操作</th></tr></thead><tbody>{ips or '<tr><td colspan="7"><div class="empty-state">暂无访问记录。</div></td></tr>'}</tbody></table></div>{ip_pager}</div><div class="panel"><div class="panel-head"><div><h3>封禁 IP</h3><p>危险操作需要管理员确认</p></div></div><div class="table-wrap"><table><thead><tr><th>IP</th><th>原因</th><th>时间</th><th>操作</th></tr></thead><tbody>{banned_rows or '<tr><td colspan="4"><div class="empty-state">暂无封禁 IP。</div></td></tr>'}</tbody></table></div></div></div></section>
<section id="runtime" class="section"><div class="section-heading"><div><h2>运行设置</h2><p>调整访问限额、列表密度和过期文件清理</p></div><span class="section-meta">限额{limit_state}</span></div><div class="control-grid"><div class="panel"><div class="panel-head"><div><h3>上传限额</h3><p>同一 IP 在指定时间窗口内的排版次数限制</p></div></div><div class="panel-body"><form class="control-form" method="post" action="/limit">{csrf_input}<label><span>状态</span><span><input type="checkbox" name="enabled" value="1"{limit_checked}> 启用</span></label><label><span>时间窗口（秒）</span><input type="number" min="1" name="window_seconds" value="{limit['window_seconds']}"></label><label><span>允许次数</span><input type="number" min="1" name="count" value="{limit['count']}"></label><button class="primary-btn" type="submit">保存设置</button></form></div></div><div class="panel"><div class="panel-head"><div><h3>文件维护</h3><p>清理超过 TTL 的临时输入和输出文件</p></div></div><div class="panel-body"><p class="hint">文件保留时间：{version.get('file_ttl_seconds', FILE_TTL)} 秒。清理操作不会删除数据库任务记录。</p><form method="post" action="/cleanup" style="margin-top:13px">{csrf_input}<button class="danger-btn" type="submit">清理过期文件</button></form></div></div></div><div class="panel" style="margin-top:14px"><div class="panel-head"><div><h3>显示设置</h3><p>控制任务中心和活跃 IP 每页显示数量</p></div></div><div class="panel-body"><form class="control-form" method="get" action="/monitor"><label><span>最近任务/页</span><input type="number" min="1" max="{MAX_MONITOR_PAGE_SIZE}" name="recent_size" value="{query['recent_size']}"></label><label><span>活跃 IP/页</span><input type="number" min="1" max="{MAX_MONITOR_PAGE_SIZE}" name="ip_size" value="{query['ip_size']}"></label><button class="primary-btn" type="submit">应用</button><a class="top-link" href="/monitor">恢复默认</a><span class="hint">默认每页 50 条，最多 {MAX_MONITOR_PAGE_SIZE} 条。</span></form></div></div></section>
<section id="logs" class="section"><div class="panel"><div class="panel-head"><div><h3>日志查询</h3><p>从任务中心的“查看日志”进入具体任务日志</p></div><a class="top-link" href="/stats" target="_blank">打开 JSON API</a></div><div class="panel-body"><p class="hint">日志仅保存在服务端运行目录，页面不会显示 Cookie、管理员密钥或代理密钥。失败任务优先从任务中心进入排查。</p></div></div></section>
<footer class="side-footer" style="margin-top:24px">最后生成：{_html_escape(_now_local()[:19])} · 页面每 15 秒自动刷新</footer>
</main></div>
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
    csrf_input = _csrf_hidden_input(admin_token)
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
            f"<td><span class=\"status-tag {cls}\">{tag}</span></td>"
            f"<td><a class=\"action-link\" href=\"{_admin_url('/log/' + _html_escape(item.get('id','')), admin_token)}\" target=\"_blank\">查看日志</a></td></tr>")
    total = _ip_upload_count(ip)
    last_hour = _ip_upload_count(ip, 3600)
    banned = _is_ip_banned(ip)
    action = (f"<form method=\"post\" action=\"/unban\">{csrf_input}<input type=\"hidden\" name=\"ip\" value=\"{_html_escape(ip)}\"><button class=\"danger-btn\" type=\"submit\">解封 IP</button></form>"
              if banned else
              f"<form method=\"post\" action=\"/ban\" onsubmit=\"return confirm('确认封禁该 IP？')\">{csrf_input}<input type=\"hidden\" name=\"ip\" value=\"{_html_escape(ip)}\"><input type=\"hidden\" name=\"reason\" value=\"monitor\"><button class=\"danger-btn\" type=\"submit\">封禁 IP</button></form>")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>IP 明细 · {html.escape(ip)}</title>
<style>
:root{{--bg:#07101f;--panel:#0d1a2e;--line:rgba(160,181,215,.17);--text:#edf4ff;--muted:#8fa2be;--gold:#f6c85f;--green:#55d6a0;--red:#fb7185}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","Noto Sans CJK SC","WenQuanYi Micro Hei","PingFang SC",Arial,sans-serif}}.page{{width:min(1180px,calc(100% - 36px));margin:0 auto;padding:24px 0 40px}}.topbar{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding-bottom:18px;border-bottom:1px solid var(--line)}}.nav{{display:flex;gap:9px;align-items:center}}.nav a,.danger-btn{{height:34px;padding:0 11px;border:1px solid var(--line);border-radius:7px;background:rgba(255,255,255,.04);color:#b9c9df;text-decoration:none;font-size:11px;display:inline-flex;align-items:center;cursor:pointer}}.danger-btn{{border-color:rgba(251,113,133,.28);background:rgba(251,113,133,.08);color:#fecdd3}}.nav form{{margin:0}}.eyebrow{{color:var(--gold);font-size:10px;letter-spacing:.12em;margin-bottom:5px}}h1{{font-size:22px;margin:0}}.mono{{font-family:Consolas,"Noto Sans Mono CJK SC","WenQuanYi Micro Hei",monospace;font-size:11px}}.cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:20px 0}}.card{{padding:16px;border:1px solid var(--line);border-radius:10px;background:linear-gradient(145deg,rgba(18,35,59,.9),rgba(10,24,42,.9))}}.n{{font-size:23px;font-weight:800;color:#f6d985}}.card div:last-child{{font-size:11px;color:var(--muted);margin-top:5px}}.panel{{border:1px solid var(--line);border-radius:12px;background:var(--panel);overflow:hidden}}.panel-head{{padding:16px 18px;border-bottom:1px solid var(--line)}}.panel-head h2{{font-size:15px;margin:0}}.panel-head p{{font-size:11px;color:var(--muted);margin:4px 0 0}}.table-wrap{{overflow-x:auto}}table{{width:100%;min-width:780px;border-collapse:collapse}}th{{background:rgba(4,13,25,.4);text-align:left;padding:10px 11px;color:#7890b2;font-size:10px}}td{{font-size:12px;padding:10px 11px;border-top:1px solid rgba(160,181,215,.09);color:#c8d6e9;white-space:nowrap}}.fn{{max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.status-tag{{display:inline-flex;padding:4px 7px;border-radius:5px;font-size:10px;font-weight:700}}.status-tag.done{{background:rgba(85,214,160,.12);color:#a7f3d0}}.status-tag.error{{background:rgba(251,113,133,.12);color:#fecdd3}}.action-link{{color:#9bc8ff;text-decoration:none;font-size:11px}}.empty{{padding:28px;text-align:center;color:var(--muted)}}@media(max-width:640px){{.page{{width:min(100% - 24px,1180px);padding-top:14px}}.topbar{{align-items:flex-start;flex-direction:column}}.cards{{grid-template-columns:1fr}}}}
</style></head><body>
<main class="page"><header class="topbar"><div><div class="eyebrow">SECURITY / IP DETAIL</div><h1>IP 上传明细：<span class="mono">{html.escape(ip)}</span></h1></div><div class="nav"><a href="/monitor#security">返回工作台</a>{action}</div></header>
<div class="cards"><div class="card"><div class="n">{total}</div><div>总上传次数</div></div>
<div class="card"><div class="n">{last_hour}</div><div>最近 1 小时</div></div>
<div class="card"><div class="n">{"已封禁" if banned else "正常"}</div><div>当前状态</div></div></div>
<section class="panel"><div class="panel-head"><h2>任务记录</h2><p>该 IP 最近关联的排版任务和处理状态</p></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>文件名</th><th>大小</th><th>段数</th><th>耗时</th><th>状态</th><th>日志</th></tr></thead><tbody>{"".join(rows) or '<tr><td colspan="7"><div class="empty">暂无上传记录</div></td></tr>'}</tbody></table></div></section></main>
</body></html>"""


# ── 安全工具 ──

def _is_safe_uuid(s: str) -> bool:
    return bool(_re.match(r'^[0-9a-fA-F-]{32,36}$', s or ""))

def _sanitize_filename(name: str) -> str:
    """Return a Windows-safe filename for display and download headers."""
    raw = str(name or "").replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()
    raw = raw.replace("\\", "/")
    raw = os.path.basename(raw) or raw
    raw = _re.sub(r'[/\\:*?"<>|]+', "_", raw)
    raw = _re.sub(r"\s+", " ", raw).strip(" ._")
    if not raw or raw in {".", ".."}:
        raw = "download.docx"
    stem, ext = os.path.splitext(raw)
    if not stem:
        stem = "download"
    reserved = {
        "con", "prn", "aux", "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if stem.rstrip(" ._").lower() in reserved:
        stem = f"_{stem}"
    if not ext:
        ext = ".docx"
    cleaned = f"{stem}{ext}"
    return cleaned[:120]

def _safe_download_filename(orig_name: str) -> str:
    safe = _sanitize_filename(orig_name)
    stem, _ext = os.path.splitext(safe)
    if not stem:
        stem = "download"
    return f"{stem}_排版文件.docx"

def _content_disposition_filename(filename: str) -> str:
    safe = _sanitize_filename(filename)
    ascii_fallback = _re.sub(r"[^A-Za-z0-9._-]+", "_", safe.encode("ascii", "ignore").decode("ascii")).strip("._-")
    if not ascii_fallback:
        ascii_fallback = "formatted.docx"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(safe, safe='')}"

def _is_local_host(host: str) -> bool:
    host = (host or "").strip().lower()
    if not host:
        return False
    if host.startswith("[") and "]" in host:
        host = host[1:host.index("]")]
        return host in {"localhost", "127.0.0.1", "::1"}
    host = host.split(":", 1)[0]
    return host in {"localhost", "127.0.0.1", "::1"}

def _trusted_proxy_source(client_address) -> bool:
    if not TRUST_PROXY_HEADERS:
        return False
    if not client_address:
        return False
    ip = str(client_address[0] or "").strip()
    if not ip:
        return False
    return ip in TRUSTED_PROXY_IPS

def _compare_secret(value: str, secret: str) -> bool:
    return bool(value) and bool(secret) and hmac.compare_digest(value, secret)

def _html_escape(text: str) -> str:
    return html.escape(str(text or ""))

def _redact_sensitive_log(text: str) -> str:
    value = str(text or "")
    for name in ("ADMIN_TOKEN", "PROXY_SECRET", "Authorization", "Proxy-Authorization", "Cookie", "Set-Cookie"):
        value = _re.sub(
            rf"(?im)^({name}\s*[:=]\s*).+$",
            r"\1[REDACTED]",
            value,
        )
    return value

def _split_ip_header(value: str):
    return [p.strip() for p in str(value or "").split(",") if p.strip()]

def _is_ipv4(value: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(value.strip()), ipaddress.IPv4Address)
    except ValueError:
        return False

def _client_ip(headers, client_address) -> str:
    """Return the actual client IP only when the request came from a trusted proxy."""
    client_ip = client_address[0] if client_address else ""
    if not _trusted_proxy_source(client_address):
        return client_ip

    candidates = []
    for name in ("X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP"):
        candidates.extend(_split_ip_header(headers.get(name, "")))
    if client_ip:
        candidates.append(client_ip)
    for ip in candidates:
        if _is_ipv4(ip):
            return ip
    for ip in candidates:
        if _is_ip(ip):
            return ip
    return client_ip


class Handler(BaseHTTPRequestHandler):

    def _set_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")

    def _set_cors_headers(self):
        for key, value in cors_headers_for_request(self.headers.get("Origin", "")).items():
            self.send_header(key, value)

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self._set_security_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = _route_path(parsed.path)
        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/admin/login":
            self._serve_admin_login()
        elif path == "/admin/session":
            self._handle_admin_session()
        elif path == "/health":
            self._json(_health_payload())
        elif path == "/ready":
            ready = _ready_payload()
            self._json(ready, 200 if ready.get("ok") else 503)
        elif path == "/version":
            self._json(_version_payload())
        elif path == "/auth/me":
            self._handle_auth_me()
        elif path == "/stats":
            if not self._require_admin(parsed):
                return
            self._json(get_sql_stats(_monitor_query_from(parsed)))
        elif path == "/monitor":
            if not self._require_admin(parsed):
                return
            ctx = self._admin_context_or_default()
            if ctx.get("legacy_token") and not ctx.get("session"):
                session = _create_admin_session(self.headers.get("User-Agent", ""), self.client_address[0] if self.client_address else "")
                self._redirect("/monitor", extra_headers=[("Set-Cookie", _admin_cookie_header(session["session_id"]))])
                return
            query = _monitor_query_from(parsed)
            self._text(_monitor_html(get_sql_stats(query), self._admin_csrf_token(parsed)), "text/html")
        elif path == "/ip":
            if not self._require_admin(parsed):
                return
            self._handle_ip_detail(parsed)
        elif path == "/ban":
            self.send_error(405)
        elif path == "/unban":
            self.send_error(405)
        elif path == "/limit":
            self.send_error(405)
        elif path == "/cleanup":
            self.send_error(405)
        elif path == "/presets":
            self._handle_presets_list()
        elif path.startswith("/presets/"):
            self._handle_preset_detail(path.split("/", 2)[-1])
        elif path.startswith("/status/") or path.startswith("/api/status/"):
            if not self._require_file_api():
                return
            self._handle_status(path.split("/")[-1])
        elif path.startswith("/download/") or path.startswith("/api/download/"):
            if not self._require_file_api():
                return
            self._handle_download(path.split("/")[-1])
        elif path.startswith("/log/"):
            if not self._require_admin(parsed):
                return
            self._handle_log(path.split("/")[-1])
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = _route_path(parsed.path)
        if path == "/upload":
            if not self._require_file_api():
                return
            self._handle_upload_raw()
        elif path == "/auth/register":
            self._handle_auth_register()
        elif path == "/auth/login":
            self._handle_auth_login()
        elif path == "/auth/logout":
            self._handle_auth_logout()
        elif path == "/admin/login":
            self._handle_admin_login()
        elif path == "/admin/logout":
            self._handle_admin_logout()
        elif path == "/ban":
            if not self._require_admin_post(parsed):
                return
            self._handle_ban(parsed)
        elif path == "/unban":
            if not self._require_admin_post(parsed):
                return
            self._handle_unban(parsed)
        elif path == "/limit":
            if not self._require_admin_post(parsed):
                return
            self._handle_limit(parsed)
        elif path == "/cleanup":
            if not self._require_admin_post(parsed):
                return
            self._handle_cleanup(parsed)
        elif path == "/presets":
            if not self._require_preset_mutation(parsed):
                return
            self._handle_preset_create()
        elif path.startswith("/presets/"):
            if not self._require_preset_mutation(parsed):
                return
            self._handle_preset_update(path.split("/", 2)[-1])
        else:
            self.send_error(404)

    def do_PUT(self):
        path = _route_path(urlparse(self.path).path)
        if path == "/upload":
            if not self._require_file_api():
                return
            self._handle_upload_raw()
        elif path.startswith("/presets/"):
            if not self._require_preset_mutation(urlparse(self.path)):
                return
            self._handle_preset_update(path.split("/", 2)[-1])
        else:
            self.send_error(404)

    def do_DELETE(self):
        path = _route_path(urlparse(self.path).path)
        if path.startswith("/presets/"):
            parsed = urlparse(self.path)
            if not self._require_preset_mutation(parsed):
                return
            self._handle_preset_delete(path.split("/", 2)[-1])
        else:
            self.send_error(404)

    def _serve_html(self):
        candidates = [
            str(resource_path("frontend", "pages", "index.html")),
        ]
        p = next((path for path in candidates if os.path.exists(path)), candidates[-1])
        try:
            with open(p, "r", encoding="utf-8") as f:
                self._text(f.read(), "text/html")
        except FileNotFoundError:
            self.send_error(404)

    def _serve_admin_login(self):
        body = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>管理员登录 · 公文智能排版</title>
<style>
:root{--bg:#07101f;--panel:#0d1a2e;--line:rgba(160,181,215,.18);--text:#edf4ff;--muted:#8fa2be;--gold:#f6c85f}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;font-family:"Microsoft YaHei","Noto Sans CJK SC","PingFang SC",sans-serif;background:radial-gradient(circle at 25% 20%,rgba(66,100,150,.16),transparent 32%),var(--bg);color:var(--text)}
.workspace{width:min(920px,100%);display:grid;grid-template-columns:minmax(0,1.05fr) minmax(340px,.75fr);border:1px solid var(--line);border-radius:14px;overflow:hidden;background:rgba(7,16,31,.86);box-shadow:0 28px 80px rgba(0,0,0,.35)}
.intro{padding:52px 48px;background:linear-gradient(145deg,rgba(18,36,61,.94),rgba(9,23,40,.94));border-right:1px solid var(--line)}.mark{width:46px;height:46px;display:grid;place-items:center;border-radius:11px;background:linear-gradient(135deg,#f6c85f,#e89c3a);color:#152238;font-size:22px;font-weight:900;margin-bottom:28px}.eyebrow{color:var(--gold);font-size:11px;letter-spacing:.13em;margin-bottom:10px}h1{font-size:29px;margin:0 0 13px}.intro p{max-width:38ch;color:#a9bad1;line-height:1.8;font-size:14px;margin:0}.status{display:grid;gap:10px;margin-top:34px}.status span{display:flex;align-items:center;gap:9px;color:#8fa2be;font-size:12px}.status i{width:7px;height:7px;border-radius:50%;background:#55d6a0}
.login{padding:48px 40px;background:rgba(9,21,37,.92);display:flex;flex-direction:column;justify-content:center}.login h2{font-size:18px;margin:0 0 6px}.login>p{color:var(--muted);font-size:12px;line-height:1.7;margin:0 0 24px}label{display:block;color:#b9c9df;font-size:12px;font-weight:700;margin-bottom:8px}input{width:100%;height:44px;border:1px solid var(--line);border-radius:8px;background:#071426;color:#fff;padding:0 12px;font-size:14px;outline:none}input:focus{border-color:rgba(246,200,95,.5);box-shadow:0 0 0 4px rgba(246,200,95,.08)}button{width:100%;height:44px;margin-top:15px;border:1px solid rgba(246,200,95,.42);border-radius:8px;background:rgba(246,200,95,.14);color:#ffe7a4;font-weight:800;cursor:pointer}button:hover{background:rgba(246,200,95,.22)}.hint{font-size:11px;color:#6f85a4;margin-top:14px;line-height:1.65}.back{display:inline-block;color:#9bc8ff;font-size:11px;margin-top:18px;text-decoration:none}
@media(max-width:760px){.workspace{grid-template-columns:1fr}.intro{padding:30px;border-right:0;border-bottom:1px solid var(--line)}.intro p,.status{display:none}.mark{margin-bottom:18px}.login{padding:30px}}
</style></head>
<body><main class="workspace"><section class="intro"><div class="mark">文</div><div class="eyebrow">DOCXTOOL ADMIN</div><h1>公文排版工作台</h1><p>集中查看任务状态、运行指标、访问安全和服务配置。管理员会话通过安全 Cookie 建立。</p><div class="status"><span><i></i>后端服务已连接</span><span><i></i>管理员会话受保护</span></div></section><section class="login"><h2>管理员登录</h2><p>输入服务器配置的管理员密钥，登录后进入运行工作台。</p><form method="post" action="/admin/login"><label for="admin_token">管理员密钥</label><input id="admin_token" name="admin_token" type="password" autocomplete="current-password" required autofocus><button type="submit">进入工作台</button></form><div class="hint">密钥仅用于建立当前管理员会话，不会写入页面地址。</div><a class="back" href="/">返回公文排版工具</a></section></main></body></html>"""
        self._text(body, "text/html")

    def _admin_context_or_default(self):
        return getattr(self, "_admin_context", {"authorized": False, "session": {}, "legacy_token": False})

    def _admin_csrf_token(self, parsed=None) -> str:
        ctx = self._admin_context_or_default()
        session = ctx.get("session") or {}
        if session.get("csrf_token"):
            return session["csrf_token"]
        if ctx.get("legacy_token"):
            return ""
        return ""

    def _handle_admin_session(self):
        session = _admin_session_from_headers(self.headers, self.headers.get("Cookie", ""))
        if not session:
            self._json_error("UNAUTHORIZED", "需要管理员权限", 403)
            return
        self._json({
            "ok": True,
            "csrf_token": session.get("csrf_token", ""),
            "expires_at": session.get("expires_at", 0),
        })

    def _handle_admin_login(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = _read_exact(self.rfile, length) if length > 0 else b""
        params = {}
        if body:
            try:
                params = {k: (v[-1] if isinstance(v, list) and v else v) for k, v in parse_qs(body.decode("utf-8")).items()}
            except Exception:
                params = {}
        token = str(params.get("admin_token") or params.get("token") or "").strip()
        if not token:
            self._json_error("INVALID_LOGIN", "请输入管理员密钥", 400)
            return
        if not hmac.compare_digest(token, ADMIN_TOKEN):
            self._json_error("INVALID_LOGIN", "管理员密钥错误", 403)
            return
        session = _create_admin_session(self.headers.get("User-Agent", ""), self.client_address[0] if self.client_address else "")
        cookie = _admin_cookie_header(session["session_id"])
        self._redirect("/monitor", extra_headers=[("Set-Cookie", cookie)])

    def _handle_admin_logout(self):
        session = _admin_session_from_headers(self.headers, self.headers.get("Cookie", ""))
        if session:
            _delete_admin_session(session.get("session_id", ""))
        cookie = f"{ADMIN_SESSION_COOKIE}=; HttpOnly; Path=/; SameSite=Strict; Max-Age=0"
        if COOKIE_SECURE:
            cookie += "; Secure"
        self._redirect("/admin/login", extra_headers=[("Set-Cookie", cookie)])

    def _require_admin(self, parsed) -> bool:
        ctx = _admin_request_context(parsed, self.headers, self.headers.get("Cookie", ""))
        self._admin_context = ctx
        if ctx.get("authorized"):
            return True
        self._json_error("UNAUTHORIZED", "需要管理员权限", 403)
        return False

    def _require_admin_post(self, parsed) -> bool:
        ctx = _admin_request_context(parsed, self.headers, self.headers.get("Cookie", ""))
        self._admin_context = ctx
        if not ctx.get("authorized"):
            self._json_error("UNAUTHORIZED", "需要管理员权限", 403)
            return False
        params = self._request_params(parsed)
        self._request_params_cache = params
        csrf_value = str(params.get("csrf_token") or _csrf_header_value(self.headers) or "").strip()
        session = ctx.get("session") or {}
        if not session or not csrf_value or not hmac.compare_digest(csrf_value, session.get("csrf_token", "")):
            self._json_error("CSRF_INVALID", "CSRF 校验失败", 403)
            return False
        return True

    def _require_preset_mutation(self, parsed) -> bool:
        """Authorize either an admin public-template mutation or a private one."""
        admin_context = _admin_request_context(parsed, self.headers, self.headers.get("Cookie", ""))
        if admin_context.get("authorized"):
            if not self._require_admin_post(parsed):
                return False
            self._preset_owner_id = ""
            self._preset_public_only = True
            self._preset_admin = True
            return True
        if not _anonymous_template_origin_allowed(self.headers):
            self._json_error("CSRF_INVALID", "模板请求来源校验失败", 403)
            return False
        self._request_params_cache = self._request_params(parsed)
        principal = _principal(self.headers, self.client_address)
        if principal.get("authenticated") and not _auth_csrf_allowed(self.headers, principal):
            self._json_error("CSRF_INVALID", "CSRF 校验失败", 403)
            return False
        self._preset_owner_id = principal["owner_id"]
        self._preset_cookie_header = principal.get("cookie", "")
        self._preset_public_only = False
        self._preset_admin = False
        return True

    def _require_file_api(self) -> bool:
        if _file_api_authorized(self.headers, self.client_address):
            return True
        self._json_error("PROXY_REQUIRED", "缺少或无效的代理密钥", 403)
        return False

    def _auth_json_request(self) -> dict | None:
        if not _auth_origin_allowed(self.headers):
            self._json_error("ORIGIN_INVALID", "请求来源不被允许", 403)
            return None
        content_type = (self.headers.get("Content-Type", "") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._json_error("CONTENT_TYPE_INVALID", "请求必须使用 application/json", 415)
            return None
        payload = self._request_params(urlparse(self.path))
        return payload if isinstance(payload, dict) else None

    def _handle_auth_me(self):
        principal = _principal(self.headers, self.client_address)
        data = {"authenticated": bool(principal.get("authenticated")), "user": None, "csrf_token": None}
        if principal.get("authenticated"):
            data["user"] = {"id": principal["user_id"], "username": principal["username"], "display_name": principal.get("display_name", "")}
            data["csrf_token"] = principal.get("csrf_token")
        extra = []
        if principal.get("cookie"):
            extra.append(("Set-Cookie", principal["cookie"]))
        if principal.get("invalid_user_session"):
            extra.append(("Set-Cookie", _user_cookie_header("", clear=True)))
        self._json({"ok": True, "data": data}, extra_headers=extra)

    def _handle_auth_register(self):
        payload = self._auth_json_request()
        if payload is None:
            return
        allowed, retry = _auth_rate_allow("register-ip", _client_ip(self.headers, self.client_address), 3600, 5)
        if not allowed:
            self._json_error("RATE_LIMITED", "注册请求过于频繁，请稍后再试", 429, retry_after=retry)
            return
        try:
            display, username_norm = validate_username(payload.get("username", ""))
            password = validate_password(payload.get("password", ""))
        except ValueError as exc:
            code, msg = str(exc).split(":", 1)
            self._json_error(code, msg, 400)
            return
        anonymous = _principal(self.headers, self.client_address)
        user_id = f"usr_{uuid.uuid4().hex}"
        now = _now_unix()
        conn = None
        try:
            with _SQL_LOCK:
                conn = _sql()
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("INSERT INTO users(id,username,username_norm,password_hash,display_name,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (user_id, display, username_norm, hash_password(password), display, now, now))
                _migrate_anonymous_owner(conn, anonymous.get("owner_id", ""), user_id)
                conn.commit()
                conn.close()
        except Exception as exc:
            if conn is not None:
                conn.rollback()
                conn.close()
            if "UNIQUE constraint" in str(exc):
                self._json_error("USERNAME_TAKEN", "用户名已存在", 409)
            else:
                self._json_error("REGISTER_FAILED", "注册失败", 500)
            return
        session = _create_user_session(user_id, self.headers.get("User-Agent", ""), self.client_address[0] if self.client_address else "")
        self._json({"ok": True, "data": {"user": {"id": user_id, "username": display, "display_name": display}, "csrf_token": session["csrf_token"]}}, 201, [
            ("Set-Cookie", _user_cookie_header(session["token"])),
            ("Set-Cookie", _anonymous_user_cookie_clear_header()),
        ])

    def _handle_auth_login(self):
        payload = self._auth_json_request()
        if payload is None:
            return
        try:
            _, username_norm = validate_username(payload.get("username", ""))
        except ValueError:
            self._json_error("INVALID_CREDENTIALS", "用户名或密码错误", 401)
            return
        ip = _client_ip(self.headers, self.client_address)
        ip_allowed, ip_retry = _auth_rate_allow("login-ip", ip, 600, 30)
        name_allowed, name_retry = _auth_rate_allow("login-name", username_norm, 600, 10)
        if not ip_allowed or not name_allowed:
            self._json_error("RATE_LIMITED", "登录请求过于频繁，请稍后再试", 429, retry_after=max(ip_retry, name_retry))
            return
        password = str(payload.get("password", ""))
        with _SQL_LOCK:
            conn = _sql()
            row = conn.execute("SELECT * FROM users WHERE username_norm=?", (username_norm,)).fetchone()
            conn.close()
        if not row or not verify_password(row["password_hash"], password)[0]:
            self._json_error("INVALID_CREDENTIALS", "用户名或密码错误", 401)
            return
        if row["status"] != "active":
            self._json_error("ACCOUNT_DISABLED", "账号已停用", 403)
            return
        _, needs_rehash = verify_password(row["password_hash"], password)
        with _SQL_LOCK:
            conn = _sql()
            now = _now_unix()
            if needs_rehash:
                conn.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?", (hash_password(password), now, row["id"]))
            conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now, row["id"]))
            conn.commit()
            conn.close()
        principal = _principal(self.headers, self.client_address)
        _migrate_anonymous_resources(principal.get("owner_id", ""), row["id"])
        session = _create_user_session(row["id"], self.headers.get("User-Agent", ""), self.client_address[0] if self.client_address else "")
        remember_me = _parse_bool(str(payload.get("remember_me", "true")), True)
        self._json({"ok": True, "data": {"user": {"id": row["id"], "username": row["username"], "display_name": row["display_name"]}, "csrf_token": session["csrf_token"]}}, extra_headers=[
            ("Set-Cookie", _user_cookie_header(session["token"], persistent=remember_me)),
            ("Set-Cookie", _anonymous_user_cookie_clear_header()),
        ])

    def _handle_auth_logout(self):
        if not _auth_origin_allowed(self.headers):
            self._json_error("ORIGIN_INVALID", "请求来源不被允许", 403)
            return
        principal = _principal(self.headers, self.client_address)
        if principal.get("authenticated") and not _auth_csrf_allowed(self.headers, principal):
            self._json_error("CSRF_INVALID", "CSRF 校验失败", 403)
            return
        _delete_user_session(self.headers)
        self._json({"ok": True, "data": {"logged_out": True}}, extra_headers=[("Set-Cookie", _user_cookie_header("", True))])

    def _handle_upload_raw(self):
        principal = _principal(self.headers, self.client_address)
        ip = _client_ip(self.headers, self.client_address)
        if _is_ip_banned(ip):
            logger.warning(f"[Security] banned ip blocked: {ip}")
            self._json_error("IP_BANNED", "该 IP 已被禁止访问", 403)
            return
        if _upload_limit_exceeded(ip):
            logger.warning(f"[Security] upload limit exceeded: {ip}")
            self._json_error("UPLOAD_LIMIT_EXCEEDED", "当前 IP 在该时间段内排版次数已达上限，请稍后再试", 429)
            return
        if not _allow(ip):
            self._json_error("RATE_LIMITED", "请求过于频繁，请稍后再试", 429)
            return
        try:
            try:
                format_config = _decode_format_config(self.headers)
            except FormatConfigRequestError as cfg_error:
                self._json_error(
                    cfg_error.code,
                    cfg_error.message,
                    cfg_error.status,
                    field=cfg_error.field,
                    reason=cfg_error.reason,
                )
                return
            request_meta = _upload_request_meta(self.headers)
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_SIZE:
                self._json_error("FILE_TOO_LARGE", "文件过大或无内容", 413)
                return
            task_id = str(uuid.uuid4())
            raw_name = unquote(self.headers.get("X-Filename", "upload.docx"))
            task_tmp_dir = _task_tmp_dir(task_id)
            os.makedirs(task_tmp_dir, exist_ok=True)
            input_path = _task_tmp_input_path(task_id, raw_name)
            old_timeout = None
            try:
                old_timeout = self.connection.gettimeout()
            except Exception:
                old_timeout = None
            try:
                self.connection.settimeout(UPLOAD_READ_TIMEOUT_SECONDS)
                written = _read_exact_to_file(self.rfile, input_path, length, timeout=UPLOAD_READ_TIMEOUT_SECONDS)
            except (TimeoutError, socket.timeout):
                _cleanup_task_tmp(task_id, input_path)
                self._json_error("UPLOAD_TIMEOUT", "文件上传超时", 408)
                return
            except Exception as exc:
                _cleanup_task_tmp(task_id, input_path)
                self._json_error("UPLOAD_FAILED", f"文件上传失败: {exc}"[:200], 400)
                return
            finally:
                if old_timeout is not None:
                    try:
                        self.connection.settimeout(old_timeout)
                    except Exception:
                        pass
            if written != length:
                _cleanup_task_tmp(task_id, input_path)
                self._json_error("INCOMPLETE_UPLOAD", "读取不完整", 400)
                return
            try:
                validate_docx_upload(
                    input_path,
                    max_upload_bytes=MAX_SIZE,
                    max_uncompressed_bytes=MAX_DOCX_UNCOMPRESSED_BYTES,
                    max_file_count=MAX_DOCX_FILE_COUNT,
                    max_xml_bytes=MAX_DOCX_XML_BYTES,
                    max_media_bytes=MAX_DOCX_MEDIA_BYTES,
                    max_compression_ratio=MAX_DOCX_COMPRESSION_RATIO,
                )
            except DocxValidationError as exc:
                _cleanup_task_tmp(task_id, input_path)
                self._json_error(exc.code, exc.message, exc.status)
                return
            compatibility_warnings = detect_docx_complexity(input_path)
            md5 = hashlib.md5()
            with open(input_path, "rb") as fp:
                while True:
                    chunk = fp.read(1024 * 1024)
                    if not chunk:
                        break
                    md5.update(chunk)
            h = md5.hexdigest()
            logger.info(
                f"[Upload] size={written} expect={length} md5={h} task={task_id[:8]} "
                f"preset={request_meta.get('preset_name','')} mode={request_meta.get('processing_mode','smart')} "
                f"frontend_config={bool(format_config)}"
            )
            _ensure_workers_started()
            try:
                info = _enqueue_task(task_id, input_path, raw_name, ip, self.headers.get("User-Agent", ""),
                                     format_config=format_config, request_meta=request_meta,
                                     compatibility_warnings=compatibility_warnings,
                                     owner_id=principal["owner_id"])
            except OverflowError as exc:
                _cleanup_task_tmp(task_id, input_path)
                message = str(exc)
                text = message.split(":", 1)[1].strip() if ":" in message else "服务器繁忙，请稍后再试"
                self._json_error("QUEUE_FULL", text, 503)
                return
            payload = {"task_id": task_id, "status": "queued", **info}
            if compatibility_warnings:
                payload["compatibility_warnings"] = compatibility_warnings
            self._json(payload, extra_headers=[("Set-Cookie", principal["cookie"])] if principal.get("cookie") else None)
        except Exception as e:
            try:
                if 'task_id' in locals():
                    _cleanup_task_tmp(task_id, locals().get("input_path", ""))
            except Exception:
                pass
            self._json_error("INTERNAL_ERROR", str(e)[:200], 500)

    def _handle_status(self, task_id: str):
        if not _is_safe_uuid(task_id):
            self._json_error("INVALID_TASK_ID", "无效的任务 ID", 400)
            return
        principal = _principal(self.headers, self.client_address)
        task = _public_task_state(task_id, principal["owner_id"])
        if not task:
            self._json_error("TASK_NOT_FOUND", "任务不存在或已过期", 404)
        else:
            self._json(task)

    def _handle_download(self, task_id: str):
        if not _is_safe_uuid(task_id):
            self._json_error("INVALID_TASK_ID", "无效的任务 ID", 400)
            return
        principal = _principal(self.headers, self.client_address)
        owner_id = principal["owner_id"]
        with TASKS_LOCK:
            task = TASKS.get(task_id)
            if task and owner_id and task.get("owner_id", "") != owner_id:
                task = None
        if not task or task.get("status") != "done":
            with _SQL_LOCK:
                conn = _sql()
                row = conn.execute(
                    "SELECT status, output_path, output_filename, filename FROM tasks WHERE id=? AND owner_id=?",
                    (task_id, owner_id),
                ).fetchone()
                conn.close()
            if not row or row["status"] != "done":
                self._json_error("FILE_NOT_READY", "文件未就绪", 400)
                return
            path = row["output_path"] or ""
            download_name = row["output_filename"] or _safe_download_filename(row["filename"] or "download.docx")
        else:
            path = task.get("output_path") or task.get("output") or ""
            download_name = task.get("download_name") or _safe_download_filename(task.get("filename", "download.docx"))
        if not path or not os.path.exists(path):
            self._json_error("FILE_EXPIRED", "文件已过期", 410)
            return
        try:
            file_size = os.path.getsize(path)
        except OSError:
            self._json_error("FILE_EXPIRED", "文件已过期", 410)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.send_header("Content-Disposition", _content_disposition_filename(download_name))
        self.send_header("Content-Length", str(file_size))
        self._set_cors_headers()
        self._set_security_headers()
        self.end_headers()
        _stream_file(path, self.wfile)

    def _redirect(self, target: str, extra_headers=None):
        self.send_response(303)
        self.send_header("Location", target)
        if extra_headers:
            if isinstance(extra_headers, dict):
                items = extra_headers.items()
            else:
                items = extra_headers
            for key, value in items:
                self.send_header(key, value)
        self._set_security_headers()
        self.end_headers()

    def _request_params(self, parsed) -> dict:
        cached = getattr(self, "_request_params_cache", None)
        if cached is not None:
            return cached
        params = {k: (v[-1] if isinstance(v, list) and v else v) for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        if self.command not in ("POST", "PUT", "DELETE"):
            return params
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return params
        body = _read_exact(self.rfile, length)
        if not body:
            return params
        content_type = (self.headers.get("Content-Type", "") or "").split(";", 1)[0].strip().lower()
        try:
            if content_type == "application/json":
                body_params = _parse_json_body(body)
                for key, value in body_params.items():
                    params[key] = value
            else:
                body_params = parse_qs(body.decode("utf-8"), keep_blank_values=True)
                for key, value in body_params.items():
                    params[key] = value[-1] if isinstance(value, list) and value else value
        except Exception:
            return params
        return params

    def _query_ip(self, parsed):
        qs = parse_qs(parsed.query)
        return (qs.get("ip") or qs.get("addr") or [""])[0].strip()

    def _handle_ip_detail(self, parsed):
        ip = self._query_ip(parsed)
        if not _is_ip(ip):
            self._json_error("INVALID_IP", "无效的 IP", 400)
            return
        self._text(_ip_detail_html(ip, self._admin_csrf_token(parsed)), "text/html")

    def _handle_ban(self, parsed):
        params = self._request_params(parsed)
        ip = (params.get("ip") or params.get("addr") or "").strip()
        if not _is_ip(ip):
            self._json_error("INVALID_IP", "无效的 IP", 400)
            return
        reason = str(params.get("reason") or "monitor")[:120]
        _ban_ip(ip, reason)
        logger.warning(f"[Security] ip banned: {ip} reason={reason}")
        self._redirect("/monitor")

    def _handle_unban(self, parsed):
        params = self._request_params(parsed)
        ip = (params.get("ip") or params.get("addr") or "").strip()
        if not _is_ip(ip):
            self._json_error("INVALID_IP", "无效的 IP", 400)
            return
        _unban_ip(ip)
        logger.warning(f"[Security] ip unbanned: {ip}")
        self._redirect("/monitor")

    def _handle_limit(self, parsed):
        params = self._request_params(parsed)
        enabled = str(params.get("enabled") or "0") == "1"
        try:
            window_seconds = int(params.get("window_seconds") or DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS)
        except ValueError:
            window_seconds = DEFAULT_UPLOAD_LIMIT_WINDOW_SECONDS
        try:
            count = int(params.get("count") or DEFAULT_UPLOAD_LIMIT_COUNT)
        except ValueError:
            count = DEFAULT_UPLOAD_LIMIT_COUNT
        _save_limit_settings(enabled, window_seconds, count)
        logger.warning(
            f"[Security] upload limit settings updated: enabled={enabled} "
            f"window_seconds={max(1, window_seconds)} count={max(1, count)}"
        )
        self._redirect("/monitor")

    def _handle_cleanup(self, parsed):
        tmp_result = _cleanup_expired_tmp()
        file_result = _cleanup_expired_outputs()
        db_result = _cleanup_expired_task_records()
        logger.warning(
            f"[Cleaner] manual cleanup inputs={tmp_result['removed']} files={file_result['removed']} tasks={db_result['removed']} "
            f"errors={tmp_result['errors'] + file_result['errors'] + db_result['errors']}"
        )
        self._redirect("/monitor")

    def _handle_presets_list(self):
        principal = _principal(self.headers, self.client_address)
        self._json(
            {"presets": _list_presets(principal["owner_id"])},
            extra_headers=[("Set-Cookie", principal["cookie"])] if principal.get("cookie") else None,
        )

    def _handle_preset_detail(self, preset_id: str):
        preset_id = str(preset_id or "").strip()
        if not preset_id:
            self._json_error("TEMPLATE_ID_INVALID", "无效的模板 ID", 400)
            return
        principal = _principal(self.headers, self.client_address)
        preset = _get_preset(preset_id, owner_id=principal["owner_id"])
        if not preset:
            self._json_error("TEMPLATE_NOT_FOUND", "模板不存在", 404)
            return
        self._json(preset, extra_headers=[("Set-Cookie", principal["cookie"])] if principal.get("cookie") else None)

    def _handle_preset_create(self):
        payload = getattr(self, "_request_params_cache", {})
        try:
            preset = _insert_preset(
                payload.get("name", ""),
                payload.get("description", ""),
                payload.get("config_json", {}),
                preset_id=payload.get("id", ""),
                owner_id=getattr(self, "_preset_owner_id", ""),
                visibility="public" if getattr(self, "_preset_admin", False) else "private",
            )
        except ValueError as exc:
            code, message = str(exc).split(":", 1) if ":" in str(exc) else ("TEMPLATE_INVALID", str(exc))
            self._json_error(code, message.strip(), 400)
            return
        extra_headers = []
        if getattr(self, "_preset_cookie_header", ""):
            extra_headers.append(("Set-Cookie", self._preset_cookie_header))
        self._json(preset, 201, extra_headers=extra_headers or None)

    def _handle_preset_update(self, preset_id: str):
        payload = getattr(self, "_request_params_cache", {})
        try:
            preset = _update_preset(
                preset_id,
                payload.get("name", ""),
                payload.get("description", ""),
                payload.get("config_json", {}),
                owner_id=getattr(self, "_preset_owner_id", ""),
                public_only=getattr(self, "_preset_public_only", True),
            )
        except ValueError as exc:
            code, message = str(exc).split(":", 1) if ":" in str(exc) else ("TEMPLATE_INVALID", str(exc))
            status = 404 if code == "TEMPLATE_NOT_FOUND" else 400
            self._json_error(code, message.strip(), status)
            return
        extra_headers = []
        if getattr(self, "_preset_cookie_header", ""):
            extra_headers.append(("Set-Cookie", self._preset_cookie_header))
        self._json(preset, extra_headers=extra_headers or None)

    def _handle_preset_delete(self, preset_id: str):
        try:
            result = _delete_preset(
                preset_id,
                owner_id=getattr(self, "_preset_owner_id", ""),
                public_only=getattr(self, "_preset_public_only", True),
            )
        except ValueError as exc:
            code, message = str(exc).split(":", 1) if ":" in str(exc) else ("TEMPLATE_INVALID", str(exc))
            status = 404 if code == "TEMPLATE_NOT_FOUND" else 400
            self._json_error(code, message.strip(), status)
            return
        extra_headers = []
        if getattr(self, "_preset_cookie_header", ""):
            extra_headers.append(("Set-Cookie", self._preset_cookie_header))
        self._json(result, 200, extra_headers=extra_headers or None)

    def _handle_log(self, task_id: str):
        if not _is_safe_uuid(task_id):
            self._json_error("INVALID_TASK_ID", "无效的任务 ID", 400)
            return
        path = ""
        with TASKS_LOCK:
            task = TASKS.get(task_id)
            if task:
                filename = task.get("log_filename", "")
                if filename:
                    path = os.path.join(LOG_DIR, filename)
        with _SQL_LOCK:
            conn = _sql()
            row = conn.execute(
                """SELECT filename, status, duration_ms, error_code, error_message,
                          created_at, log_path
                   FROM tasks WHERE id=?""",
                (task_id,),
            ).fetchone()
            conn.close()
        if not path:
            path = row["log_path"] if row else ""
        if not path:
            self._json_error("LOG_NOT_FOUND", "日志不存在", 404)
            return
        root = os.path.abspath(LOG_DIR)
        path = os.path.abspath(path)
        if not path.startswith(root + os.sep) or not os.path.exists(path):
            self._json_error("LOG_NOT_FOUND", "日志不存在或已过期", 404)
            return
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            log_text = _redact_sensitive_log(f.read())
        filename = _html_escape(row["filename"] if row else "-")
        status = _html_escape(row["status"] if row else "-")
        duration = ((row["duration_ms"] or 0) / 1000) if row else 0
        error_code = _html_escape(row["error_code"] if row else "") or "-"
        created_at = _html_escape(row["created_at"] if row else "-")
        escaped_log = _html_escape(log_text)
        body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>任务日志 · {filename}</title><style>
:root{{--bg:#07101f;--panel:#0d1a2e;--line:rgba(160,181,215,.17);--text:#edf4ff;--muted:#8fa2be;--gold:#f6c85f;--red:#fb7185}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","Noto Sans CJK SC","PingFang SC",sans-serif}}.page{{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:22px 0 36px}}.topbar{{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;padding-bottom:17px;border-bottom:1px solid var(--line)}}.eyebrow{{color:var(--gold);font-size:10px;letter-spacing:.12em;margin-bottom:5px}}h1{{font-size:20px;margin:0;max-width:780px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.actions{{display:flex;gap:8px}}.btn{{height:34px;padding:0 11px;border:1px solid var(--line);border-radius:7px;background:rgba(255,255,255,.04);color:#b9c9df;font-size:11px;display:inline-flex;align-items:center;cursor:pointer;text-decoration:none}}.btn:hover{{border-color:rgba(246,200,95,.4);color:#ffe7a4}}.meta{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:18px 0}}.meta div{{padding:13px;border:1px solid var(--line);border-radius:9px;background:var(--panel)}}.meta span{{display:block;color:var(--muted);font-size:10px;margin-bottom:5px}}.meta b{{font-size:13px;font-weight:650}}.log-panel{{border:1px solid var(--line);border-radius:11px;overflow:hidden;background:#050d19}}.log-head{{padding:12px 15px;border-bottom:1px solid var(--line);color:#9eb1cb;font-size:11px}}pre{{margin:0;padding:18px;min-height:360px;overflow:auto;color:#c9d8eb;font:12px/1.75 Consolas,"Noto Sans Mono CJK SC",monospace;white-space:pre-wrap;word-break:break-word}}@media(max-width:700px){{.topbar{{flex-direction:column}}.meta{{grid-template-columns:1fr 1fr}}h1{{white-space:normal}}}}
</style></head><body><main class="page"><header class="topbar"><div><div class="eyebrow">TASK LOG / {_html_escape(task_id)}</div><h1>{filename}</h1></div><div class="actions"><a class="btn" href="/monitor#tasks">返回工作台</a><button class="btn" type="button" onclick="navigator.clipboard.writeText(document.getElementById('taskLog').textContent).then(()=>this.textContent='已复制')">复制日志</button></div></header><section class="meta"><div><span>任务状态</span><b>{status}</b></div><div><span>创建时间</span><b>{created_at}</b></div><div><span>处理耗时</span><b>{duration:.1f}s</b></div><div><span>错误码</span><b>{error_code}</b></div></section><section class="log-panel"><div class="log-head">日志内容 · 已自动隐藏敏感认证字段</div><pre id="taskLog">{escaped_log}</pre></section></main></body></html>"""
        self._text(body, "text/html")

    def _text(self, body: str, mime: str, status: int = 200, extra_headers=None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if extra_headers:
            if isinstance(extra_headers, dict):
                items = extra_headers.items()
            else:
                items = extra_headers
            for key, value in items:
                self.send_header(key, value)
        self._set_cors_headers()
        self._set_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj: dict, status: int = 200, extra_headers=None):
        data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if extra_headers:
            if isinstance(extra_headers, dict):
                items = extra_headers.items()
            else:
                items = extra_headers
            for key, value in items:
                self.send_header(key, value)
        self._set_cors_headers()
        self._set_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _json_error(self, code: str, message: str, status: int, *, field: str = "", reason: str = "", retry_after: int = 0):
        headers = [("Retry-After", str(retry_after))] if retry_after else None
        if _route_path(urlparse(self.path).path).startswith("/auth/"):
            error = {"code": code, "message": message}
            if field:
                error["field"] = field
            if reason:
                error["reason"] = reason
            self._json({"ok": False, "error": error}, status, extra_headers=headers)
            return
        self._json(_error_payload(code, message, field=field, reason=reason), status, extra_headers=headers)

    def log_message(self, fmt, *args):
        pass


def main():
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print("Usage: python server.py")
        print("   or: python -m docxtool")
        print("Configure ADMIN_TOKEN and PROXY_SECRET before starting the service.")
        return
    _validate_secrets_or_exit()
    _startup_cleanup()
    _sql_init()
    _recover_inflight_tasks_on_startup()
    _ensure_workers_started()
    server = ThreadingHTTPServer(_server_bind_address(), Handler)
    server.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    urls = _startup_urls()
    print(f"排版工具:   {urls['tool']}")
    print(f"管理员登录: {urls['admin_login']}")
    print(f"监控面板:   登录后访问 {urls['monitor']}")
    print("鉴权配置:   ADMIN_TOKEN 已设置 | PROXY_SECRET 已设置")
    print(f"线程池: {MAX_WORKERS} | 队列: {MAX_QUEUE} | 上限: {MAX_SIZE//1048576}MB")
    print(f"限流: {RATE_WINDOW}s/IP | 文件TTL: {FILE_TTL}s")
    for line in _startup_time_check_lines():
        print(line)
    print("外网访问:   Cloudflare Pages /api/* -> Nginx 80 -> 127.0.0.1:9527")
    print("Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()

if __name__ == "__main__":
    main()
