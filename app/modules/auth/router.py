"""
app/modules/auth/router.py

Auth endpoints — signup and login with email or Google.

Routes:
  POST /api/v1/auth/signup/email   — email + password registration
  POST /api/v1/auth/signup/google  — Google ID token registration / login
  POST /api/v1/auth/login/email    — email + password authentication
  POST /api/v1/auth/login/google   — Google ID token authentication
"""

from fastapi import APIRouter, status

from app.core.dependencies import DBSessionDep
from app.core.logging import get_logger
from app.modules.auth.schemas import (
    EmailLoginRequest,
    EmailSignupRequest,
    GoogleLoginRequest,
    GoogleSignupRequest,
    LoginResponse,
    SignupResponse,
)
from app.modules.auth.service import AuthService

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/signup/email",
    status_code=status.HTTP_201_CREATED,
    summary="Sign up with email and password",
    description=(
        "Creates a new user account and a linked tenant. "
        "Returns a JWT access token so the user is immediately authenticated. "
        "Returns 409 if the email is already registered."
    ),
)
async def signup_email(
    body: EmailSignupRequest,
    db: DBSessionDep,
) -> SignupResponse:
    svc = AuthService(db)
    return await svc.email_signup(body)


@router.post(
    "/signup/google",
    status_code=status.HTTP_200_OK,
    summary="Sign up or log in with Google",
    description=(
        "Verifies a Google ID token from the frontend. "
        "Creates a new user + tenant on first call; returns existing user data "
        "on subsequent calls (idempotent). "
        "Returns 401 if the token is invalid or expired."
    ),
)
async def signup_google(
    body: GoogleSignupRequest,
    db: DBSessionDep,
) -> SignupResponse:
    svc = AuthService(db)
    return await svc.google_signup(body)


@router.post(
    "/login/email",
    status_code=status.HTTP_200_OK,
    summary="Log in with email and password",
    description=(
        "Authenticates an existing email/password account. "
        "Returns a JWT access token on success. "
        "Returns 401 for invalid credentials (error message is intentionally vague "
        "to prevent user enumeration)."
    ),
)
async def login_email(
    body: EmailLoginRequest,
    db: DBSessionDep,
) -> LoginResponse:
    svc = AuthService(db)
    return await svc.email_login(body)


@router.post(
    "/login/google",
    status_code=status.HTTP_200_OK,
    summary="Log in with Google",
    description=(
        "Authenticates an existing user via a Google ID token. "
        "Unlike /signup/google, this endpoint does NOT create new accounts — "
        "the user must have signed up first. "
        "Returns 401 if the token is invalid or the account does not exist."
    ),
)
async def login_google(
    body: GoogleLoginRequest,
    db: DBSessionDep,
) -> LoginResponse:
    svc = AuthService(db)
    return await svc.google_login(body)
