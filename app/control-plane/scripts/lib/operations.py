"""Business logic for Makeway operational scripts.

Every script under ``scripts/`` delegates to the functions in this module so
user/team/membership semantics live in exactly one place. Scripts only ever
parse CLI arguments, open a session and call these helpers.
"""

from uuid import UUID

from sqlmodel import Session, select

from auth.password import hash_password
from core.logger import get_logger
from database.models.team import Team
from database.models.team_member import TeamMember
from database.models.user import User

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# User operations
# ---------------------------------------------------------------------------


def get_user(session: Session, email: str) -> User | None:
    """Return the user with the given email, or None."""
    return session.exec(select(User).where(User.email == email)).first()


def get_or_create_user(
    session: Session,
    email: str,
    password: str,
    actor_email: str | None = None,
) -> User:
    """Return an existing user by email, or create a new one.

    ``actor_email`` is recorded as the creator/editor for audit purposes and
    defaults to the user's own email when not provided.
    """
    user = get_user(session, email)
    if user:
        logger.info("User already exists: %s (userId=%s)", email, user.userId)
        return user

    actor = actor_email or email
    user = User(
        email=email,
        passwordHash=hash_password(password),
        createdBy=actor,
        modifiedBy=actor,
    )
    session.add(user)
    session.flush()
    session.refresh(user)
    logger.info("Created user: %s (userId=%s)", email, user.userId)
    return user


# ---------------------------------------------------------------------------
# Team operations
# ---------------------------------------------------------------------------


def get_team(session: Session, team_name: str) -> Team | None:
    """Return the team with the given name, or None."""
    return session.exec(select(Team).where(Team.teamName == team_name)).first()


def get_or_create_team(
    session: Session,
    team_name: str,
    actor_email: str,
) -> Team:
    """Return an existing team by name, or create a new one."""
    team = get_team(session, team_name)
    if team:
        logger.info("Team already exists: %s (teamId=%s)", team_name, team.teamId)
        return team

    team = Team(
        teamName=team_name,
        createdBy=actor_email,
        modifiedBy=actor_email,
    )
    session.add(team)
    session.flush()
    session.refresh(team)
    logger.info("Created team: %s (teamId=%s)", team_name, team.teamId)
    return team


def list_teams_with_members(session: Session) -> list[tuple[Team, list[tuple[TeamMember, User]]]]:
    """Return all teams alongside their active members (excludes soft-deleted)."""
    teams = session.exec(select(Team)).all()
    result: list[tuple[Team, list[tuple[TeamMember, User]]]] = []
    for team in teams:
        members = session.exec(
            select(TeamMember, User)
            .join(User, TeamMember.userId == User.userId)
            .where(TeamMember.teamId == team.teamId, TeamMember.isDeleted == False)  # noqa: E712
        ).all()
        result.append((team, members))
    return result


# ---------------------------------------------------------------------------
# Team-membership operations
# ---------------------------------------------------------------------------


def get_team_member(
    session: Session,
    team_id: int,
    user_id: UUID,
) -> TeamMember | None:
    """Return the membership record for a user in a team, or None."""
    return session.exec(
        select(TeamMember).where(
            TeamMember.teamId == team_id,
            TeamMember.userId == user_id,
        )
    ).first()


def upsert_team_member(
    session: Session,
    team: Team,
    user: User,
    role: str,
) -> TeamMember:
    """Add a user to a team, restoring or re-roling an existing membership.

    Semantics:
      * no membership  -> create with ``role``
      * soft-deleted   -> restore and assign ``role``
      * active but role differs -> update to ``role``
      * active with same role   -> no-op

    The returned membership is flushed so its id is populated, but never
    committed — the caller owns the transaction.
    """
    membership = get_team_member(session, team.teamId, user.userId)

    if membership:
        if membership.isDeleted:
            membership.isDeleted = False
            membership.role = role
            session.add(membership)
            session.flush()
            logger.info(
                "Restored membership: user=%s team=%s role=%s", user.email, team.teamName, role
            )
        elif membership.role != role:
            membership.role = role
            session.add(membership)
            session.flush()
            logger.info(
                "Updated membership role: user=%s team=%s role=%s", user.email, team.teamName, role
            )
        else:
            logger.info(
                "Membership already exists: user=%s team=%s role=%s", user.email, team.teamName, role
            )
        return membership

    membership = TeamMember(
        teamId=team.teamId,
        userId=user.userId,
        role=role,
        isDeleted=False,
    )
    session.add(membership)
    session.flush()
    session.refresh(membership)
    logger.info("Added member: user=%s team=%s role=%s", user.email, team.teamName, role)
    return membership


def remove_team_member(session: Session, team: Team, user: User) -> bool:
    """Soft-delete a membership. Returns True if a member was removed.

    Already-removed or non-existent memberships return False (no-op).
    """
    membership = get_team_member(session, team.teamId, user.userId)

    if membership is None:
        logger.warning("Member not found: user=%s team=%s", user.email, team.teamName)
        return False

    if membership.isDeleted:
        logger.info("Member already removed: user=%s team=%s", user.email, team.teamName)
        return False

    membership.isDeleted = True
    session.add(membership)
    session.flush()
    logger.info("Removed member: user=%s team=%s", user.email, team.teamName)
    return True


def update_team_member_role(
    session: Session,
    team: Team,
    user: User,
    new_role: str,
) -> TeamMember | None:
    """Update a member's role. Returns the updated membership, or None if the
    member does not exist or has been removed."""
    membership = get_team_member(session, team.teamId, user.userId)

    if membership is None:
        logger.warning("Member not found: user=%s team=%s", user.email, team.teamName)
        return None

    if membership.isDeleted:
        logger.warning("Cannot update role of removed member: user=%s", user.email)
        return None

    if membership.role == new_role:
        logger.info("Role already set: user=%s team=%s role=%s", user.email, team.teamName, new_role)
        return membership

    membership.role = new_role
    session.add(membership)
    session.flush()
    logger.info("Updated role: user=%s team=%s role=%s", user.email, team.teamName, new_role)
    return membership