import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PagesProxyPackagingTest(unittest.TestCase):
    def test_pages_worker_proxy_is_packaged(self):
        worker = ROOT / 'pages_dist' / '_worker.js'

        self.assertTrue(worker.exists(), 'pages_dist/_worker.js should proxy /api/* to the backend')
        text = worker.read_text(encoding='utf-8')
        self.assertIn('BACKEND_BASE_URL', text)
        self.assertIn('PROXY_SECRET', text)
        self.assertNotIn('DEFAULT_PROXY_SECRET', text)
        self.assertNotIn('docxtool-proxy-20260601-9ec0d6e2443a4f5f9784f0f04bb62917', text)
        self.assertIn('/api/upload', text)
        self.assertIn('env.ASSETS.fetch(request)', text)
        self.assertIn('"X-Admin-Token"', text)
        self.assertIn('"CF-Connecting-IP"', text)
        self.assertIn('"X-Forwarded-For"', text)

    def test_pages_frontend_uses_same_origin_api(self):
        html = (ROOT / 'pages_dist' / 'index.html').read_text(encoding='utf-8')

        self.assertNotIn('trycloudflare.com', html)
        self.assertIn("const API_PREFIX = '/api'", html)

    def test_pages_frontend_hides_unimplemented_and_removed_options(self):
        html = (ROOT / 'pages_dist' / 'index.html').read_text(encoding='utf-8')

        self.assertNotIn('正文上标', html)
        self.assertNotIn('表格优化', html)
        self.assertNotIn('<option>A3</option>', html)
        self.assertNotIn('<option>Letter</option>', html)


if __name__ == '__main__':
    unittest.main()
