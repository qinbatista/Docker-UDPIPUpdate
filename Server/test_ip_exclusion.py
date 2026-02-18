import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add the current directory to sys.path to import UDPServer
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from UDPServer import UDPServer


class TestIPExclusion(unittest.TestCase):
    @patch("UDPServer.LightSail")
    @patch("UDPServer.UDPServer.get_ipv4", return_value="1.2.3.4")
    @patch("UDPServer.UDPServer.get_ipv6", return_value="::1")
    @patch("UDPServer.gethostbyname")
    def test_get_excluded_ips(self, mock_gethostbyname, mock_get_ipv6, mock_get_ipv4, mock_lightsail):
        # Setup mock behavior
        def side_effect(domain):
            if domain == "la.qinyupeng.com":
                return "10.0.0.1"
            elif domain == "timov4.qinyupeng.com":
                return "10.0.0.2"
            return "0.0.0.0"

        mock_gethostbyname.side_effect = side_effect

        # Initialize server
        server = UDPServer(log_file="test_udp_server.log")

        # Test finding excluded IPs
        excluded_ips = server._get_excluded_ips()
        print(f"Excluded IPs found: {excluded_ips}")

        self.assertIn("10.0.0.1", excluded_ips)
        self.assertIn("10.0.0.2", excluded_ips)
        self.assertEqual(len(excluded_ips), 2)

        # Verify cache usage (calling again shouldn't trigger side_effect if within 5 mins,
        # but mocking time is complex, so just checking logic works first)

        # Test simulated receive loop check
        sender_ip = "10.0.0.1"
        if sender_ip in excluded_ips:
            print(f"Correctly identified {sender_ip} as excluded.")
        else:
            self.fail(f"Failed to identify {sender_ip} as excluded.")

        sender_ip_allowed = "192.168.1.1"
        if sender_ip_allowed not in excluded_ips:
            print(f"Correctly identified {sender_ip_allowed} as allowed.")
        else:
            self.fail(f"Failed to allow {sender_ip_allowed}.")

if __name__ == "__main__":
    unittest.main()
