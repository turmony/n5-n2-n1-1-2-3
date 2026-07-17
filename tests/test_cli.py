import unittest

from jlpt_notes.cli import build_parser


class CliTests(unittest.TestCase):
    def test_cli_exposes_initialize_command(self) -> None:
        choices = build_parser()._subparsers._group_actions[0].choices
        self.assertIn("init", choices)
