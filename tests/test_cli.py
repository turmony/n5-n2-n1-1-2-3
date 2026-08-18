import unittest
from pathlib import Path
import sys
from unittest.mock import patch

from jlpt_notes.cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_cli_exposes_initialize_command(self) -> None:
        choices = build_parser()._subparsers._group_actions[0].choices
        self.assertIn("init", choices)

    def test_cli_exposes_daily_report_and_backup_commands(self) -> None:
        choices = build_parser()._subparsers._group_actions[0].choices
        self.assertTrue({"report-daily", "backup", "validate"}.issubset(choices))

    def test_cli_exposes_reader_command_and_default_port(self) -> None:
        parser = build_parser()
        choices = parser._subparsers._group_actions[0].choices
        self.assertIn("reader", choices)
        args = parser.parse_args(
            ["reader", "--root", "notes", "--config", "reader/mkdocs.yml"]
        )
        self.assertEqual(args.port, 8765)

    def test_reader_port_rejects_privileged_and_out_of_range_values(self) -> None:
        parser = build_parser()
        for value in ("80", "65536", "not-a-number"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                parser.parse_args(["reader", "--port", value])

    def test_reader_dispatches_before_repository_and_passes_current_executable(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "jlpt-notes",
                "reader",
                "--root",
                "my-notes",
                "--config",
                "reader/mkdocs.yml",
                "--port",
                "9876",
            ],
        ), patch("jlpt_notes.reader.launcher.run", return_value=7) as run, patch(
            "jlpt_notes.cli.Repository"
        ) as repository:
            result = main()

        self.assertEqual(result, 7)
        repository.assert_not_called()
        run.assert_called_once_with(
            root=Path("my-notes"),
            config_path=Path("reader/mkdocs.yml"),
            program_path=Path(sys.executable).resolve(),
            port=9876,
        )
