"""Inspect and explicitly configure the reader's Windows Firewall rule."""

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any


RULE_DISPLAY_NAME = "JLPT iPad Reader (Private LAN)"


class FirewallInspectionError(RuntimeError):
    """Raised when firewall status cannot be inspected."""


class FirewallConfigurationError(RuntimeError):
    """Raised when the explicit firewall configuration cannot be launched."""


def firewall_rule_present(port: int, *, runner=None) -> bool:
    """Inspect whether the exact enabled Private/LocalSubnet rule exists."""
    checked_port = _validate_port(port)
    query = _status_query(checked_port)
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        query,
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
        raise FirewallInspectionError(f"无法检查 Windows 防火墙规则：{detail}") from error

    value = completed.stdout.strip().casefold()
    if value not in {"true", "false"}:
        raise FirewallInspectionError("无法检查 Windows 防火墙规则：PowerShell 返回了未知结果")
    return value == "true"


def configure_firewall(
    script_path: Path,
    port: int,
    *,
    runner=None,
) -> bool:
    """Run the firewall script only after an explicit caller action."""
    checked_port = _validate_port(port)
    resolved_script = Path(script_path).resolve(strict=True)
    if not resolved_script.is_file():
        raise FileNotFoundError(f"找不到防火墙配置脚本：{resolved_script}")
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(resolved_script),
        "-Port",
        str(checked_port),
    ]
    process_runner: Callable[..., Any] = runner or subprocess.run
    try:
        completed = process_runner(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise FirewallConfigurationError(f"无法启动 Windows 防火墙配置：{error}") from error
    return completed.returncode == 0


def _validate_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError("端口必须是 1024 到 65535 之间的整数")
    return port


def _status_query(port: int) -> str:
    return rf"""
$name = '{RULE_DISPLAY_NAME}'
$found = $false
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue |
    Where-Object {{
        $_.Enabled -eq 'True' -and
        $_.Direction -eq 'Inbound' -and
        $_.Action -eq 'Allow' -and
        $_.Profile -eq 'Private'
    }} |
    ForEach-Object {{
        $portFilter = Get-NetFirewallPortFilter -AssociatedNetFirewallRule $_
        $addressFilter = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $_
        if (
            $portFilter.Protocol -eq 'TCP' -and
            [string]$portFilter.LocalPort -eq '{port}' -and
            @($addressFilter.RemoteAddress).Count -eq 1 -and
            $addressFilter.RemoteAddress -contains 'LocalSubnet'
        ) {{
            $found = $true
        }}
    }}
if ($found) {{ 'True' }} else {{ 'False' }}
""".strip()
