import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from jlpt_notes.reader.firewall import (
    FirewallConfigurationError,
    FirewallInspectionError,
    configure_firewall,
    firewall_rule_present,
)


class ReaderFirewallTests(unittest.TestCase):
    def test_status_query_accepts_only_the_private_local_subnet_tcp_rule(self) -> None:
        rule = _firewall_rule()

        def matching_query_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(rule), stderr="")

        self.assertTrue(
            firewall_rule_present(8765, _serving_program(), runner=matching_query_runner)
        )

    def test_status_rejects_each_single_unsafe_rule_independently(self) -> None:
        unsafe_rules = (
            ("public profile", {"Profile": "Public"}),
            ("any profile", {"Profile": "Any"}),
            ("any remote", {"RemoteAddress": ["Any"]}),
            ("extra remote", {"RemoteAddress": ["LocalSubnet", "Any"]}),
            ("udp", {"Protocol": "UDP"}),
            ("wrong port", {"LocalPort": "9876"}),
            ("disabled", {"Enabled": "False"}),
            ("outbound", {"Direction": "Outbound"}),
            ("wrong program", {"Program": r"C:\Windows\System32\notepad.exe"}),
            ("block action", {"Action": "Block"}),
        )

        for label, changes in unsafe_rules:
            rule = _firewall_rule(**changes)

            def unsafe_rule_runner(command, **kwargs):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(rule),
                    stderr="",
                )

            with self.subTest(label=label):
                self.assertFalse(
                    firewall_rule_present(
                        8765,
                        _serving_program(),
                        runner=unsafe_rule_runner,
                    )
                )

    def test_status_rejects_an_exact_rule_when_a_broad_same_name_sibling_exists(self) -> None:
        exact = _firewall_rule()
        broad = _firewall_rule(
            Profile="Public",
            RemoteAddress=["Any"],
            Program="Any",
        )

        def mixed_rule_runner(command, **kwargs):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps([exact, broad]),
                stderr="",
            )

        self.assertFalse(
            firewall_rule_present(8765, _serving_program(), runner=mixed_rule_runner)
        )

    def test_status_query_returns_false_when_no_matching_rule_exists(self) -> None:
        def no_rule_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")

        self.assertFalse(
            firewall_rule_present(8765, _serving_program(), runner=no_rule_runner)
        )

    def test_status_query_reports_inspection_failures(self) -> None:
        def failing_runner(command, **kwargs):
            raise subprocess.CalledProcessError(1, command, stderr="not permitted")

        with self.assertRaisesRegex(FirewallInspectionError, "无法检查.*not permitted"):
            firewall_rule_present(8765, _serving_program(), runner=failing_runner)

    def test_configuration_runs_only_the_explicit_resolved_script(self) -> None:
        with TemporaryDirectory() as directory:
            script = Path(directory) / "configure firewall.ps1"
            program = Path(directory) / "pythonw.exe"
            script.write_text("# controlled test script\n", encoding="utf-8")
            program.write_bytes(b"test executable")
            expected = [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script.resolve()),
                "-Port",
                "8765",
                "-Program",
                str(program.resolve()),
            ]

            def successful_runner(command, **kwargs):
                self.assertEqual(command, expected)
                self.assertEqual(
                    kwargs,
                    {"capture_output": True, "text": True, "timeout": 120, "check": False},
                )
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            configured = configure_firewall(
                script,
                8765,
                program,
                runner=successful_runner,
            )

        self.assertTrue(configured)

    def test_configuration_returns_false_when_uac_or_script_is_cancelled(self) -> None:
        with TemporaryDirectory() as directory:
            script = Path(directory) / "configure-firewall.ps1"
            program = Path(directory) / "pythonw.exe"
            script.write_text("# controlled test script\n", encoding="utf-8")
            program.write_bytes(b"test executable")

            def cancelled_runner(command, **kwargs):
                return subprocess.CompletedProcess(command, 1223, stdout="", stderr="cancelled")

            self.assertFalse(
                configure_firewall(script, 8765, program, runner=cancelled_runner)
            )

    def test_configuration_rejects_unsafe_input_without_starting_powershell(self) -> None:
        def forbidden_runner(command, **kwargs):
            self.fail("invalid configuration must not start PowerShell")

        with self.assertRaisesRegex(ValueError, "1024.*65535"):
            configure_firewall(
                Path("missing.ps1"),
                80,
                Path("missing-pythonw.exe"),
                runner=forbidden_runner,
            )
        with self.assertRaises(FileNotFoundError):
            configure_firewall(
                Path("missing.ps1"),
                8765,
                Path("missing-pythonw.exe"),
                runner=forbidden_runner,
            )

    def test_configuration_reports_process_launch_failures(self) -> None:
        with TemporaryDirectory() as directory:
            script = Path(directory) / "configure-firewall.ps1"
            program = Path(directory) / "pythonw.exe"
            script.write_text("# controlled test script\n", encoding="utf-8")
            program.write_bytes(b"test executable")

            def unavailable_runner(command, **kwargs):
                raise OSError("PowerShell unavailable")

            with self.assertRaisesRegex(FirewallConfigurationError, "无法启动.*unavailable"):
                configure_firewall(script, 8765, program, runner=unavailable_runner)

    def test_script_whatif_describes_the_rule_without_touching_firewall(self) -> None:
        project = Path(__file__).resolve().parents[2]
        script = project / "reader" / "configure-firewall.ps1"
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Port",
                "8765",
                "-Program",
                str(_serving_program()),
                "-WhatIf",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )

        preview = json.loads(completed.stdout)
        self.assertEqual(
            preview,
            {
                "DisplayName": "JLPT iPad Reader (Private LAN)",
                "Direction": "Inbound",
                "Action": "Allow",
                "Protocol": "TCP",
                "LocalPort": 8765,
                "Profile": "Private",
                "RemoteAddress": "LocalSubnet",
                "Program": str(_serving_program()),
            },
        )


def _firewall_rule(**changes):
    rule = {
        "DisplayName": "JLPT iPad Reader (Private LAN)",
        "Enabled": "True",
        "Direction": "Inbound",
        "Action": "Allow",
        "Profile": "Private",
        "Protocol": "TCP",
        "LocalPort": "8765",
        "RemoteAddress": ["LocalSubnet"],
        "Program": str(_serving_program()),
    }
    rule.update(changes)
    return rule


def _serving_program() -> Path:
    return Path(sys.executable).with_name("pythonw.exe").resolve()


if __name__ == "__main__":
    unittest.main()
