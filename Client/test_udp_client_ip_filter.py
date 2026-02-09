import os
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from Client.UDPClient import UDPClient
except ModuleNotFoundError:
    from UDPClient import UDPClient


class MockResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"http {self.status_code}")


class TestUDPClientIPFilter(unittest.TestCase):
    def _build_client(self):
        log_file = tempfile.NamedTemporaryFile(delete=False).name
        with patch.object(UDPClient, "get_public_ip", return_value="0.0.0.0"):
            client = UDPClient("client.example.com", "server.example.com", log_file=log_file)
        return client, log_file

    def tearDown(self):
        for file_name in getattr(self, "_temp_files", []):
            try:
                os.remove(file_name)
            except OSError:
                pass

    def _remember_temp(self, file_name):
        if not hasattr(self, "_temp_files"):
            self._temp_files = []
        self._temp_files.append(file_name)

    def _requests_patch_target(self):
        return f"{UDPClient.__module__}.requests.get"

    def test_rejects_reserved_benchmark_ip(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)

        def fake_get(url, timeout=5):
            if url in client._ipv4_services:
                return MockResponse("198.18.2.112\n")
            raise Exception(f"unexpected url: {url}")

        with patch(self._requests_patch_target(), side_effect=fake_get):
            self.assertEqual(client.get_public_ip(), "0.0.0.0")

    def test_rejects_vpn_ip(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._vpn_ip_map = {"1.1.1.1": "timov4.qinyupeng.com"}
        client._vpn_ips_last_refresh = time.time()

        def fake_get(url, timeout=5):
            if url in client._ipv4_services:
                return MockResponse("1.1.1.1")
            raise Exception(f"unexpected url: {url}")

        with patch(self._requests_patch_target(), side_effect=fake_get):
            self.assertEqual(client.get_public_ip(), "0.0.0.0")

    def test_accepts_cn_public_ip(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._vpn_ips_last_refresh = time.time()

        def fake_get(url, timeout=5):
            if url in client._ipv4_services:
                return MockResponse("36.112.0.1")
            if "ipinfo.io/36.112.0.1/country" in url:
                return MockResponse("CN")
            return MockResponse("CN")

        with patch(self._requests_patch_target(), side_effect=fake_get):
            self.assertEqual(client.get_public_ip(), "36.112.0.1")

    def test_fallback_to_last_good_when_current_ip_non_cn(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._last_good_public_ip = "36.112.0.1"
        client._vpn_ips_last_refresh = time.time()

        def fake_get(url, timeout=5):
            if url in client._ipv4_services:
                return MockResponse("8.8.8.8")
            if "ipinfo.io/8.8.8.8/country" in url:
                return MockResponse("US")
            return MockResponse("US")

        with patch(self._requests_patch_target(), side_effect=fake_get):
            self.assertEqual(client.get_public_ip(), "36.112.0.1")


if __name__ == "__main__":
    unittest.main()
