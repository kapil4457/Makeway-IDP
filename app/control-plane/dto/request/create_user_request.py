from pydantic import BaseModel, EmailStr, Field


class CreateUserRequest(BaseModel):

    email: EmailStr
    password: str = Field(min_length=8)