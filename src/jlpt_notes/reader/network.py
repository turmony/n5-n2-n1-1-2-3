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
    """Parse and rank safe physical-LAN candidates from PowerShell JSON."""
    if not text.strip():
        return ()
    try:
        value = json.loads(text)
        rows = value if isinstance(value, list) else [value]
        if not all(isinstance(row, dict) for row in rows):
            raise TypeError("network result is not an object list")
        ranked = [_parse_candidate(row) for row in rows]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise NetworkInspectionError(
            f"无法解析 Windows 网络信息：返回数据无效（{error}）"
        ) from error

    unique: dict[tuple[int, str], tuple[int, LanAddress]] = {}
    for candidate in ranked:
        if candidate is None:
            continue
        rank, address = candidate
        unique[(address.interface_index, address.address)] = (rank, address)
    return tuple(
        address
        for _, address in sorted(
            unique.values(),
            key=lambda item: (
                item[0],
                item[1].interface_index,
                int(ipaddress.ip_address(item[1].address)),
            ),
        )
    )


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
$adapters = Get-NetAdapter -Physical -IncludeHidden
$rows = @(
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.AddressState -eq 'Preferred' } |
    ForEach-Object {
        $address = $_
        $profile = @($profiles | Where-Object { $_.InterfaceIndex -eq $address.InterfaceIndex })[0]
        if ($null -ne $profile) {
            $adapter = @($adapters | Where-Object { $_.InterfaceIndex -eq $address.InterfaceIndex })[0]
            [pscustomobject]@{
                InterfaceIndex = $address.InterfaceIndex
                IPAddress = [string]$address.IPAddress
                NetworkCategory = $profile.NetworkCategory.ToString()
                SkipAsSource = [bool]$address.SkipAsSource
                AdapterStatus = [string]$adapter.Status
                HardwareInterface = [bool]$adapter.HardwareInterface
                Virtual = [bool]$adapter.Virtual
                InterfaceAlias = [string]$address.InterfaceAlias
                InterfaceDescription = [string]$adapter.InterfaceDescription
                MediaType = [string]$adapter.MediaType
                PhysicalMediaType = [string]$adapter.PhysicalMediaType
            }
        }
    }
)
ConvertTo-Json -InputObject $rows -Compress
""".strip()


_PRIVATE_RANGES = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_BLOCKED_ADAPTER_MARKERS = (
    "vpn",
    "tunnel",
    "hyper-v",
    "vethernet",
    "virtual",
    "loopback",
    "wireguard",
    "openvpn",
    "tailscale",
    "zerotier",
    "wsl",
    "docker",
)


def _parse_candidate(row: dict[str, object]) -> tuple[int, LanAddress] | None:
    interface_index = _required_int(row, "InterfaceIndex")
    address_text = _required_string(row, "IPAddress")
    category = _required_string(row, "NetworkCategory")
    skip_as_source = _required_bool(row, "SkipAsSource")
    adapter_status = _required_string(row, "AdapterStatus")
    hardware_interface = _required_bool(row, "HardwareInterface")
    virtual = _required_bool(row, "Virtual")
    adapter_text = " ".join(
        _required_string(row, field)
        for field in (
            "InterfaceAlias",
            "InterfaceDescription",
            "MediaType",
            "PhysicalMediaType",
        )
    ).casefold()
    address = ipaddress.ip_address(address_text)

    if (
        category.casefold() != "private"
        or address.version != 4
        or not any(address in network for network in _PRIVATE_RANGES)
        or skip_as_source
        or adapter_status.casefold() != "up"
        or not hardware_interface
        or virtual
        or any(marker in adapter_text for marker in _BLOCKED_ADAPTER_MARKERS)
    ):
        return None

    if any(
        marker in adapter_text
        for marker in ("802.11", "wi-fi", "wifi", "wireless", "wlan")
    ):
        rank = 0
    elif any(marker in adapter_text for marker in ("802.3", "ethernet", "gbe")):
        rank = 1
    else:
        rank = 2
    return rank, LanAddress(interface_index, str(address), "Private")


def _required_string(row: dict[str, object], field: str) -> str:
    value = row[field]
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text")
    return value


def _required_bool(row: dict[str, object], field: str) -> bool:
    value = row[field]
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be boolean")
    return value


def _required_int(row: dict[str, object], field: str) -> int:
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TypeError(f"{field} must be a positive integer")
    return value
