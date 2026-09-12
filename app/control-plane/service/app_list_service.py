"""Read-side listing for ``GET /app`` — the dashboard's landing grid.

Team-scoped: returns the apps owned by the teams the current user is an
active member of (the same ``TeamMember.isDeleted`` gate the status endpoint's
ownership check enforces). Read-only — no commit, no queue, no side effects;
``AppStatusService`` remains the write-loop's read companion.
"""

from sqlmodel import Session

from database.models.user import User
from dto.response.app_summary import AppSummaryResponse
from repository.app_repository import AppRepository
from repository.team_repository import TeamMemberRepository


class AppListService:

    def __init__(
        self,
        session: Session,
        appRepository: AppRepository,
        teamMemberRepository: TeamMemberRepository,
    ):
        self.session = session
        self.appRepository = appRepository
        self.teamMemberRepository = teamMemberRepository

    def list_apps(self, current_user: User) -> list[AppSummaryResponse]:
        """Apps owned by the user's active teams, most recently modified first."""
        team_ids = self.teamMemberRepository.get_active_team_ids_for_user(
            current_user.userId
        )

        # Team names resolved once per team, not once per row.
        team_names: dict[int, str | None] = {}

        summaries: list[AppSummaryResponse] = []
        for app in self.appRepository.list_by_team_ids(team_ids):
            if app.teamId not in team_names:
                team = self.teamMemberRepository.get_team_by_id(app.teamId)
                team_names[app.teamId] = team.teamName if team else None

            summaries.append(
                AppSummaryResponse(
                    appId=app.appId,
                    appName=app.appName,
                    appRepoUrl=app.appRepoUrl,
                    gitOpsPath=app.gitOpsPath,
                    teamId=app.teamId,
                    teamName=team_names[app.teamId],
                    createdBy=app.createdBy,
                    createdAt=app.createdAt,
                    modifiedBy=app.modifiedBy,
                    modifiedAt=app.modifiedAt,
                )
            )

        return summaries