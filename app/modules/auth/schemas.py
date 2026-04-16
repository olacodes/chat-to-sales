"""\napp/modules/auth/schemas.py\n\nPydantic request/response models for the auth endpoints.\n"""

import re

from pydantic import BaseModel, EmailStr, Field, field_validator

# Minimum password requirements:
# - At least 8 characters
# - At least one letter and one digit
# bcrypt silently truncates passwords > 72 bytes — we reject them explicitly
# so users are aware their full password is not being hashed.
_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 72  # bcrypt hard limit
_PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")


class EmailSignupRequest(BaseModel):
    """POST /api/v1/auth/signup/email"""

    email: EmailStr = Field(..., description="Valid email address")
    password: str = Field(
        ...,
        min_length=_MIN_PASSWORD_LENGTH,
        max_length=_MAX_PASSWORD_LENGTH,
        description="8–72 chars, must contain a letter and a digit",
    )

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not _PASSWORD_RE.match(v):
            raise ValueError(
                "Password must be at least 8 characters and contain at least "
                "one letter and one digit."
            )
        return v


class GoogleSignupRequest(BaseModel):
    """POST /api/v1/auth/signup/google"""

    id_token: str = Field(
        ..., min_length=10, description="Google ID token from the frontend"
    )


class SignupResponse(BaseModel):
    """Returned by both signup endpoints."""

    user_id: str
    tenant_id: str
    email: str
    auth_provider: str
    access_token: str = Field(
        description="JWT bearer token — include as Authorization: Bearer <token>"
    )


# ── Login schemas ─────────────────────────────────────────────────────────────


class EmailLoginRequest(BaseModel):
    """POST /api/v1/auth/login/email"""

    email: EmailStr = Field(..., description="Registered email address")
    password: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_PASSWORD_LENGTH,
        description="Account password",
    )


class GoogleLoginRequest(BaseModel):
    """POST /api/v1/auth/login/google"""

    id_token: str = Field(
        ..., min_length=10, description="Google ID token from the frontend"
    )


class LoginUserInfo(BaseModel):
    user_id: str
    email: str


class LoginResponse(BaseModel):
    """Returned by both login endpoints."""

    access_token: str
    token_type: str = "bearer"
    user: LoginUserInfo
    tenant_id: str
