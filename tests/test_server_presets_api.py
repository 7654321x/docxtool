import os
import tempfile
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


if __name__ == "__main__":
    unittest.main()
