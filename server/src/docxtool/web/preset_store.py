"""预设模板数据库读写辅助。"""

from __future__ import annotations

import re
import uuid
from typing import Any, Callable


def list_presets(
    owner_id: str = "",
    *,
    connect: Callable[[], Any],
    sql_lock,
    row_to_dict: Callable[[Any, bool], dict],
) -> list:
    """传入 owner ID、数据库依赖和行转换函数，返回该 owner 可见的预设模板列表。"""
    with sql_lock:
        conn = connect()
        try:
            rows = conn.execute(
                """SELECT id, name, description, is_system, is_default, visibility,
                          version, created_at, updated_at
                   FROM presets
                   WHERE is_system=1 OR visibility='public' OR (visibility='private' AND owner_id=?)
                   ORDER BY is_default DESC, is_system DESC, updated_at DESC, name ASC""",
                (owner_id or "",),
            ).fetchall()
        finally:
            conn.close()
    return [row_to_dict(row, False) for row in rows]


def get_preset(
    preset_id: str,
    owner_id: str = "",
    public_only: bool = False,
    *,
    connect: Callable[[], Any],
    sql_lock,
    row_to_dict: Callable[[Any, bool], dict],
) -> dict:
    """传入模板 ID、owner ID 和可见性限制，返回带配置的模板字典或空字典。"""
    with sql_lock:
        conn = connect()
        try:
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
        finally:
            conn.close()
    if not row:
        return {}
    return row_to_dict(row, True)


def insert_preset(
    name: str,
    description: str,
    config_json: dict,
    is_system: bool = False,
    is_default: bool = False,
    preset_id: str = "",
    owner_id: str = "",
    visibility: str = "public",
    *,
    connect: Callable[[], Any],
    sql_lock,
    normalize_id: Callable[[str], str],
    normalize_name: Callable[[str], str],
    validate_config: Callable[[dict], dict],
    json_dumps: Callable[[dict], str],
    now_func: Callable[[], str],
    get_one: Callable[[str, str, bool], dict],
) -> dict:
    """传入模板字段和数据库依赖，插入模板并返回新模板详情。"""
    preset_id = normalize_id(preset_id) if preset_id else f"tpl_{uuid.uuid4().hex[:12]}"
    name = normalize_name(name)
    normalized = validate_config(config_json)
    payload = json_dumps(normalized)
    visibility = "private" if visibility == "private" else "public"
    owner_id = str(owner_id or "").strip() if visibility == "private" else ""
    if visibility == "private" and not re.fullmatch(r"usr_[0-9a-f]{32}", owner_id):
        raise ValueError("TEMPLATE_OWNER_INVALID: 模板所有者无效")
    now = now_func()
    with sql_lock:
        conn = connect()
        try:
            row = conn.execute(
                """SELECT id FROM presets
                   WHERE lower(name)=lower(?) AND id<>? AND visibility=? AND owner_id=?""",
                (name, preset_id, visibility, owner_id),
            ).fetchone()
            if row:
                raise ValueError("TEMPLATE_NAME_CONFLICT: 已存在同名模板，请先重命名")
            existing = conn.execute("SELECT * FROM presets WHERE id=?", (preset_id,)).fetchone()
            if existing:
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
        finally:
            conn.close()
    return get_one(preset_id, owner_id, visibility == "public")


def update_preset(
    preset_id: str,
    name: str,
    description: str,
    config_json: dict,
    owner_id: str = "",
    public_only: bool = True,
    *,
    connect: Callable[[], Any],
    sql_lock,
    normalize_id: Callable[[str], str],
    normalize_name: Callable[[str], str],
    validate_config: Callable[[dict], dict],
    json_dumps: Callable[[dict], str],
    now_func: Callable[[], str],
    get_one: Callable[[str, str, bool], dict],
) -> dict:
    """传入模板 ID、更新字段和数据库依赖，更新模板并返回更新后的详情。"""
    preset_id = normalize_id(preset_id)
    name = normalize_name(name)
    normalized = validate_config(config_json)
    payload = json_dumps(normalized)
    now = now_func()
    with sql_lock:
        conn = connect()
        try:
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
                raise ValueError("TEMPLATE_NOT_FOUND: 模板不存在")
            dup = conn.execute(
                """SELECT id FROM presets
                   WHERE lower(name)=lower(?) AND id<>? AND visibility=? AND owner_id=?""",
                (name, preset_id, row["visibility"] or "public", row["owner_id"] or ""),
            ).fetchone()
            if dup:
                raise ValueError("TEMPLATE_NAME_CONFLICT: 已存在同名模板，请先重命名")
            version = int(row["version"] or 1) + 1
            conn.execute(
                """UPDATE presets SET
                   name=?, description=?, config_json=?, version=?, updated_at=?
                   WHERE id=?""",
                (name, description or "", payload, version, now, preset_id),
            )
            conn.commit()
        finally:
            conn.close()
    return get_one(preset_id, owner_id, public_only)


def delete_preset(
    preset_id: str,
    owner_id: str = "",
    public_only: bool = True,
    *,
    connect: Callable[[], Any],
    sql_lock,
    normalize_id: Callable[[str], str],
) -> dict:
    """传入模板 ID、owner ID 和可见性限制，删除允许删除的模板并返回删除结果。"""
    preset_id = normalize_id(preset_id)
    with sql_lock:
        conn = connect()
        try:
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
                raise ValueError("TEMPLATE_NOT_FOUND: 模板不存在")
            if row["is_system"]:
                raise ValueError("TEMPLATE_SYSTEM_LOCKED: 系统模板不能删除")
            conn.execute("DELETE FROM presets WHERE id=?", (preset_id,))
            conn.commit()
        finally:
            conn.close()
    return {"deleted": True, "id": preset_id}
