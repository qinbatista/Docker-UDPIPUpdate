import os
import tempfile
import unittest
from unittest.mock import patch

from UDPServer import UDPServer


class TestDomainUpdateDecision(unittest.TestCase):
    def setUp(self):
        fd, self.log_file = tempfile.mkstemp(prefix="udp_server_test_", suffix=".log")
        os.close(fd)

    def tearDown(self):
        try:
            os.remove(self.log_file)
        except OSError:
            pass

    @patch("UDPServer.LightSail")
    @patch("UDPServer.UDPServer.get_ipv4", return_value="1.2.3.4")
    @patch("UDPServer.UDPServer.get_ipv6", return_value="::1")
    @patch("UDPServer.getaddrinfo")
    def test_domain_points_to_ip_match(self, mock_getaddrinfo, mock_get_ipv6, mock_get_ipv4, mock_lightsail):
        mock_getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        server = UDPServer(log_file=self.log_file)
        try:
            dns_match, dns_ip, dns_status = server._domain_points_to_ip("demo.example.com", "8.8.8.8")
            self.assertTrue(dns_match)
            self.assertEqual(dns_ip, "8.8.8.8")
            self.assertEqual(dns_status, "match")
        finally:
            server.server_socket.close()

    @patch("UDPServer.LightSail")
    @patch("UDPServer.UDPServer.get_ipv4", return_value="1.2.3.4")
    @patch("UDPServer.UDPServer.get_ipv6", return_value="::1")
    @patch("UDPServer.getaddrinfo")
    def test_domain_points_to_ip_mismatch(self, mock_getaddrinfo, mock_get_ipv6, mock_get_ipv4, mock_lightsail):
        mock_getaddrinfo.return_value = [(None, None, None, None, ("1.1.1.1", 0))]
        server = UDPServer(log_file=self.log_file)
        try:
            dns_match, dns_ip, dns_status = server._domain_points_to_ip("demo.example.com", "8.8.8.8")
            self.assertFalse(dns_match)
            self.assertEqual(dns_ip, "1.1.1.1")
            self.assertEqual(dns_status, "mismatch")
        finally:
            server.server_socket.close()

    @patch("UDPServer.LightSail")
    @patch("UDPServer.UDPServer.get_ipv4", return_value="1.2.3.4")
    @patch("UDPServer.UDPServer.get_ipv6", return_value="::1")
    @patch("UDPServer.getaddrinfo", side_effect=Exception("dns down"))
    def test_domain_points_to_ip_resolve_failed(self, mock_getaddrinfo, mock_get_ipv6, mock_get_ipv4, mock_lightsail):
        server = UDPServer(log_file=self.log_file)
        try:
            dns_match, dns_ip, dns_status = server._domain_points_to_ip("demo.example.com", "8.8.8.8")
            self.assertFalse(dns_match)
            self.assertEqual(dns_ip, "")
            self.assertEqual(dns_status, "dns_resolve_failed")
        finally:
            server.server_socket.close()

    @patch("UDPServer.LightSail")
    @patch("UDPServer.UDPServer.get_ipv4", return_value="1.2.3.4")
    @patch("UDPServer.UDPServer.get_ipv6", return_value="::1")
    def test_select_update_ipv4_uses_reported_ip_only(self, mock_get_ipv6, mock_get_ipv4, mock_lightsail):
        server = UDPServer(log_file=self.log_file)
        try:
            self.assertEqual(server._select_update_ipv4("8.8.4.4"), "8.8.4.4")
            self.assertIsNone(server._select_update_ipv4("0.0.0.0"))
            self.assertIsNone(server._select_update_ipv4("not-an-ip"))
        finally:
            server.server_socket.close()


if __name__ == "__main__":
    unittest.main()
