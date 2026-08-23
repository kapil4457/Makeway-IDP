from dto.request.login import LoginRequest
from dto.response.login import LoginResponse

from exceptions.base import UnauthorizedException

from auth.jwt import create_access_token
from repository.user_repository import UserRepository

from pwdlib import PasswordHash


password_hash = PasswordHash.recommended()


class AuthService:

    def __init__(self,repository: UserRepository):
        self.repository = repository

    def login(self,request: LoginRequest) -> LoginResponse:

        user = self.repository.get_by_email(str(request.email))

        if user is None:
            raise UnauthorizedException(
                message="Invalid email or password.",
                error_code="INVALID_CREDENTIALS",
            )

        if not password_hash.verify(request.password,user.passwordHash,):
            raise UnauthorizedException(
                message="Invalid email or password.",
                error_code="INVALID_CREDENTIALS",
            )

        token = create_access_token(user_id=user.userId,email=user.email,)

        return LoginResponse(access_token=token)