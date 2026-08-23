from sqlmodel import Field, UniqueConstraint, SQLModel
from uuid import UUID

class TeamMember(SQLModel, table=True):
    teamMemberId: int = Field(primary_key=True)
    role: str = Field(default="member", index=True)
    isDeleted: bool = Field(default=False, index=True)

    teamId: int = Field(nullable=False, foreign_key="team.teamId", index=True)
    userId: UUID = Field(nullable=False, foreign_key="user.userId", index=True)

    __table_args__ = (
        UniqueConstraint("teamId", "userId", name="uq_teammember_team_user"),
    )