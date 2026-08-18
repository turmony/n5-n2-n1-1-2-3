"""Inspect and explicitly configure the reader's Windows Firewall rule."""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any


RULE_DISPLAY_NAME = "JLPT iPad Reader (Private LAN)"


class FirewallInspectionError(RuntimeError):
    """Raised when firewall status cannot be inspected."""


class FirewallConfigurationError(RuntimeError):
    """Raised when the explicit firewall configuration cannot be launched."""


def firewall_rule_present(
    port: int,
    program_path: Path,
    *,
    runner=None,
) -> bool:
    """Inspect whether the exact enabled Private/LocalSubnet rule exists."""
    checked_port = _validate_port(port)
    expected_program = str(_resolve_program_path(program_path))
    query = _status_query()
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

    try:
        value = json.loads(completed.stdout or "[]")
        rows = value if isinstance(value, list) else [value]
        if not all(isinstance(row, dict) for row in rows):
            raise TypeError("rule result is not an object list")
    except (json.JSONDecodeError, TypeError) as error:
        raise FirewallInspectionError(
            f"无法检查 Windows 防火墙规则：返回数据无效（{error}）"
        ) from error
    return len(rows) == 1 and _rule_matches(rows[0], checked_port, expected_program)


def configure_firewall(
    script_path: Path,
    port: int,
    program_path: Path,
    *,
    runner=None,
) -> bool:
    """Run the firewall script only after an explicit caller action."""
    checked_port = _validate_port(port)
    resolved_script = Path(script_path).resolve(strict=True)
    program = _resolve_program_path(program_path)
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
        "-Program",
        str(program),
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


def _resolve_program_path(program_path: Path) -> Path:
    resolved = Path(program_path).resolve(strict=True)
    if not resolved.is_file():
        raise FileNotFoundError(f"找不到阅读器程序：{resolved}")
    return resolved


def _rule_matches(rule: dict[str, object], port: int, program: str) -> bool:
    return (
        rule.get("DisplayName") == RULE_DISPLAY_NAME
        and rule.get("Enabled") == "True"
        and rule.get("Direction") == "Inbound"
        and rule.get("Action") == "Allow"
        and rule.get("Profile") == "Private"
        and rule.get("Protocol") == "TCP"
        and str(rule.get("LocalPort")) == str(port)
        and rule.get("RemoteAddress") == ["LocalSubnet"]
        and str(rule.get("Program", "")).casefold() == program.casefold()
    )


def _status_query() -> str:
    return rf"""
$name = '{RULE_DISPLAY_NAME}'
$rules = @(
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue |
    ForEach-Object {{
        $rule = $_
        $portFilter = Get-NetFirewallPortFilter -AssociatedNetFirewallRule $_
        $addressFilter = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $_
        $applicationFilter = Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule $_
        [pscustomobject]@{{
            DisplayName = [string]$rule.DisplayName
            Enabled = $rule.Enabled.ToString()
            Direction = $rule.Direction.ToString()
            Action = $rule.Action.ToString()
            Profile = $rule.Profile.ToString()
            Protocol = $portFilter.Protocol.ToString()
            LocalPort = [string]$portFilter.LocalPort
            RemoteAddress = @($addressFilter.RemoteAddress)
            Program = [string]$applicationFilter.Program
        }}
    }}
)
ConvertTo-Json -InputObject $rules -Compress
""".strip()
