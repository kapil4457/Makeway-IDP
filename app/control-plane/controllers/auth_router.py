from fastapi import APIRouter, Depends

from dependencies.auth import get_current_user, get_auth_service
from dependencies.app import get_team_member_repository

from database.models.user import User

from dto.request.login import LoginRequest
from dto.response.login import LoginResponse
from dto.response.current_user import CurrentUserResponse, UserTeamMembership

from service.auth_service import AuthService
from repository.team_repository import TeamMemberRepository


router = APIRouter(
    prefix="/auth",
    tags=["User Management"],
)


@router.post("/login",summary="Authenticate user",response_model=LoginResponse)
def login(request: LoginRequest,service: AuthService = Depends(get_auth_service)) -> LoginResponse:
    return service.login(request)


@router.get("/me",summary="Get current authenticated user",response_model=CurrentUserResponse)
def get_me(
    current_user: User = Depends(get_current_user),
    teamMemberRepository: TeamMemberRepository = Depends(get_team_member_repository),
) -> CurrentUserResponse:
    teams: list[UserTeamMembership] = []
    for membership in teamMemberRepository.get_active_memberships_for_user(
        current_user.userId
    ):
        team = teamMemberRepository.get_team_by_id(membership.teamId)
        if team is None:
            continue
        teams.append(UserTeamMembership(
            teamId=team.teamId,
            teamName=team.teamName,
            role=membership.role,
        ))

    return CurrentUserResponse(
        userId=current_user.userId,
        email=current_user.email,
        teams=teams,
    )