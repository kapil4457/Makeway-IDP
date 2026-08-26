#!/usr/bin/env python
"""
List Teams Script

Lists all teams with their members and roles.
"""

import sys

from sqlmodel import Session

from database.db_engine import engine
from core.logger import get_logger
from scripts.lib.operations import list_teams_with_members

logger = get_logger(__name__)


def main() -> int:
    try:
        with Session(engine) as session:
            teams = list_teams_with_members(session)

            if not teams:
                logger.info("No teams found")
                return 0

            logger.info("Found %s team(s)", len(teams))
            for team, members in teams:
                logger.info("Team: %s (teamId=%s) | created by %s", team.teamName, team.teamId, team.createdBy)
                if not members:
                    logger.info("  No active members")
                    continue
                for tm, user in members:
                    logger.info("  - %s (userId=%s) - role: %s", user.email, user.userId, tm.role)

            return 0
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to list teams: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())