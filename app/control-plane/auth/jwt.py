import os
from datetime import datetime, timedelta, timezone
import jwt


JWT_SECRET_KEY = os.environ.get(
    "JWT_SECRET_KEY",
    "JWT_SECRET_KEY",
)

JWT_ALGORITHM =  os.environ.get(
    "JWT_ALGORITHM",
    "HS256",
)

JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.environ.get(
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        "30",
    )
)


def create_access_token(user_id: str,email: str,) -> str:

    now = datetime.now(timezone.utc)

    expires_at = now + timedelta(
        minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": expires_at,
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict:

    return jwt.decode(
        token,
        JWT_SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
    )