#!/usr/bin/env python
"""
Team Creation Script

Creates a team with an owner and optional members.
The creator of the team becomes the owner (role="owner").
Additional members are added with role="member".

Usage:
    python -m scripts.create_team --team-name "my-team" --owner-email "owner@example.com" --members "member1@example.com,member2@example.com"
    python -m scripts.create_team --team-name "my-team" --owner-email "owner@example.com"
"""

import sys

from sqlmodel import Session

from database.db_engine import engine
from core.logger import get_logger
from scripts.lib import cli, config
from scripts.lib.operations import (
    get_or_create_team,
    get_or_create_user,
    upsert_team_member,
)

logger = get_logger(__name__)


def main() -> int:
    parser = cli.build_parser("Create a team with owner and members", epilog=__doc__)
    parser.add_argument("--team-name", required=True, help="Name of the team to create")
    parser.add_argument(
        "--owner-email",
        required=True,
        help="Email of the team owner (will be created if doesn't exist)",
    )
    parser.add_argument(
        "--owner-password",
        default=config.DEFAULT_PASSWORD,
        help="Password for the owner",
    )
    parser.add_argument(
        "--members",
        default="",
        help="Comma-separated list of member emails to add to the team",
    )
    parser.add_argument(
        "--member-password",
        default=config.DEFAULT_PASSWORD,
        help="Password for members",
    )
    cli.add_dry_run_flag(parser)

    args = parser.parse_args()
    member_emails = cli.parse_csv(args.members)

    logger.info("Team name: %s | Owner: %s | Members: %s", args.team_name, args.owner_email, member_emails or "none")
    if args.dry_run:
        cli.log_dry_run()
        return 0

    try:
        with Session(engine) as session:
            owner = get_or_create_user(session, args.owner_email, args.owner_password)
            team = get_or_create_team(session, args.team_name, args.owner_email)
            upsert_team_member(session, team, owner, "owner")

            for member_email in member_emails:
                member = get_or_create_user(session, member_email, args.member_password, args.owner_email)
                upsert_team_member(session, team, member, "member")

            session.commit()

            logger.info("Team creation completed: %s (teamId=%s)", team.teamName, team.teamId)
            return 0
    except Exception as e:  # noqa: BLE001 - scripts report and exit non-zero
        logger.error("Team creation failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())