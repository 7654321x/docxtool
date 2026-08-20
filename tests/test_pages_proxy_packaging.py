import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PagesProxyPackagingTest(unittest.TestCase):
    def test_pages_directory_is_authoritative_frontend(self):
        frontend = ROOT / "resources" / "frontend"
        pages = frontend / "pages"

        self.assertTrue((pages / "index.html").exists(), "resources/frontend/pages/index.html should be the production page")
        self.assertTrue((pages / "_worker.js").exists(), "resources/frontend/pages/_worker.js should be the production Worker")
        self.assertFalse((frontend / "legacy").exists(), "legacy frontend should be removed from the published tree")

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
        self.assertNotIn("CF_ACCESS_CLIENT_ID", text)
        self.assertNotIn("CF_ACCESS_CLIENT_SECRET", text)
        self.assertIn("shouldProxyPath", text)
        self.assertIn("isAdminProxyPath", text)
        self.assertIn("/api/upload", text)
        self.assertIn("/monitor", text)
        self.assertIn("/admin/login", text)
        self.assertIn("/wps-api/v1/auth/login", text)
        self.assertIn("/ban", text)
        self.assertIn("env.ASSETS.fetch(request)", text)
        self.assertIn('"X-Admin-Token"', text)
        self.assertIn('"CF-Connecting-IP"', text)
        self.assertIn('"X-Forwarded-For"', text)
        self.assertIn('"CF-Access-Client-Id"', text)
        self.assertIn('"CF-Access-Client-Secret"', text)
        self.assertNotIn('headers.set("CF-Access-Client-Id"', text)
        self.assertNotIn('headers.set("CF-Access-Client-Secret"', text)

    def test_pages_frontend_uses_same_origin_api(self):
        html = (ROOT / "resources" / "frontend" / "pages" / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("trycloudflare.com", html)
        self.assertIn("const API_PREFIX = '/api'", html)

    def test_publish_script_uses_pages_manifest_and_push_default(self):
        script = (ROOT / "scripts" / "publish_to_github.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$DryRun", script)
        self.assertIn("[switch]$Verify", script)
        self.assertIn("Mode: $(if ($DryRun) { 'dry-run' } else { 'push' })", script)
        self.assertIn("if ($DryRun)", script)
        self.assertIn("No commit was created and nothing was pushed", script)
        self.assertIn('Invoke-Checked git @("commit", "-m", $CommitMessage)', script)
        self.assertIn('Invoke-Checked git @("push", "origin", "HEAD:$Branch")', script)
        self.assertIn("Push verification failed", script)
        self.assertIn("if ($Verify)", script)
        self.assertIn("git restore --staged", script)
        self.assertNotIn("--force", script)
        self.assertNotIn("--force-with-lease", script)
        self.assertIn("Local Git baseline mismatch", script)
        self.assertIn("Staged local publish changes", script)
        self.assertNotIn('git @("clone"', script)
        self.assertIn("Get-ChangedFiles", script)
        self.assertIn("core.quotePath=false", script)
        self.assertIn("ls-files --others --exclude-standard", script)
        self.assertIn('Invoke-Checked git @("add", "-A",', script)
        self.assertIn("Publish staging omitted working-tree changes", script)
        self.assertIn('"scripts/verify_changed.ps1", "-SkipPublishDryRun"', script)
        self.assertNotIn("pull --rebase", script)
        self.assertIn('(^|/)\\.env(\\.|$)', script)
        self.assertIn('\\.(pem|key|db|sqlite|sqlite3|log|zip|exe|whl|docx)$', script)
        self.assertIn("git@github.com:7654321x/docxtool.git", script)
        self.assertIn('Write-Host "Commit SHA:', script)
        self.assertIn('Write-Host "Working tree clean: true"', script)

    def test_ci_builds_python_package(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("python -m pytest", workflow)
        self.assertIn("python -m ruff check src tests scripts", workflow)
        self.assertIn("node --test tests/worker-routing.test.mjs", workflow)
        self.assertIn("python -m pip install --require-hashes -r requirements-dev.lock", workflow)
        self.assertIn("python -m build", workflow)


if __name__ == "__main__":
    unittest.main()
