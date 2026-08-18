import json
import subprocess
import unittest

from jlpt_notes.reader.network import (
    LanAddress,
    NetworkInspectionError,
    parse_network_json,
    private_lan_addresses,
)


class ReaderNetworkTests(unittest.TestCase):
    def test_keeps_only_active_physical_private_rfc1918_addresses(self) -> None:
        rows = [
            _network_row(9, "10.0.0.8", NetworkCategory="Public"),
            _network_row(7, "192.168.1.20"),
            _network_row(8, "172.31.4.5", InterfaceAlias="Ethernet", MediaType="802.3"),
            _network_row(10, "127.0.0.1"),
            _network_row(11, "169.254.1.8"),
            _network_row(12, "2001:db8::1"),
            _network_row(13, "8.8.8.8"),
            _network_row(14, "10.1.1.8", SkipAsSource=True),
            _network_row(15, "10.1.1.9", AdapterStatus="Disconnected"),
        ]

        addresses = parse_network_json(json.dumps(rows))

        self.assertEqual(
            addresses,
            (
                LanAddress(7, "192.168.1.20", "Private"),
                LanAddress(8, "172.31.4.5", "Private"),
            ),
        )

    def test_prefers_wifi_then_ethernet_and_excludes_vpn_and_virtual_switches(self) -> None:
        rows = [
            _network_row(
                3,
                "192.168.137.1",
                InterfaceAlias="vEthernet (Default Switch)",
                InterfaceDescription="Hyper-V Virtual Ethernet Adapter",
                HardwareInterface=True,
                Virtual=False,
                MediaType="802.3",
            ),
            _network_row(
                4,
                "10.8.0.2",
                InterfaceAlias="Work VPN",
                InterfaceDescription="WireGuard Tunnel",
                HardwareInterface=True,
                Virtual=False,
                MediaType="Tunnel",
            ),
            _network_row(
                11,
                "192.168.1.30",
                InterfaceAlias="Ethernet",
                InterfaceDescription="Realtek PCIe GbE Family Controller",
                MediaType="802.3",
            ),
            _network_row(7, "192.168.1.20"),
            _network_row(
                12,
                "192.168.1.40",
                InterfaceAlias="USB LAN",
                InterfaceDescription="USB network device",
                MediaType="Unknown",
            ),
        ]

        addresses = parse_network_json(json.dumps(rows))

        self.assertEqual(
            addresses,
            (
                LanAddress(7, "192.168.1.20", "Private"),
                LanAddress(11, "192.168.1.30", "Private"),
                LanAddress(12, "192.168.1.40", "Private"),
            ),
        )

    def test_accepts_single_powershell_json_object_and_empty_output(self) -> None:
        text = json.dumps(_network_row(12, "10.2.0.4"))

        addresses = parse_network_json(text)

        self.assertEqual(addresses, (LanAddress(12, "10.2.0.4", "Private"),))
        self.assertEqual(parse_network_json(""), ())

    def test_discovers_addresses_from_injected_adapter_metadata(self) -> None:
        rows = [
            _network_row(7, "192.168.50.7"),
            _network_row(
                6,
                "10.44.0.2",
                InterfaceAlias="Company VPN",
                InterfaceDescription="OpenVPN Data Channel Offload",
                HardwareInterface=True,
                Virtual=False,
                MediaType="Tunnel",
            ),
        ]

        def injected_runner(command, **kwargs):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(rows),
                stderr="",
            )

        addresses = private_lan_addresses(runner=injected_runner)

        self.assertEqual(addresses, (LanAddress(7, "192.168.50.7", "Private"),))

    def test_reports_malformed_network_output_with_launcher_friendly_error(self) -> None:
        malformed_values = (
            "{",
            '"not an object list"',
            json.dumps({"InterfaceIndex": 7}),
            json.dumps(_network_row(7, "not-an-ip")),
            json.dumps(_network_row(True, "192.168.1.20")),
        )

        for text in malformed_values:
            with self.subTest(text=text), self.assertRaisesRegex(
                NetworkInspectionError,
                "无法解析 Windows 网络信息",
            ):
                parse_network_json(text)

    def test_reports_powershell_discovery_failures_without_changing_networks(self) -> None:
        def failing_runner(command, **kwargs):
            raise subprocess.CalledProcessError(1, command, stderr="access denied")

        with self.assertRaisesRegex(NetworkInspectionError, "无法读取.*access denied"):
            private_lan_addresses(runner=failing_runner)


def _network_row(interface_index, address: str, **changes):
    row = {
        "InterfaceIndex": interface_index,
        "IPAddress": address,
        "NetworkCategory": "Private",
        "SkipAsSource": False,
        "AdapterStatus": "Up",
        "HardwareInterface": True,
        "Virtual": False,
        "InterfaceAlias": "Wi-Fi",
        "InterfaceDescription": "Intel Wi-Fi 6 AX201 160MHz",
        "MediaType": "Native 802.11",
        "PhysicalMediaType": "Native 802.11",
    }
    row.update(changes)
    return row


if __name__ == "__main__":
    unittest.main()
