from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from uuid import UUID
import jwt

from auth.jwt import decode_access_token


class AuthInterceptor(BaseHTTPMiddleware):

    async def dispatch(self,request: Request,call_next):

        authorization = request.headers.get("Authorization")

        # No token supplied.
        # Protected endpoints will be handled by
        # get_current_user().
        if not authorization:
            return await call_next(request)

        if not authorization.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "error": {
                        "code": "INVALID_AUTHORIZATION_HEADER",
                        "message": "Invalid Authorization header.",
                        "details": [],
                    },
                },
            )

        token = authorization.removeprefix("Bearer ").strip()

        if not token:
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "error": {
                        "code": "MISSING_TOKEN",
                        "message": "Authentication token is missing.",
                        "details": [],
                    },
                },
            )

        try:
            payload = decode_access_token(token)

            request.state.user_id = UUID(payload["sub"])

            request.state.user_email = payload.get(
                "email"
            )

        except (
            jwt.ExpiredSignatureError,
            jwt.InvalidTokenError,
            KeyError,
            ValueError,
        ):
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "error": {
                        "code": "INVALID_TOKEN",
                        "message": "Invalid or expired authentication token.",
                        "details": [],
                    },
                },
            )

        return await call_next(request)