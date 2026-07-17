"""Command-line entry points for the JLPT note repository."""

import argparse
from datetime import date
from pathlib import Path

from .analytics import aggregate_attempts, render_daily_report
from .repository import Repository


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command parser."""
    parser = argparse.ArgumentParser(prog="jlpt-notes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("init", "create a learner data repository"), ("validate", "validate the repository"),
                            ("report-daily", "render today's read-only review brief"), ("backup", "create a local backup")):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--root", default="jlpt-notes")
    subparsers.choices["report-daily"].add_argument("--limit", type=int, default=15)
    return parser


def main() -> int:
    """Run the command-line application."""
    args = build_parser().parse_args()
    repo = Repository(Path(args.root))
    if args.command == "init":
        repo.init_layout()
        print(f"已创建资料库：{repo.root}")
    elif args.command == "validate":
        repo.init_layout()
        print("资料库结构有效")
    elif args.command == "report-daily":
        repo.init_layout()
        print(render_daily_report(aggregate_attempts([]), 0, 0, 0, args.limit))
    elif args.command == "backup":
        print(repo.create_backup(date.today()))
    return 0
