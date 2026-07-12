import os
import tempfile
import unittest
from pathlib import Path

import server


class IpAdminTest(unittest.TestCase):
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

    def test_ban_and_unban_ip(self):
        self.assertFalse(server._is_ip_banned("203.0.113.8"))

        server._ban_ip("203.0.113.8", "测试封禁")
        self.assertTrue(server._is_ip_banned("203.0.113.8"))
        self.assertEqual(server._banned_ips()[0]["reason"], "测试封禁")

        server._unban_ip("203.0.113.8")
        self.assertFalse(server._is_ip_banned("203.0.113.8"))

    def test_ip_activity_and_window_count(self):
        server.log_sql("t1", "203.0.113.8", "ua", "a.docx", 100, "NORMAL", 3, 1, 2, 1200, "done")
        server.log_sql("t2", "203.0.113.8", "ua", "b.docx", 200, "NORMAL", 4, 1, 3, 1500, "error", "x")
        server.log_sql("t3", "198.51.100.2", "ua", "c.docx", 300, "NORMAL", 5, 1, 4, 1800, "done")

        activity = server._ip_activity("203.0.113.8")
        self.assertEqual([r["filename"] for r in activity], ["b.docx", "a.docx"])
        self.assertEqual(server._ip_upload_count("203.0.113.8", 3600), 2)

        stats = server.get_sql_stats()
        top = {r["ip"]: r for r in stats["top_ips"]}
        self.assertEqual(top["203.0.113.8"]["c"], 2)
        self.assertEqual(top["203.0.113.8"]["done"], 1)
        self.assertEqual(top["203.0.113.8"]["error"], 1)
        self.assertEqual(top["203.0.113.8"]["last_filename"], "b.docx")

    def test_upload_limit_settings_are_persisted(self):
        self.assertEqual(server._limit_settings(), {"enabled": False, "window_seconds": 3600, "count": 10})

        server._save_limit_settings(True, 1800, 5)
        self.assertEqual(server._limit_settings(), {"enabled": True, "window_seconds": 1800, "count": 5})

        server.log_sql("t1", "203.0.113.8", "ua", "a.docx", 100, "NORMAL", 3, 1, 2, 1200, "done")
        server.log_sql("t2", "203.0.113.8", "ua", "b.docx", 100, "NORMAL", 3, 1, 2, 1200, "done")
        server.log_sql("t3", "203.0.113.8", "ua", "c.docx", 100, "NORMAL", 3, 1, 2, 1200, "done")
        server.log_sql("t4", "203.0.113.8", "ua", "d.docx", 100, "NORMAL", 3, 1, 2, 1200, "done")
        server.log_sql("t5", "203.0.113.8", "ua", "e.docx", 100, "NORMAL", 3, 1, 2, 1200, "done")

        self.assertTrue(server._upload_limit_exceeded("203.0.113.8"))

        server._save_limit_settings(False, 1800, 5)
        self.assertFalse(server._upload_limit_exceeded("203.0.113.8"))

    def test_monitor_html_includes_upload_limit_form(self):
        server._save_limit_settings(True, 1800, 5)

        html = server._monitor_html(server.get_sql_stats())

        self.assertIn('action="/limit"', html)
        self.assertIn('name="window_seconds" value="1800"', html)
        self.assertIn('name="count" value="5"', html)
        self.assertIn('name="enabled" value="1" checked', html)


if __name__ == "__main__":
    unittest.main()
