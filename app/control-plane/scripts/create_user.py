#!/usr/bin/env python
"""
User Creation Script

Creates a new user in the system.

Usage:
    python -m scripts.create_user --email "user@example.com" --password "securepassword"
    python -m scripts.create_user --email "user@example.com"  # Uses default password
"""

import sys

from sqlmodel import Session

from database.db_engine import engine
from core.logger import get_logger
from scripts.lib import cli, config
from scripts.lib.operations import get_or_create_user

logger = get_logger(__name__)


def main() -> int:
    parser = cli.build_parser("Create a new user", epilog=__doc__)
    parser.add_argument("--email", required=True, help="Email of the user to create")
    parser.add_argument("--password", default=config.DEFAULT_PASSWORD, help="Password for the user")
    cli.add_dry_run_flag(parser)

    args = parser.parse_args()

    logger.info("Email: %s", args.email)
    if args.dry_run:
        cli.log_dry_run()
        return 0

    try:
        with Session(engine) as session:
            user = get_or_create_user(session, args.email, args.password)
            session.commit()
            logger.info("User confirmed: %s (userId=%s)", user.email, user.userId)
            return 0
    except Exception as e:  # noqa: BLE001
        logger.error("User creation failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())