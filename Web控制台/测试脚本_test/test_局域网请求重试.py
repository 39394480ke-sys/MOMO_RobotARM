"""局域网客户端短暂抖动时，请求应先重试再提示错误。"""

from pathlib import Path
import unittest


WEB_ROOT = Path(__file__).resolve().parents[1]


class LanRequestRetryTest(unittest.TestCase):
    def test_get_requests_retry_once_with_a_longer_default_timeout(self) -> None:
        app = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

        self.assertIn('const timeout = options.timeout ?? 10000;', app)
        self.assertIn('method === "GET" ? 1 : 0', app)
        self.assertIn('error.name === "AbortError" || error instanceof TypeError', app)

    def test_frontend_cache_key_includes_lan_retry_release(self) -> None:
        index = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

        self.assertIn("lan-retry", index)


if __name__ == "__main__":
    unittest.main()
