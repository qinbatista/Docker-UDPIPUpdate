import os
import tempfile
import unittest
from unittest.mock import patch

try:
    from Client.UDPClient import UDPClient
except ModuleNotFoundError:
    from UDPClient import UDPClient


class TestUDPClientDNSIP(unittest.TestCase):
    DNS_IP = "8.8.4.4"
    PUBLIC_IP = "1.1.1.1"
    ROUTER_IP = "9.9.9.9"
    PUBLIC_FALLBACK_IP = "208.67.222.222"

    class MockResponse:
        def __init__(self, text, status_code=200, payload=None):
            self.text = text
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception(f"http {self.status_code}")

        def json(self):
            if self._payload is not None:
                return self._payload
            raise ValueError("no json payload")

    def _build_client(self):
        log_file = tempfile.NamedTemporaryFile(delete=False).name
        with patch.object(UDPClient, "_select_update_ip", return_value="0.0.0.0"):
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

    def _requests_get_patch_target(self):
        return f"{UDPClient.__module__}.requests.get"

    def test_get_dns_client_ip_returns_global_dns_ip(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        with patch(self._getaddrinfo_patch_target(), return_value=[(None, None, None, None, (self.DNS_IP, 0))]):
            self.assertEqual(client._get_dns_client_ip(), (self.DNS_IP, "ok"))

    def test_get_dns_client_ip_returns_non_global_status(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        with patch(self._getaddrinfo_patch_target(), return_value=[(None, None, None, None, ("198.18.2.112", 0))]):
            self.assertEqual(client._get_dns_client_ip(), ("0.0.0.0", "non_global_dns_ip"))

    def test_get_dns_client_ip_returns_fail_on_resolve_error(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        with patch(self._getaddrinfo_patch_target(), side_effect=Exception("dns down")):
            self.assertEqual(client._get_dns_client_ip(), ("0.0.0.0", "fail"))

    def test_select_update_ip_prefers_public_ip(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        with patch.object(client, "_get_public_client_ip", return_value=(self.PUBLIC_IP, "https://api.ipify.org")), patch.object(client, "_get_dns_client_ip", return_value=(self.DNS_IP, "ok")):
            self.assertEqual(client._select_update_ip(), self.PUBLIC_IP)
            self.assertEqual(client._last_ip_source, "https://api.ipify.org")

    def test_select_update_ip_falls_back_to_dns_ip(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        with patch.object(client, "_get_public_client_ip", return_value=("0.0.0.0", "public:none")), patch.object(client, "_get_dns_client_ip", return_value=(self.DNS_IP, "ok")):
            self.assertEqual(client._select_update_ip(), self.DNS_IP)
            self.assertEqual(client._last_ip_source, "dns:client.example.com")

    def test_get_public_client_ip_returns_zero_when_all_lookups_fail(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        with patch(self._requests_get_patch_target(), side_effect=Exception("network down")):
            self.assertEqual(client._get_public_client_ip(), ("0.0.0.0", "public:none"))

    def test_get_router_wan_ip_from_plain_text(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._wan_ip_source_url = "http://router.local/wan-ip"
        with patch(self._requests_get_patch_target(), return_value=self.MockResponse(self.ROUTER_IP)):
            self.assertEqual(client._get_router_wan_ip(), (self.ROUTER_IP, "http://router.local/wan-ip"))

    def test_get_router_wan_ip_from_json_key(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._wan_ip_source_url = "http://router.local/wan-ip"
        with patch(self._requests_get_patch_target(), return_value=self.MockResponse("{\"wan_ip\":\"9.9.9.9\"}", payload={"wan_ip": self.ROUTER_IP})):
            self.assertEqual(client._get_router_wan_ip(), (self.ROUTER_IP, "http://router.local/wan-ip"))

    def test_select_update_ip_prefers_router_when_configured(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._wan_ip_source_url = "http://router.local/wan-ip"
        with patch.object(client, "_get_router_wan_ip", return_value=(self.ROUTER_IP, "http://router.local/wan-ip")), patch.object(client, "_get_dns_client_ip", return_value=(self.DNS_IP, "ok")):
            self.assertEqual(client._select_update_ip(), self.ROUTER_IP)
            self.assertEqual(client._last_ip_source, "router:http://router.local/wan-ip")

    def test_select_update_ip_router_fallback_to_public_when_router_unavailable(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._wan_ip_source_url = "http://router.local/wan-ip"
        with patch.object(client, "_get_router_wan_ip", return_value=("0.0.0.0", "http://router.local/wan-ip")), patch.object(client, "_get_dns_client_ip", return_value=(self.DNS_IP, "ok")), patch.object(client, "_get_public_client_ip", return_value=(self.PUBLIC_FALLBACK_IP, "https://ifconfig.me/ip")):
            self.assertEqual(client._select_update_ip(), self.PUBLIC_FALLBACK_IP)
            self.assertEqual(client._last_ip_source, "https://ifconfig.me/ip")

    def test_select_update_ip_router_then_public_then_dns(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._wan_ip_source_url = "http://router.local/wan-ip"
        with patch.object(client, "_get_router_wan_ip", return_value=("0.0.0.0", "http://router.local/wan-ip")), patch.object(client, "_get_public_client_ip", return_value=("0.0.0.0", "public:none")), patch.object(client, "_get_dns_client_ip", return_value=(self.DNS_IP, "ok")):
            self.assertEqual(client._select_update_ip(), self.DNS_IP)
            self.assertEqual(client._last_ip_source, "dns:client.example.com")

    def test_select_update_ip_router_required_blocks_public_fallback(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._wan_ip_source_url = "http://router.local/wan-ip"
        client._wan_ip_source_required = True
        with patch.object(client, "_get_router_wan_ip", return_value=("0.0.0.0", "http://router.local/wan-ip")), patch.object(client, "_get_public_client_ip", return_value=(self.PUBLIC_FALLBACK_IP, "https://ifconfig.me/ip")), patch.object(client, "_get_dns_client_ip", return_value=(self.DNS_IP, "ok")):
            self.assertEqual(client._select_update_ip(), "0.0.0.0")
            self.assertEqual(client._last_ip_source, "router_failed:http://router.local/wan-ip")

    def test_default_public_ip_services_match_shadowrocket_direct_rules(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        self.assertEqual(client._ipv4_services, ["https://ifconfig.me/ip", "https://icanhazip.com", "https://api.ip.sb/ip"])

    def test_public_ip_services_rotate_round_robin(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        client._ipv4_services = ["u1", "u2", "u3"]
        self.assertEqual(client._public_ip_services_round_robin(), ["u1", "u2", "u3"])
        self.assertEqual(client._public_ip_services_round_robin(), ["u2", "u3", "u1"])
        self.assertEqual(client._public_ip_services_round_robin(), ["u3", "u1", "u2"])

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

    def test_update_log_has_no_send_field(self):
        client, log_file = self._build_client()
        self._remember_temp(log_file)
        message = client._format_update_log(self.DNS_IP, "connected(timov4.qinyupeng.com@54.249.229.136)", "https://api.ipify.org")
        self.assertEqual(message, f"[client={self.DNS_IP}(source=https://api.ipify.org)] [domain=client.example.com@{self.DNS_IP}] [connectivity=connected(timov4.qinyupeng.com@54.249.229.136)]||")


if __name__ == "__main__":
    unittest.main()
