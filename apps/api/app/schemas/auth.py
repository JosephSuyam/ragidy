from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import NO_NUL


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128, pattern=NO_NUL)


class LoginRequest(BaseModel):
    # Plain str, so a malformed email gets the same 401 as a wrong one; only NUL gets a 422.
    # Capped like EmailStr, because each failed login keeps its email as a lockout key.
    email: str = Field(max_length=254, pattern=NO_NUL)
    password: str = Field(max_length=128, pattern=NO_NUL)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str


class ProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
