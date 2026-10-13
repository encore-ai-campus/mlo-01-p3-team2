from unittest.mock import patch

from django.test import SimpleTestCase

from .network import local_lan_addresses


class LanAddressTests(SimpleTestCase):
    @patch("config.network.socket.gethostbyname_ex")
    def test_only_this_pc_private_addresses_become_allowed_hosts(self, resolve):
        resolve.return_value = ("campus-pc", [], [
            "192.168.0.77", "192.168.0.77", "172.25.176.1", "10.2.3.4",
            "127.0.0.1", "0.0.0.0", "169.254.1.2", "8.8.8.8", "::1", "*", "invalid",
        ])
        self.assertEqual(local_lan_addresses(), ["10.2.3.4", "172.25.176.1", "192.168.0.77"])

    @patch("config.network.socket.gethostbyname_ex", side_effect=OSError("unavailable"))
    def test_lookup_failure_keeps_loopback_server_available(self, resolve):
        self.assertEqual(local_lan_addresses(), [])
