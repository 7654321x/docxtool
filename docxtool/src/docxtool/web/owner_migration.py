"""匿名 owner 资源迁移辅助。"""

from __future__ import annotations

import re
from typing import Any, Callable


def is_anonymous_owner_id(value: str) -> bool:
    """传入 owner ID 字符串，返回它是否符合匿名用户 ID 形态。"""
    return bool(re.fullmatch(r"usr_[0-9a-f]{32}", str(value or "")))


def migrate_anonymous_owner(conn, anonymous_id: str, user_id: str) -> None:
    """传入已开启事务的连接、匿名 ID 和用户 ID，将匿名任务/私人模板归属迁移给用户。"""
    if not is_anonymous_owner_id(anonymous_id):
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


def migrate_anonymous_resources(
    anonymous_id: str,
    user_id: str,
    *,
    connect: Callable[[], Any],
    sql_lock,
) -> None:
    """传入匿名 ID、用户 ID 和数据库依赖，开启事务并迁移该匿名 owner 的资源。"""
    with sql_lock:
        conn = connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            migrate_anonymous_owner(conn, anonymous_id, user_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
