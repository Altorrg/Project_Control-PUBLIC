from __future__ import annotations

from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .kozos import ApiModel, ShortText


class LoginRequest(ApiModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("Hibás e-mail-formátum.")
        return value


class PasswordChangeRequest(ApiModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=12, max_length=200)
    new_password_confirmation: str = Field(min_length=12, max_length=200)

    @model_validator(mode="after")
    def validate_password_change(self) -> "PasswordChangeRequest":
        if self.new_password != self.new_password_confirmation:
            raise ValueError("Az új jelszó és a megerősítés nem egyezik.")
        if self.current_password == self.new_password:
            raise ValueError("Az új jelszónak különböznie kell a jelenlegi jelszótól.")
        return self


class Profile(ApiModel):
    id: UUID
    display_name: ShortText
    role: ShortText
    active: bool = True


class SessionInfo(ApiModel):
    profile: Profile
    csrf_token: str
    expires_in: int
