"""Command-line entry points for the JLPT note repository."""

import argparse


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command parser."""
    parser = argparse.ArgumentParser(prog="jlpt-notes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="create a learner data repository")
    return parser


def main() -> int:
    """Run the command-line application."""
    build_parser().parse_args()
    return 0
