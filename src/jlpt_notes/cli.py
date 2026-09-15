"""Command-line entry points for the JLPT note repository."""

import argparse
from datetime import date
from pathlib import Path
import sys

from .analytics import aggregate_attempts, render_daily_report
from .repository import Repository


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command parser."""
    parser = argparse.ArgumentParser(prog="jlpt-notes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("init", "create a learner data repository"), ("validate", "validate the repository"),
                            ("validate-links", "check publishable local image links without writing"),
                            ("report-daily", "render today's read-only review brief"), ("backup", "create a local backup")):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--root", default="jlpt-notes")
    subparsers.choices["report-daily"].add_argument("--limit", type=int, default=15)
    reader = subparsers.add_parser("reader", help="open the manual iPad LAN reader")
    reader.add_argument("--root", default="jlpt-notes")
    reader.add_argument("--config", default="reader/mkdocs.yml")
    reader.add_argument("--port", type=_reader_port, default=8765)
    return parser


def main() -> int:
    """Run the command-line application."""
    args = build_parser().parse_args()
    if args.command == "reader":
        from .reader.launcher import run

        return run(
            root=Path(args.root),
            config_path=Path(args.config),
            program_path=Path(sys.executable).resolve(),
            port=args.port,
        )
    repo = Repository(Path(args.root))
    if args.command == "init":
        repo.init_layout()
        print(f"已创建资料库：{repo.root}")
    elif args.command in {"validate", "validate-links"}:
        from .asset_links import audit_assets

        if not repo.root.is_dir():
            print(f"资料库不存在：{repo.root}", file=sys.stderr)
            return 1
        issues = audit_assets(repo.root)
        for issue in issues:
            print(issue, file=sys.stderr)
        if issues:
            print(f"发现 {len(issues)} 个图片资源链接问题", file=sys.stderr)
            return 1
        print("图片资源链接校验通过")
    elif args.command == "report-daily":
        repo.init_layout()
        print(render_daily_report(aggregate_attempts([]), 0, 0, 0, args.limit))
    elif args.command == "backup":
        print(repo.create_backup(date.today()))
    return 0


def _reader_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("端口必须是整数") from error
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须是 1024 到 65535 之间的整数")
    return port
