from pydantic import BaseModel, EmailStr
from uuid import UUID

class CurrentUserResponse(BaseModel):
    userId: UUID
    email: EmailStr