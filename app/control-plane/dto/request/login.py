from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr = Field(
        description="User email address",
        examples=["admin@example.com"]
    )

    password: str = Field(
        min_length=1,
        description="User password"
    )