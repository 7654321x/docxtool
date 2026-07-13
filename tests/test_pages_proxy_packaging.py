import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PagesProxyPackagingTest(unittest.TestCase):
    def test_pages_directory_is_authoritative_frontend(self):
        frontend = ROOT / "resources" / "frontend"
        pages = frontend / "pages"
        legacy = frontend / "legacy" / "index-before-restructure.html"

        self.assertTrue((pages / "index.html").exists(), "resources/frontend/pages/index.html should be the production page")
        self.assertTrue((pages / "_worker.js").exists(), "resources/frontend/pages/_worker.js should be the production Worker")
        self.assertTrue(legacy.exists(), "legacy page should remain available for audit comparison")

        production_entrypoints = [
            path.relative_to(frontend).as_posix()
            for path in frontend.rglob("*")
            if path.is_file() and path.name in {"index.html", "_worker.js"}
        ]
        self.assertEqual(
            sorted(production_entrypoints),
            [
                "pages/_worker.js",
                "pages/index.html",
            ],
        )

    def test_pages_worker_proxy_is_packaged(self):
        worker = ROOT / "resources" / "frontend" / "pages" / "_worker.js"

        self.assertTrue(worker.exists(), "resources/frontend/pages/_worker.js should proxy /api/* to the backend")
        text = worker.read_text(encoding="utf-8")
        self.assertIn("BACKEND_BASE_URL", text)
        self.assertIn("PROXY_SECRET", text)
        self.assertIn("shouldProxyPath", text)
        self.assertIn("isAdminProxyPath", text)
        self.assertIn("/api/upload", text)
        self.assertIn("/monitor", text)
        self.assertIn("/admin/login", text)
        self.assertIn("/ban", text)
        self.assertIn("env.ASSETS.fetch(request)", text)
        self.assertIn('"X-Admin-Token"', text)
        self.assertIn('"CF-Connecting-IP"', text)
        self.assertIn('"X-Forwarded-For"', text)

    def test_pages_frontend_uses_same_origin_api(self):
        html = (ROOT / "resources" / "frontend" / "pages" / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("trycloudflare.com", html)
        self.assertIn("const API_PREFIX = '/api'", html)

    def test_publish_script_uses_pages_manifest_and_dry_run_default(self):
        script = (ROOT / "scripts" / "publish_to_github.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$Push", script)
        self.assertIn("Mode: $(if ($Push) { 'push' } else { 'dry-run' })", script)
        self.assertIn("if (-not $Push)", script)
        self.assertIn("Dry run complete. Re-run with -Push", script)
        self.assertIn('Invoke-Checked git @("commit", "-m", $CommitMessage)', script)
        self.assertIn('Invoke-Checked git @("push", "origin", "HEAD:$Branch")', script)
        self.assertNotIn("--force", script)
        self.assertNotIn("--force-with-lease", script)
        self.assertIn("Remote $Branch changed after clone", script)
        self.assertIn('"resources/frontend/pages/index.html"', script)
        self.assertIn('"resources/frontend/pages/_worker.js"', script)
        self.assertIn('"resources/frontend/legacy/index-before-restructure.html"', script)
        self.assertNotIn('"resources/frontend/index.html"', script)
        self.assertIn('(^|/)\\.env(\\.|$)', script)
        self.assertIn('\\.(pem|key|db|sqlite|sqlite3|log|zip)$', script)
        self.assertIn('\\.docx$', script)

    def test_ci_builds_python_package(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("python -m pytest", workflow)
        self.assertIn("python -m ruff check src tests scripts", workflow)
        self.assertIn("node --test tests/worker-routing.test.mjs", workflow)
        self.assertIn("python -m pip install -r requirements.txt pytest ruff build", workflow)
        self.assertIn("python -m build", workflow)


if __name__ == "__main__":
    unittest.main()
