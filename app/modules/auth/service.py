"""
app/modules/auth/service.py

AuthService — orchestrates the signup and login flows.

Flows:
  email_signup()  — validate → hash password → create user + tenant + link → JWT
  google_signup() — verify token → idempotent user lookup → create if new → JWT
  email_login()   — look up user → verify password → resolve tenant → JWT
  google_login()  — verify token → look up user (must exist) → resolve tenant → JWT

Design rules:
  - Service layer owns all business logic (not the router).
  - DB operations run inside the session from the request scope (committed by
    the get_db dependency on success, rolled back on exception).
  - JWT is generated here so a freshly signed-up user is immediately
    authenticated without a round-trip login.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.logging import get_logger
from app.core.models.user import AuthProvider, UserRole
from app.infra.auth_utils import (
    create_access_token,
    hash_password,
    verify_google_token,
    verify_password,
)
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import (
    EmailLoginRequest,
    EmailSignupRequest,
    GoogleLoginRequest,
    GoogleSignupRequest,
    LoginResponse,
    LoginUserInfo,
    SignupResponse,
)

logger = get_logger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = AuthRepository(session)

    # ── Email signup ──────────────────────────────────────────────────────────

    async def email_signup(self, req: EmailSignupRequest) -> SignupResponse:
        """
        Register a new user with email + password.

        Raises ConflictError (409) if the email is already registered.
        """
        # Step 1 — Duplicate check
        existing = await self._repo.get_user_by_email(req.email)
        if existing:
            raise ConflictError(f"An account with email '{req.email}' already exists.")

        # Step 2 — Hash password (never stored in plaintext)
        pw_hash = hash_password(req.password)

        # Step 3 — Create user
        user = await self._repo.create_user(
            email=req.email,
            password_hash=pw_hash,
            auth_provider=AuthProvider.EMAIL,
        )

        # Step 4 — Create tenant (one per signup — the user is the owner)
        tenant = await self._repo.create_tenant()

        # Step 5 — Link user → tenant as owner
        await self._repo.create_user_tenant(
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserRole.OWNER,
        )

        logger.info("Email signup complete — user=%s tenant=%s", user.id, tenant.id)

        token = create_access_token(
            user_id=user.id,
            tenant_id=tenant.id,
            email=user.email,
        )

        return SignupResponse(
            user_id=user.id,
            tenant_id=tenant.id,
            email=user.email,
            auth_provider=AuthProvider.EMAIL,
            access_token=token,
        )

    # ── Google signup ─────────────────────────────────────────────────────────

    async def google_signup(self, req: GoogleSignupRequest) -> SignupResponse:
        """
        Register (or idempotently log in) via Google ID token.

        - If the email already exists → return the existing user's data (login).
        - If new → create user + tenant + link.

        Idempotent: repeated calls with the same Google account are safe.

        Raises UnauthorizedError (401) if the token is invalid.
        """
        # Step 1 — Verify token with Google
        try:
            claims = await verify_google_token(req.id_token)
        except ValueError as exc:
            raise UnauthorizedError(str(exc)) from exc

        email: str = claims["email"]
        display_name: str = claims.get("name", "")

        # Step 2 — Check if user already exists (idempotency)
        existing = await self._repo.get_user_by_email(email)
        if existing:
            # User exists — find their primary tenant and return a fresh JWT.
            membership = await self._repo.get_user_tenant(user_id=existing.id)
            tenant_id = membership.tenant_id if membership else ""
            logger.info(
                "Google signup — existing user logged in user=%s tenant=%s",
                existing.id,
                tenant_id,
            )
            token = create_access_token(
                user_id=existing.id,
                tenant_id=tenant_id,
                email=existing.email,
            )
            return SignupResponse(
                user_id=existing.id,
                tenant_id=tenant_id,
                email=existing.email,
                auth_provider=existing.auth_provider,
                access_token=token,
            )

        # Step 3 — New user: create user + tenant + link
        user = await self._repo.create_user(
            email=email,
            password_hash=None,  # Google users have no password
            auth_provider=AuthProvider.GOOGLE,
            display_name=display_name or None,
        )
        tenant = await self._repo.create_tenant(name=display_name or None)
        await self._repo.create_user_tenant(
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserRole.OWNER,
        )

        logger.info("Google signup complete — user=%s tenant=%s", user.id, tenant.id)

        token = create_access_token(
            user_id=user.id,
            tenant_id=tenant.id,
            email=user.email,
        )

        return SignupResponse(
            user_id=user.id,
            tenant_id=tenant.id,
            email=user.email,
            auth_provider=AuthProvider.GOOGLE,
            access_token=token,
        )

    # ── Email login ───────────────────────────────────────────────────────────

    async def email_login(self, req: EmailLoginRequest) -> LoginResponse:
        """
        Authenticate an email/password user.

        Raises UnauthorizedError (401) on bad credentials (deliberately vague
        to prevent user enumeration).
        """
        _invalid = "Invalid email or password."

        user = await self._repo.get_user_by_email(req.email)
        if not user or user.auth_provider != AuthProvider.EMAIL:
            raise UnauthorizedError(_invalid)

        if not user.password_hash or not verify_password(
            req.password, user.password_hash
        ):
            raise UnauthorizedError(_invalid)

        membership = await self._repo.get_owner_tenant_or_first(user_id=user.id)
        tenant_id = membership.tenant_id if membership else ""

        logger.info("Email login — user=%s tenant=%s", user.id, tenant_id)

        token = create_access_token(
            user_id=user.id,
            tenant_id=tenant_id,
            email=user.email,
        )
        return LoginResponse(
            access_token=token,
            user=LoginUserInfo(user_id=user.id, email=user.email),
            tenant_id=tenant_id,
        )

    # ── Google login ──────────────────────────────────────────────────────────

    async def google_login(self, req: GoogleLoginRequest) -> LoginResponse:
        """
        Authenticate a Google user.

        Unlike google_signup() this does NOT create a new user — use
        /signup/google for first-time registration.

        Raises UnauthorizedError (401) if the token is invalid or the account
        does not exist.
        """
        try:
            claims = await verify_google_token(req.id_token)
        except ValueError as exc:
            raise UnauthorizedError(str(exc)) from exc

        email: str = claims["email"]
        user = await self._repo.get_user_by_email(email)
        if not user:
            raise UnauthorizedError(
                "No account found for this Google account. Please sign up first."
            )

        membership = await self._repo.get_owner_tenant_or_first(user_id=user.id)
        tenant_id = membership.tenant_id if membership else ""

        logger.info("Google login — user=%s tenant=%s", user.id, tenant_id)

        token = create_access_token(
            user_id=user.id,
            tenant_id=tenant_id,
            email=user.email,
        )
        return LoginResponse(
            access_token=token,
            user=LoginUserInfo(user_id=user.id, email=user.email),
            tenant_id=tenant_id,
        )
