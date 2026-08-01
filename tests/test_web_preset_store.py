from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest

from docxtool.web.preset_config import normalize_template_id, normalize_template_name, preset_row_to_dict
from docxtool.web.preset_store import delete_preset, get_preset, insert_preset, list_presets, update_preset


OWNER_A = "usr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
OWNER_B = "usr_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


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
        CREATE TABLE presets(
            id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            config_json TEXT,
            is_system INTEGER DEFAULT 0,
            is_default INTEGER DEFAULT 0,
            owner_id TEXT DEFAULT '',
            visibility TEXT DEFAULT 'public',
            version INTEGER DEFAULT 1,
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        )
        """
    )
    conn.executemany(
        """INSERT INTO presets
           (id, name, description, config_json, is_system, is_default, owner_id, visibility, version, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [
            ("system", "系统模板", "", "{\"ok\":true}", 1, 1, "", "public", 1, "1", "1"),
            ("private-a", "个人模板", "", "{\"owner\":\"a\"}", 0, 0, OWNER_A, "private", 1, "2", "2"),
        ],
    )
    conn.commit()
    conn.close()


def _validate_config(config: dict) -> dict:
    """测试辅助：传入配置字典，返回带标记的可持久化配置。"""
    return {"normalized": True, **dict(config)}


def _json_dumps(config: dict) -> str:
    """测试辅助：传入配置字典，返回稳定 JSON 字符串。"""
    return json.dumps(config, ensure_ascii=False, separators=(",", ":"))


def _get_one_factory(connect, lock):
    def get_one(preset_id: str, owner_id: str, public_only: bool) -> dict:
        """测试辅助：传入模板 ID、owner 和可见性限制，返回模板详情。"""
        return get_preset(
            preset_id,
            owner_id,
            public_only,
            connect=connect,
            sql_lock=lock,
            row_to_dict=preset_row_to_dict,
        )

    return get_one


def test_list_and_get_presets_respect_owner_visibility() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "preset.db")
        _init_db(connect)
        lock = threading.Lock()

        visible_a = list_presets(OWNER_A, connect=connect, sql_lock=lock, row_to_dict=preset_row_to_dict)
        visible_b = list_presets(OWNER_B, connect=connect, sql_lock=lock, row_to_dict=preset_row_to_dict)
        private_for_a = get_preset("private-a", OWNER_A, False, connect=connect, sql_lock=lock, row_to_dict=preset_row_to_dict)
        private_for_b = get_preset("private-a", OWNER_B, False, connect=connect, sql_lock=lock, row_to_dict=preset_row_to_dict)

    assert {row["id"] for row in visible_a} == {"system", "private-a"}
    assert {row["id"] for row in visible_b} == {"system"}
    assert private_for_a["config_json"] == {"owner": "a"}
    assert private_for_b == {}


def test_insert_update_and_delete_private_preset() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "preset.db")
        _init_db(connect)
        lock = threading.Lock()
        get_one = _get_one_factory(connect, lock)

        created = insert_preset(
            " 新模板 ",
            "说明",
            {"x": 1},
            preset_id="new-template",
            owner_id=OWNER_A,
            visibility="private",
            connect=connect,
            sql_lock=lock,
            normalize_id=normalize_template_id,
            normalize_name=normalize_template_name,
            validate_config=_validate_config,
            json_dumps=_json_dumps,
            now_func=lambda: "10",
            get_one=get_one,
        )
        updated = update_preset(
            "new-template",
            "新模板 2",
            "更新",
            {"x": 2},
            owner_id=OWNER_A,
            public_only=False,
            connect=connect,
            sql_lock=lock,
            normalize_id=normalize_template_id,
            normalize_name=normalize_template_name,
            validate_config=_validate_config,
            json_dumps=_json_dumps,
            now_func=lambda: "11",
            get_one=get_one,
        )
        deleted = delete_preset(
            "new-template",
            owner_id=OWNER_A,
            public_only=False,
            connect=connect,
            sql_lock=lock,
            normalize_id=normalize_template_id,
        )

    assert created["name"] == "新模板"
    assert created["visibility"] == "private"
    assert created["config_json"]["normalized"] is True
    assert updated["name"] == "新模板 2"
    assert updated["version"] == 2
    assert deleted == {"deleted": True, "id": "new-template"}


def test_insert_rejects_invalid_owner_and_duplicate_name() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "preset.db")
        _init_db(connect)
        lock = threading.Lock()
        get_one = _get_one_factory(connect, lock)

        with pytest.raises(ValueError, match="TEMPLATE_OWNER_INVALID"):
            insert_preset(
                "私有",
                "",
                {},
                owner_id="invalid",
                visibility="private",
                connect=connect,
                sql_lock=lock,
                normalize_id=normalize_template_id,
                normalize_name=normalize_template_name,
                validate_config=_validate_config,
                json_dumps=_json_dumps,
                now_func=lambda: "1",
                get_one=get_one,
            )
        with pytest.raises(ValueError, match="TEMPLATE_NAME_CONFLICT"):
            insert_preset(
                "个人模板",
                "",
                {},
                preset_id="dup",
                owner_id=OWNER_A,
                visibility="private",
                connect=connect,
                sql_lock=lock,
                normalize_id=normalize_template_id,
                normalize_name=normalize_template_name,
                validate_config=_validate_config,
                json_dumps=_json_dumps,
                now_func=lambda: "1",
                get_one=get_one,
            )


def test_delete_rejects_system_preset() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        connect = _connect_factory(Path(tmp) / "preset.db")
        _init_db(connect)

        with pytest.raises(ValueError, match="TEMPLATE_SYSTEM_LOCKED"):
            delete_preset(
                "system",
                connect=connect,
                sql_lock=threading.Lock(),
                normalize_id=normalize_template_id,
            )
