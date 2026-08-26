"""Shared CLI plumbing for operational scripts.

Centralises the logging bootstrap, comma-list parsing and dry-run guard so
scripts stay thin and consistent.
"""

import argparse


def build_parser(description: str, epilog: str | None = None) -> argparse.ArgumentParser:
    """Return a configured argument parser with the module docstring as epilog."""
    return argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )


def parse_csv(value: str | None) -> list[str]:
    """Split a CSV string into a list of trimmed, non-empty items."""
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


def add_dry_run_flag(parser: argparse.ArgumentParser) -> None:
    """Attach the conventional ``--dry-run`` flag to a parser."""
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )


def log_dry_run() -> None:
    """Log the guard message emitted when --dry-run is set."""
    from core.logger import get_logger

    get_logger(__name__).info("DRY RUN - No changes will be made")