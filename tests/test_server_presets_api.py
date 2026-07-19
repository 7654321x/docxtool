import http.client
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from docxtool.web import app as server


class ServerPresetsApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_db = server._DB_PATH
        self.old_log_dir = server.LOG_DIR
        self.old_output_dir = server.OUTPUT_DIR
        self.old_production_mode = server.PRODUCTION_MODE
        server.PRODUCTION_MODE = False
        server._DB_PATH = str(root / "stats.db")
        server.LOG_DIR = str(root / "logs")
        server.OUTPUT_DIR = str(root / "outputs")
        os.makedirs(server.LOG_DIR, exist_ok=True)
        os.makedirs(server.OUTPUT_DIR, exist_ok=True)
        server._sql_init()

    def tearDown(self):
        server._DB_PATH = self.old_db
        server.LOG_DIR = self.old_log_dir
        server.OUTPUT_DIR = self.old_output_dir
        server.PRODUCTION_MODE = self.old_production_mode
        self.tmp.cleanup()

    def test_default_preset_is_seeded_and_readable(self):
        presets = server._list_presets()
        self.assertGreaterEqual(len(presets), 1)
        system = next((p for p in presets if p["id"] == "official_document"), None)
        self.assertIsNotNone(system)
        self.assertTrue(system["is_system"])
        self.assertTrue(system["is_default"])

        detail = server._get_preset("official_document")
        self.assertEqual(detail["name"], "党政机关公文格式")
        self.assertIn("styles", detail["config_json"])
        self.assertIn("page", detail["config_json"])

    def test_insert_update_and_delete_user_preset(self):
        config = server._default_preset_config()
        created = server._insert_preset("我的模板", "测试模板", config, preset_id="my-template")
        self.assertEqual(created["id"], "my-template")
        self.assertEqual(created["version"], 1)

        updated = server._update_preset("my-template", "我的模板 v2", "已更新", config)
        self.assertEqual(updated["name"], "我的模板 v2")
        self.assertEqual(updated["version"], 2)

        deleted = server._delete_preset("my-template")
        self.assertTrue(deleted["deleted"])
        self.assertEqual(server._get_preset("my-template"), {})

    def test_system_preset_cannot_be_deleted(self):
        with self.assertRaises(ValueError):
            server._delete_preset("official_document")

    def test_duplicate_preset_name_is_rejected(self):
        config = server._default_preset_config()
        server._insert_preset("模板A", "测试", config, preset_id="template-a")
        with self.assertRaises(ValueError):
            server._insert_preset("模板A", "重复", config, preset_id="template-b")

    def test_anonymous_cookie_is_signed_and_expires(self):
        identity = server._create_anonymous_user(now=1000)
        parsed = server._parse_anonymous_user(identity["token"], now=1001)
        self.assertEqual(parsed["owner_id"], identity["owner_id"])
        self.assertEqual(server._parse_anonymous_user(identity["token"][:-1] + "x", now=1001), {})
        self.assertEqual(
            server._parse_anonymous_user(identity["token"], now=1000 + server.ANONYMOUS_USER_COOKIE_MAX_AGE + 1),
            {},
        )
        cookie = server._anonymous_user_cookie_header(identity["token"])
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Max-Age=", cookie)
        self.assertNotIn(identity["owner_id"], cookie.split(";", 1)[0].split("=", 1)[0])

    def test_private_templates_are_isolated_by_owner(self):
        config = server._default_preset_config()
        owner_a = server._create_anonymous_user(now=2000)["owner_id"]
        owner_b = server._create_anonymous_user(now=2000)["owner_id"]
        created = server._insert_preset(
            "个人模板", "仅用户 A", config, owner_id=owner_a, visibility="private", preset_id="private-a"
        )
        self.assertEqual(created["visibility"], "private")
        self.assertEqual([p["id"] for p in server._list_presets(owner_a)].count("private-a"), 1)
        self.assertEqual([p["id"] for p in server._list_presets(owner_b)].count("private-a"), 0)
        self.assertEqual(server._get_preset("private-a", owner_id=owner_b), {})
        with self.assertRaises(ValueError):
            server._update_preset("private-a", "被越权修改", "", config, owner_id=owner_b, public_only=False)
        with self.assertRaises(ValueError):
            server._delete_preset("private-a", owner_id=owner_b, public_only=False)
        self.assertEqual(
            server._update_preset("private-a", "个人模板 v2", "", config, owner_id=owner_a, public_only=False)["name"],
            "个人模板 v2",
        )

    def test_old_presets_schema_migrates_without_losing_templates(self):
        old_db = server._DB_PATH
        legacy_path = Path(self.tmp.name) / "legacy.db"
        conn = sqlite3.connect(legacy_path)
        try:
            conn.execute(
                """CREATE TABLE presets (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
                    config_json TEXT NOT NULL, is_system INTEGER DEFAULT 0,
                    is_default INTEGER DEFAULT 0, version INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT '', updated_at TEXT DEFAULT ''
                )"""
            )
            conn.execute(
                "INSERT INTO presets (id,name,config_json) VALUES (?,?,?)",
                ("legacy", "旧模板", json.dumps(server._default_preset_config(), ensure_ascii=False)),
            )
            conn.commit()
        finally:
            conn.close()
        server._DB_PATH = str(legacy_path)
        try:
            server._sql_init()
            conn = server._sql()
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(presets)").fetchall()}
            conn.close()
            self.assertIn("owner_id", columns)
            self.assertIn("visibility", columns)
            self.assertIn("legacy", {item["id"] for item in server._list_presets()})
        finally:
            server._DB_PATH = old_db

    def test_anonymous_preset_http_flow_is_isolated_and_origin_checked(self):
        old_origin = server.FRONTEND_ORIGIN
        server.FRONTEND_ORIGIN = ""
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        port = httpd.server_address[1]
        origin = f"http://127.0.0.1:{port}"

        def request(method, path, *, cookie="", body=None, request_origin=origin):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
            headers = {"Origin": request_origin}
            if cookie:
                headers["Cookie"] = cookie
            if payload is not None:
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(payload))
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            data = json.loads(response.read().decode("utf-8"))
            set_cookie = response.getheader("Set-Cookie", "")
            status = response.status
            conn.close()
            return status, data, set_cookie

        try:
            status, _, set_cookie_a = request("GET", "/presets")
            self.assertEqual(status, 200)
            cookie_a = set_cookie_a.split(";", 1)[0]
            self.assertTrue(cookie_a.startswith(server.ANONYMOUS_USER_COOKIE + "="))

            body = {
                "id": "owner-a-template",
                "name": "用户 A 模板",
                "description": "private",
                "config_json": server._default_preset_config(),
            }
            status, created, _ = request("POST", "/presets", cookie=cookie_a, body=body)
            self.assertEqual(status, 201)
            self.assertEqual(created["visibility"], "private")

            status, listed_a, _ = request("GET", "/presets", cookie=cookie_a)
            self.assertEqual(status, 200)
            self.assertIn("owner-a-template", {item["id"] for item in listed_a["presets"]})

            status, listed_b, set_cookie_b = request("GET", "/presets")
            self.assertEqual(status, 200)
            cookie_b = set_cookie_b.split(";", 1)[0]
            self.assertNotIn("owner-a-template", {item["id"] for item in listed_b["presets"]})

            status, _, _ = request("PUT", "/presets/owner-a-template", cookie=cookie_b, body=body)
            self.assertEqual(status, 404)
            status, payload, _ = request(
                "POST", "/presets", cookie=cookie_a, body={**body, "id": "cross-origin"},
                request_origin="https://attacker.example",
            )
            self.assertEqual(status, 403)
            self.assertEqual(payload["code"], "CSRF_INVALID")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
            server.FRONTEND_ORIGIN = old_origin


if __name__ == "__main__":
    unittest.main()
