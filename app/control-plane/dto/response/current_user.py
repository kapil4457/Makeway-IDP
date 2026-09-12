from pydantic import BaseModel, EmailStr
from uuid import UUID


class UserTeamMembership(BaseModel):
    """One active team membership, as shown on the profile page.

    TeamMember rows carry no timestamp column, so there is no memberSince
    to report.
    """

    teamId: int
    teamName: str
    role: str


class CurrentUserResponse(BaseModel):
    userId: UUID
    email: EmailStr
    # Defaults to empty so callers written before teams existed keep working;
    # the /auth/me handler fills it from active TeamMember rows.
    teams: list[UserTeamMembership] = []
