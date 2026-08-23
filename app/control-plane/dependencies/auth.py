from fastapi import Depends, Request
from sqlmodel import Session

from database.db_engine import get_session
from database.models.user import User

from exceptions.base import UnauthorizedException

from repository.user_repository import UserRepository
from service.auth_service import AuthService
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer()


def get_user_repository(session: Session = Depends(get_session)) -> UserRepository:
    return UserRepository(session)


def get_auth_service(repository: UserRepository = Depends(get_user_repository)) -> AuthService:
    return AuthService(repository)


def get_current_user( request: Request,
                      repository: UserRepository = Depends(get_user_repository), 
                      credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> User:

    user_id = getattr( request.state, "user_id", None)

    if user_id is None:
        raise UnauthorizedException(
            message="Authentication is required.",
            error_code="AUTHENTICATION_REQUIRED",
        )

    user = repository.get_by_id(user_id)

    if user is None:
        raise UnauthorizedException(
            message="Authenticated user no longer exists.",
            error_code="USER_NOT_FOUND",
        )

    return user