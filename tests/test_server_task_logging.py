import os
import tempfile
import unittest
import uuid
from pathlib import Path

from docx import Document

from docxtool.web import app as server


class ServerTaskLoggingTest(unittest.TestCase):
    def test_task_records_clickable_log_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            server._DB_PATH = str(tmp / "stats.db")
            server.LOG_DIR = str(tmp / "logs")
            server.OUTPUT_DIR = str(tmp / "outputs")
            os.makedirs(server.LOG_DIR, exist_ok=True)
            os.makedirs(server.OUTPUT_DIR, exist_ok=True)
            server.TASKS.clear()
            server._sql_init()

            source = tmp / "source.docx"
            doc = Document()
            doc.add_paragraph("测试正文测试正文测试正文。")
            doc.save(source)

            task_id = str(uuid.uuid4())
            server.TASKS[task_id] = {"status": "processing"}
            server._process_task(task_id, str(source), "测试文件.docx", "127.0.0.1", "unittest")

            task = server.TASKS[task_id]
            self.assertEqual(task["status"], "done")
            self.assertEqual(task["log_url"], f"/log/{task_id}")
            self.assertTrue(task["log_filename"].endswith(f"_{task_id[:8]}.log"))

            log_path = Path(server.LOG_DIR) / task["log_filename"]
            self.assertTrue(log_path.exists())
            self.assertIn(task_id[:8], log_path.read_text(encoding="utf-8"))

            conn = server._sql()
            row = conn.execute(
                "SELECT log_filename, log_path FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            conn.close()
            self.assertEqual(row["log_filename"], task["log_filename"])
            self.assertEqual(Path(row["log_path"]), log_path)


if __name__ == "__main__":
    unittest.main()
