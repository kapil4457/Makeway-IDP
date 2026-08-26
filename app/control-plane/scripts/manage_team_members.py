#!/usr/bin/env python
"""
Team Member Management Script

Add or remove members from an existing team.

Usage:
    # Add members
    python -m scripts.manage_team_members --team-name "my-team" --add "user1@example.com,user2@example.com" --role member --actor-email admin@example.com

    # Remove members (soft delete - sets isDeleted=True)
    python -m scripts.manage_team_members --team-name "my-team" --remove "user1@example.com" --actor-email admin@example.com

    # Change role of existing member
    python -m scripts.manage_team_members --team-name "my-team" --update-role "user1@example.com" --role owner --actor-email admin@example.com
"""

import sys

from sqlmodel import Session

from database.db_engine import engine
from core.logger import get_logger
from scripts.lib import cli, config
from scripts.lib.operations import (
    get_or_create_user,
    get_team,
    get_user,
    remove_team_member,
    update_team_member_role,
    upsert_team_member,
)

logger = get_logger(__name__)


def main() -> int:
    parser = cli.build_parser("Manage team members (add/remove/update role)", epilog=__doc__)
    parser.add_argument("--team-name", required=True, help="Name of the team")
    parser.add_argument("--add", default="", help="Comma-separated list of emails to add as members")
    parser.add_argument("--remove", default="", help="Comma-separated list of emails to remove from team")
    parser.add_argument(
        "--update-role",
        default="",
        help="Email of member whose role should be updated (use with --role)",
    )
    parser.add_argument(
        "--role",
        default="member",
        choices=["member", "owner", "admin"],
        help="Role to assign when adding or updating",
    )
    parser.add_argument(
        "--actor-email",
        required=True,
        help="Email of the person performing this action (for audit trail)",
    )
    parser.add_argument(
        "--password",
        default=config.DEFAULT_PASSWORD,
        help="Password for new users created during add",
    )
    cli.add_dry_run_flag(parser)

    args = parser.parse_args()

    add_emails = cli.parse_csv(args.add)
    remove_emails = cli.parse_csv(args.remove)

    if not add_emails and not remove_emails and not args.update_role:
        parser.error("At least one of --add, --remove, or --update-role is required")

    logger.info(
        "Team: %s | Actor: %s | Add: %s | Remove: %s | Update role: %s -> %s",
        args.team_name, args.actor_email, add_emails or "none", remove_emails or "none",
        args.update_role or "none", args.role,
    )
    if args.dry_run:
        cli.log_dry_run()
        return 0

    try:
        with Session(engine) as session:
            team = get_team(session, args.team_name)
            if not team:
                logger.error("Team not found: %s", args.team_name)
                return 1

            for email in add_emails:
                user = get_or_create_user(session, email, args.password, args.actor_email)
                upsert_team_member(session, team, user, args.role)

            for email in remove_emails:
                user = get_user(session, email)
                if not user:
                    logger.warning("User not found, skipping: %s", email)
                    continue
                remove_team_member(session, team, user)

            if args.update_role:
                user = get_user(session, args.update_role)
                if not user:
                    logger.error("User not found: %s", args.update_role)
                    return 1
                update_team_member_role(session, team, user, args.role)

            session.commit()
            logger.info("Team member management completed successfully")
            return 0
    except Exception as e:  # noqa: BLE001
        logger.error("Team member management failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())