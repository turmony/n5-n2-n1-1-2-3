import subprocess
import unittest

from jlpt_notes.reader.network import (
    NetworkInspectionError,
    parse_network_json,
    private_lan_addresses,
)


class ReaderNetworkTests(unittest.TestCase):
    def test_keeps_only_private_profile_rfc1918_ipv4_addresses(self) -> None:
        text = """[
            {"InterfaceIndex":9,"IPAddress":"10.0.0.8","NetworkCategory":"Public"},
            {"InterfaceIndex":7,"IPAddress":"192.168.1.20","NetworkCategory":"Private"},
            {"InterfaceIndex":8,"IPAddress":"172.31.4.5","NetworkCategory":"Private"},
            {"InterfaceIndex":7,"IPAddress":"127.0.0.1","NetworkCategory":"Private"},
            {"InterfaceIndex":7,"IPAddress":"169.254.1.8","NetworkCategory":"Private"},
            {"InterfaceIndex":7,"IPAddress":"2001:db8::1","NetworkCategory":"Private"},
            {"InterfaceIndex":7,"IPAddress":"8.8.8.8","NetworkCategory":"Private"}
        ]"""

        addresses = parse_network_json(text)

        self.assertEqual(
            addresses,
            (
                _lan_address(7, "192.168.1.20"),
                _lan_address(8, "172.31.4.5"),
            ),
        )

    def test_accepts_single_powershell_json_object_and_sorts_addresses(self) -> None:
        text = '{"InterfaceIndex":12,"IPAddress":"10.2.0.4","NetworkCategory":"Private"}'

        addresses = parse_network_json(text)

        self.assertEqual(addresses, (_lan_address(12, "10.2.0.4"),))
        self.assertEqual(parse_network_json(""), ())

    def test_discovers_addresses_with_fixed_read_only_powershell_query(self) -> None:
        def fixed_query_runner(command, **kwargs):
            self.assertEqual(command[:3], ["powershell.exe", "-NoProfile", "-NonInteractive"])
            self.assertEqual(command[3], "-Command")
            query = command[4]
            for required in (
                "Get-NetConnectionProfile",
                "IPv4Connectivity -ne 'Disconnected'",
                "Get-NetIPAddress -AddressFamily IPv4",
                "InterfaceIndex",
                "IPAddress",
                "NetworkCategory",
                "ConvertTo-Json -Compress",
            ):
                self.assertIn(required, query)
            self.assertEqual(
                kwargs,
                {"capture_output": True, "text": True, "timeout": 10, "check": True},
            )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='{"InterfaceIndex":4,"IPAddress":"192.168.50.7","NetworkCategory":"Private"}',
                stderr="",
            )

        addresses = private_lan_addresses(runner=fixed_query_runner)

        self.assertEqual(addresses, (_lan_address(4, "192.168.50.7"),))

    def test_reports_powershell_discovery_failures_without_changing_networks(self) -> None:
        def failing_runner(command, **kwargs):
            raise subprocess.CalledProcessError(1, command, stderr="access denied")

        with self.assertRaisesRegex(NetworkInspectionError, "无法读取.*access denied"):
            private_lan_addresses(runner=failing_runner)


def _lan_address(interface_index: int, address: str):
    from jlpt_notes.reader.network import LanAddress

    return LanAddress(interface_index, address, "Private")


if __name__ == "__main__":
    unittest.main()
