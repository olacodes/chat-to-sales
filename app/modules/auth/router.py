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
    OTPRequestRequest,
    OTPRequestResponse,
    OTPVerifyRequest,
    PhoneSignupRequest,
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


@router.post(
    "/signup/phone",
    status_code=status.HTTP_200_OK,
    summary="Sign up with phone — creates Trader store + sends OTP",
    description=(
        "Creates a Trader profile (store) for the given phone number, then sends "
        "a 6-digit OTP for verification. If a Trader already exists for this "
        "number, skips creation and just sends the OTP. "
        "After this, call /otp/verify to complete signup and get a JWT."
    ),
)
async def signup_phone(
    body: PhoneSignupRequest,
    db: DBSessionDep,
) -> OTPRequestResponse:
    import json
    from app.modules.onboarding.repository import TraderRepository
    from app.modules.onboarding.service import _generate_unique_slug
    from app.modules.orders.session import cache_trader_by_phone
    from app.modules.onboarding.analytics import (
        EVT_STARTED, EVT_COMPLETED, EVT_PATH_CHOSEN, track_onboarding_event,
    )

    trader_repo = TraderRepository(db)
    existing = await trader_repo.get_by_phone(body.phone_number)

    if existing is None:
        # Build catalogue
        catalogue_dict = {p.name: p.price for p in body.products} if body.products else {}
        catalogue_json = json.dumps(catalogue_dict) if catalogue_dict else None

        slug = await _generate_unique_slug(trader_repo, body.business_name)
        await trader_repo.create(
            phone_number=body.phone_number,
            business_name=body.business_name,
            business_category=body.business_category,
            store_slug=slug,
            onboarding_catalogue=catalogue_json,
        )
        await db.commit()

        # Cache trader identity
        await cache_trader_by_phone(body.phone_number, {
            "tenant_id": "",
            "phone_number": body.phone_number,
            "business_name": body.business_name,
            "business_category": body.business_category,
            "store_slug": slug,
            "catalogue": catalogue_dict,
        })

        # Track analytics
        path = "web_products" if body.products else "web_skip"
        await track_onboarding_event(phone_number=body.phone_number, event_type=EVT_STARTED, step_name="web_signup")
        await track_onboarding_event(phone_number=body.phone_number, event_type=EVT_PATH_CHOSEN, step_name="catalogue_path", path=path)
        await track_onboarding_event(phone_number=body.phone_number, event_type=EVT_COMPLETED, step_name="completed", path=path)

        logger.info("Phone signup: trader created phone=%s slug=%s", body.phone_number, slug)

    # Send OTP (reuse existing logic)
    svc = AuthService(db)
    return await svc.request_otp(OTPRequestRequest(phone_number=body.phone_number))


@router.post(
    "/otp/request",
    status_code=status.HTTP_200_OK,
    summary="Request a WhatsApp OTP",
    description=(
        "Sends a 6-digit one-time code to the given WhatsApp number. "
        "The code expires in 10 minutes. "
        "Rate-limited to 5 requests per 10-minute window per number. "
        "Returns 429 if the limit is exceeded."
    ),
)
async def otp_request(
    body: OTPRequestRequest,
    db: DBSessionDep,
) -> OTPRequestResponse:
    svc = AuthService(db)
    return await svc.request_otp(body)


@router.post(
    "/otp/verify",
    status_code=status.HTTP_200_OK,
    summary="Verify a WhatsApp OTP and log in",
    description=(
        "Validates the 6-digit OTP sent by /otp/request and returns a JWT session. "
        "On first login, creates a User and Tenant for the trader. "
        "The trader must have completed WhatsApp onboarding first. "
        "Returns 401 for an invalid or expired code."
    ),
)
async def otp_verify(
    body: OTPVerifyRequest,
    db: DBSessionDep,
) -> LoginResponse:
    svc = AuthService(db)
    return await svc.verify_otp(body)
