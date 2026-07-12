import unittest

import server


class ClientIpTest(unittest.TestCase):
    def test_prefers_ipv4_from_forwarded_chain(self):
        headers = {
            "CF-Connecting-IP": "240e:398:41bb:c470:392d:4351:2b3f:b7c",
            "X-Forwarded-For": "240e:398:41bb:c470:392d:4351:2b3f:b7c, 203.0.113.8",
            "X-Real-IP": "198.51.100.9",
        }

        self.assertEqual(server._client_ip(headers, ("127.0.0.1", 12345)), "203.0.113.8")

    def test_falls_back_to_ipv6_when_no_ipv4_exists(self):
        headers = {"CF-Connecting-IP": "240e:398:41bb:c470:392d:4351:2b3f:b7c"}

        self.assertEqual(
            server._client_ip(headers, ("::1", 12345)),
            "240e:398:41bb:c470:392d:4351:2b3f:b7c",
        )

    def test_ignores_spoofed_headers_from_untrusted_clients(self):
        headers = {
            "CF-Connecting-IP": "203.0.113.8",
            "X-Forwarded-For": "198.51.100.9",
            "X-Real-IP": "192.0.2.7",
        }

        self.assertEqual(server._client_ip(headers, ("203.0.113.77", 12345)), "203.0.113.77")


if __name__ == "__main__":
    unittest.main()
