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

import secrets

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ChatToSalesError, ConflictError, TooManyRequestsError, UnauthorizedError
from app.core.logging import get_logger
from app.core.models.user import AuthProvider, UserRole
from app.infra.auth_utils import (
    create_access_token,
    hash_password,
    verify_google_token,
    verify_password,
)
from app.infra.cache import get_redis
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import (
    EmailLoginRequest,
    EmailSignupRequest,
    GoogleLoginRequest,
    GoogleSignupRequest,
    LoginResponse,
    LoginUserInfo,
    OTPRequestRequest,
    OTPRequestResponse,
    OTPVerifyRequest,
    SignupResponse,
)
from app.infra.crypto import decrypt_token
from app.modules.channels.repository import ChannelRepository
from app.modules.onboarding.repository import TraderRepository
from app.modules.orders.repository import OrderRepository

logger = get_logger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AuthRepository(session)
        self._trader_repo = TraderRepository(session)
        self._channel_repo = ChannelRepository(session)

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
            is_superadmin=user.is_superadmin,
        )
        return LoginResponse(
            access_token=token,
            user=LoginUserInfo(user_id=user.id, email=user.email),
            tenant_id=tenant_id,
            is_superadmin=user.is_superadmin,
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
            is_superadmin=user.is_superadmin,
        )
        return LoginResponse(
            access_token=token,
            user=LoginUserInfo(user_id=user.id, email=user.email),
            tenant_id=tenant_id,
            is_superadmin=user.is_superadmin,
        )

    # ── WhatsApp OTP request ──────────────────────────────────────────────────

    async def request_otp(self, req: OTPRequestRequest) -> OTPRequestResponse:
        """
        Generate a 6-digit OTP and deliver it to the trader via WhatsApp.

        Rate-limited to 5 requests per 10 minutes per phone number.
        The OTP is stored in Redis with a 10-minute TTL.

        In development (no WHATSAPP credentials set), the OTP is logged
        instead of sent so testing does not require a live WhatsApp number.
        """
        redis = get_redis()
        otp_key = f"auth:otp:{req.phone_number}"
        attempts_key = f"auth:otp:attempts:{req.phone_number}"

        # Rate limit: max 5 OTP requests per 10-minute window
        attempts = await redis.get(attempts_key)
        if attempts and int(attempts) >= 5:
            raise TooManyRequestsError(
                "Too many OTP requests for this number. Try again in 10 minutes."
            )

        otp = f"{secrets.randbelow(1_000_000):06d}"

        # Store OTP (10 min TTL) and increment request counter
        await redis.setex(otp_key, 600, otp)
        await redis.incr(attempts_key)
        await redis.expire(attempts_key, 600)

        await self._send_otp_whatsapp(req.phone_number, otp)

        return OTPRequestResponse(message="Login code sent to your WhatsApp number.")

    # ── WhatsApp OTP verify ───────────────────────────────────────────────────

    async def verify_otp(self, req: OTPVerifyRequest) -> LoginResponse:
        """
        Validate the OTP and return a JWT session.

        On first login for a phone number:
          - Checks that a Trader profile exists for that number (must have completed
            WhatsApp onboarding first).
          - Creates a User + Tenant for that trader.
          - Updates the Trader row's tenant_id to their new dedicated tenant.

        On subsequent logins:
          - Finds the existing User by phone number and returns a fresh JWT.

        Raises UnauthorizedError (401) for an invalid or expired OTP.
        """
        redis = get_redis()
        otp_key = f"auth:otp:{req.phone_number}"

        stored_otp = await redis.get(otp_key)
        if not stored_otp or stored_otp != req.code:
            raise UnauthorizedError("Invalid or expired login code.")

        # Single-use: delete immediately after a correct match
        await redis.delete(otp_key)

        user = await self._repo.get_user_by_phone(req.phone_number)

        if user is not None:
            # Returning user — find their tenant and issue a fresh token
            membership = await self._repo.get_owner_tenant_or_first(user_id=user.id)
            tenant_id = membership.tenant_id if membership else ""
            logger.info("WhatsApp OTP login — user=%s tenant=%s", user.id, tenant_id)
        else:
            # First login — trader must have completed WhatsApp onboarding
            trader = await self._trader_repo.get_by_phone(req.phone_number)
            if trader is None:
                raise UnauthorizedError(
                    "No trader account found for this number. "
                    "Please complete onboarding on WhatsApp first."
                )

            # Create a dedicated User + Tenant for this trader
            synthetic_email = f"{req.phone_number}@wa.chattosales.com"
            user = await self._repo.create_user(
                email=synthetic_email,
                password_hash=None,
                auth_provider=AuthProvider.WHATSAPP,
                display_name=trader.business_name,
                phone_number=req.phone_number,
            )
            tenant = await self._repo.create_tenant(name=trader.business_name)
            await self._repo.create_user_tenant(
                user_id=user.id,
                tenant_id=tenant.id,
                role=UserRole.OWNER,
            )
            # Migrate orders, conversations, and messages that were created
            # under the shared platform tenant to this trader's new tenant.
            settings = get_settings()
            old_tenant_id = trader.tenant_id or settings.TENANT_ID
            order_repo = OrderRepository(self._session)
            migrated = await order_repo.migrate_trader_orders_to_tenant(
                trader_phone=req.phone_number,
                old_tenant_id=old_tenant_id,
                new_tenant_id=tenant.id,
            )

            # Point the trader's record at their own dedicated tenant so the
            # dashboard and channel connection work against the right tenant.
            await self._trader_repo.update_tenant_id(
                phone_number=req.phone_number,
                tenant_id=tenant.id,
            )

            # Bust stale Redis caches so the order handler picks up the new tenant
            await self._bust_trader_caches(
                phone_number=req.phone_number,
                old_tenant_id=old_tenant_id,
                store_slug=trader.store_slug,
            )

            tenant_id = tenant.id
            logger.info(
                "WhatsApp OTP first login — created user=%s tenant=%s "
                "trader_phone=%s migrated_orders=%d",
                user.id,
                tenant_id,
                req.phone_number,
                migrated,
            )

        token = create_access_token(
            user_id=user.id,
            tenant_id=tenant_id,
            email=user.email,
            is_superadmin=user.is_superadmin,
        )
        return LoginResponse(
            access_token=token,
            user=LoginUserInfo(user_id=user.id, email=user.email),
            tenant_id=tenant_id,
            is_superadmin=user.is_superadmin,
        )

    # ── Internal: Redis cache busting ─────────────────────────────────────────

    async def _bust_trader_caches(
        self,
        *,
        phone_number: str,
        old_tenant_id: str,
        store_slug: str | None,
    ) -> None:
        """Delete stale Redis caches after tenant_id migration."""
        redis = get_redis()
        keys_to_delete = [
            f"trader:phone:{phone_number}",
            f"trader:tenant:{old_tenant_id}",
        ]
        if store_slug:
            keys_to_delete.append(f"trader:slug:{store_slug}")
        for key in keys_to_delete:
            await redis.delete(key)
        logger.debug(
            "Busted %d Redis trader cache keys for phone=%s",
            len(keys_to_delete),
            phone_number,
        )

    # ── Internal: OTP WhatsApp delivery ──────────────────────────────────────

    async def _send_otp_whatsapp(self, phone_number: str, otp: str) -> None:
        """
        Send the OTP via WhatsApp.

        Credential resolution (in order):
          1. Platform tenant's channel record in tenant_channels (same live
             token used by NotificationService — stays fresh automatically).
          2. WHATSAPP_PHONE_NUMBER_ID + WHATSAPP_ACCESS_TOKEN from env (fallback).
          3. Neither set → dev mode, OTP is logged instead of sent.
        """
        settings = get_settings()

        # ── Resolve credentials ────────────────────────────────────────────────
        wa_phone_id: str | None = None
        wa_token: str | None = None

        # Try the platform tenant's channel record first
        platform_tenant = settings.TENANT_ID
        if platform_tenant:
            channel = await self._channel_repo.get_by_tenant_and_channel(
                tenant_id=platform_tenant,
                channel="whatsapp",
            )
            if channel and channel.encrypted_access_token:
                wa_phone_id = channel.phone_number_id
                wa_token = decrypt_token(channel.encrypted_access_token)

        # Fall back to env vars
        if not wa_phone_id or not wa_token:
            wa_phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
            wa_token = settings.WHATSAPP_ACCESS_TOKEN

        if not wa_phone_id or not wa_token:
            logger.warning(
                "WhatsApp credentials not configured — OTP not sent (dev mode). "
                "phone=%s code=%s",
                phone_number,
                otp,
            )
            return

        # ── Send ───────────────────────────────────────────────────────────────
        frontend_url = settings.FRONTEND_URL.rstrip("/")
        login_link = f"{frontend_url}/login?code={otp}&phone={phone_number}"

        message_text = (
            f"Tap to log in to ChatToSales:\n"
            f"{login_link}\n\n"
            f"Or enter this code manually: *{otp}*\n\n"
            "This link expires in 10 minutes. Do not share it."
        )
        url = f"https://graph.facebook.com/v25.0/{wa_phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {wa_token}",
            "Content-Type": "application/json",
        }
        body = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {"body": message_text},
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=headers, json=body)

        if not response.is_success:
            logger.error(
                "Failed to send OTP WhatsApp to phone=%s status=%s body=%s",
                phone_number,
                response.status_code,
                response.text[:200],
            )
            raise ChatToSalesError(
                "Could not deliver the login code right now. Please try again shortly.",
                status_code=502,
            )
