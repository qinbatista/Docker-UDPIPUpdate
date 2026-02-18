import os
import tempfile
import unittest
from unittest.mock import patch

try:
    from Client.UDPClient import UDPClient
except ModuleNotFoundError:
    from UDPClient import UDPClient


class TestUDPClientDNSIP(unittest.TestCase):
    def _build_client(self):
        log_file = tempfile.NamedTemporaryFile(delete=False).name
        with patch.object(UDPClient, "_get_dns_client_ip", return_value=("0.0.0.0", "fail")):
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

    def _getaddrinfo_patch_target(self):
        return f"{UDPClient.__module__}.socket.getaddrinfo"

    def test_get_dns_client_ip_returns_global_dns_ip(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        with patch(self._getaddrinfo_patch_target(), return_value=[(None, None, None, None, ("14.110.98.236", 0))]):
            self.assertEqual(client._get_dns_client_ip(), ("14.110.98.236", "ok"))

    def test_get_dns_client_ip_returns_non_global_status(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        with patch(self._getaddrinfo_patch_target(), return_value=[(None, None, None, None, ("10.0.0.8", 0))]):
            self.assertEqual(client._get_dns_client_ip(), ("0.0.0.0", "non_global_dns_ip"))

    def test_get_dns_client_ip_returns_fail_on_resolve_error(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        with patch(self._getaddrinfo_patch_target(), side_effect=Exception("dns down")):
            self.assertEqual(client._get_dns_client_ip(), ("0.0.0.0", "fail"))

    def test_connectivity_turns_off_after_three_failures(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._can_connect = 1
        client._connect_fail_threshold = 3
        self.assertEqual(client._next_connectivity_state(0), 1)
        self.assertEqual(client._next_connectivity_state(0), 1)
        self.assertEqual(client._next_connectivity_state(0), 0)
        self.assertEqual(client._connect_fail_count, 3)

    def test_connectivity_failure_count_resets_on_success(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._can_connect = 1
        client._connect_fail_threshold = 3
        client._next_connectivity_state(0)
        client._next_connectivity_state(0)
        self.assertEqual(client._connect_fail_count, 2)
        self.assertEqual(client._next_connectivity_state(1), 1)
        self.assertEqual(client._connect_fail_count, 0)

    def test_connectivity_text_shows_disconnect_progress(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._can_connect = 0
        client._disconnect_window_seconds = 300
        client._disconnect_start_time = 1000
        with patch(f"{UDPClient.__module__}.time.time", return_value=1005):
            self.assertEqual(client._format_connectivity_text(), "disconnected(5/300)")

    def test_connectivity_text_connected_shows_target(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._can_connect = 1
        client._connected_server = "timov4.qinyupeng.com"
        client._connected_server_ip = "54.249.229.136"
        self.assertEqual(client._format_connectivity_text(), "connected(timov4.qinyupeng.com@54.249.229.136)")

    def test_update_log_hides_send_when_success(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        message = client._format_update_log("14.110.98.236", "connected(timov4.qinyupeng.com@54.249.229.136)", "success")
        self.assertEqual(message, "[client=14.110.98.236] [domain=client.example.com@14.110.98.236] [connectivity=connected(timov4.qinyupeng.com@54.249.229.136)]||")

    def test_update_log_keeps_send_when_failed(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        message = client._format_update_log("14.110.98.236", "disconnected(5/300)", "1/3 failed")
        self.assertEqual(message, "[client=14.110.98.236] [domain=client.example.com@14.110.98.236] [connectivity=disconnected(5/300)] [send=1/3 failed]||")


if __name__ == "__main__":
    unittest.main()
