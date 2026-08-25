from sqlmodel import Session, select

from database.models.team import Team
from database.models.team_member import TeamMember


class TeamMemberRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_by_user_and_team(
        self,
        user_id,
        team_name: str,
    ) -> bool:
        """
        Check if a user is a member of a team where isDeleted=0.

        Returns True if the user is an active member of the specified team.
        """
        statement = select(TeamMember).where(
            TeamMember.isDeleted == False,
            TeamMember.userId == user_id,
        )
        teammembers = self.session.exec(statement).all()

        for tm in teammembers:
            team_statement = select(Team).where(Team.teamId == tm.teamId)
            team = self.session.exec(team_statement).first()
            if team and team.teamName == team_name:
                return True

        return False

    def get_team_id_by_name(self, team_name: str) -> int | None:
        """
        Get the team ID by team name.
        """
        statement = select(Team).where(Team.teamName == team_name)
        team = self.session.exec(statement).first()
        if team:
            return team.teamId
        return None