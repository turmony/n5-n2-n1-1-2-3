"""Inspect read-only Windows network state for the LAN reader."""

from dataclasses import dataclass
import ipaddress
import json
import subprocess
from collections.abc import Callable
from typing import Any


class NetworkInspectionError(RuntimeError):
    """Raised when Windows network state cannot be inspected."""


@dataclass(frozen=True)
class LanAddress:
    interface_index: int
    address: str
    category: str


def parse_network_json(text: str) -> tuple[LanAddress, ...]:
    value = json.loads(text or "[]")
    rows = value if isinstance(value, list) else [value]
    private_ranges = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
    )
    addresses = []
    for row in rows:
        address = ipaddress.ip_address(str(row["IPAddress"]))
        if (
            row.get("NetworkCategory") == "Private"
            and address.version == 4
            and any(address in network for network in private_ranges)
        ):
            addresses.append(
                LanAddress(int(row["InterfaceIndex"]), str(address), "Private")
            )
    return tuple(sorted(addresses, key=lambda item: (item.interface_index, item.address)))


def private_lan_addresses(*, runner=None) -> tuple[LanAddress, ...]:
    """Return RFC 1918 IPv4 addresses on Windows Private profiles."""
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        _NETWORK_QUERY,
    ]
    process_runner: Callable[..., Any] = runner or subprocess.run
    try:
        completed = process_runner(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        raise NetworkInspectionError(f"无法读取 Windows 私有网络信息：{detail}") from error
    return parse_network_json(completed.stdout)


_NETWORK_QUERY = r"""
$profiles = Get-NetConnectionProfile |
    Where-Object { $_.IPv4Connectivity -ne 'Disconnected' }
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.AddressState -eq 'Preferred' } |
    ForEach-Object {
        $address = $_
        $profiles |
            Where-Object { $_.InterfaceIndex -eq $address.InterfaceIndex } |
            ForEach-Object {
                [pscustomobject]@{
                    InterfaceIndex = $address.InterfaceIndex
                    IPAddress = $address.IPAddress
                    NetworkCategory = $_.NetworkCategory.ToString()
                }
            }
    } |
    Select-Object InterfaceIndex, IPAddress, NetworkCategory |
    ConvertTo-Json -Compress
""".strip()
