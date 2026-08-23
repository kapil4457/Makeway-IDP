from fastapi import APIRouter, Depends

from dependencies.auth import get_current_user, get_auth_service

from database.models.user import User

from dto.request.login import LoginRequest
from dto.response.login import LoginResponse
from dto.response.current_user import CurrentUserResponse

from service.auth_service import AuthService


router = APIRouter(
    prefix="/auth",
    tags=["User Management"],
)


@router.post("/login",summary="Authenticate user",response_model=LoginResponse)
def login(request: LoginRequest,service: AuthService = Depends(get_auth_service)) -> LoginResponse:
    return service.login(request)


@router.get("/me",summary="Get current authenticated user",response_model=CurrentUserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(
        userId=current_user.userId,
        email=current_user.email,
    )