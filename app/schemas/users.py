from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=8)
    role_codes: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    full_name: str | None = None
    is_active: bool | None = None
    role_codes: list[str] | None = None
    password: str | None = Field(default=None, min_length=8)


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    is_active: bool
    roles: list[str]

    model_config = {"from_attributes": True}
