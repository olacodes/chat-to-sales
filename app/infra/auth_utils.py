"""
app/infra/auth_utils.py

Low-level authentication utilities:
  - Password hashing / verification (bcrypt via passlib)
  - JWT access token creation / decoding (python-jose)
  - Google ID token verification (via Google's tokeninfo endpoint)

These are infrastructure concerns kept separate from business logic so
they can be swapped (e.g. argon2, RS256 keys) without touching the service.
"""

from datetime import datetime, timedelta, timezone

import httpx
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Password hashing ──────────────────────────────────────────────────────────

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return a bcrypt hash of the plaintext password."""
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Return True if password matches the stored bcrypt hash."""
    return _pwd_context.verify(password, hashed)


# ── JWT ───────────────────────────────────────────────────────────────────────

_ALGORITHM = "HS256"


def create_access_token(*, user_id: str, tenant_id: str, email: str) -> str:
    """
    Create a signed JWT access token.

    Claims:
      sub       — user_id (standard JWT subject)
      tenant_id — injected so downstream handlers can read it without a DB hit
      email     — for convenience; not used for auth decisions
      exp       — expiry based on ACCESS_TOKEN_EXPIRE_MINUTES setting
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "email": email,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decode and verify a JWT access token.

    Raises:
        JWTError: if the token is invalid or expired.
    """
    settings = get_settings()
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[_ALGORITHM])


# ── Google ID token verification ──────────────────────────────────────────────

# Google's public tokeninfo endpoint — validates and decodes an id_token
# without requiring the google-auth library as a dependency.
_GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
_GOOGLE_TOKEN_TIMEOUT = 5.0


async def verify_google_token(id_token: str) -> dict:
    """
    Verify a Google ID token and return its claims.

    Calls Google's tokeninfo endpoint which validates the signature,
    expiry, and audience server-side so we never accept a forged token.

    Returns a dict with at minimum:
        {
            "email": "user@example.com",
            "name":  "Full Name",        # may be absent for some accounts
            "sub":   "google_user_id",
        }

    Raises:
        ValueError: if the token is invalid, expired, or Google is unreachable.

    Production note: For higher throughput, swap this for the google-auth
    library (google.oauth2.id_token.verify_oauth2_token) which validates
    locally using Google's public certs and avoids a network round-trip.
    The interface is identical — only this function needs to change.
    """
    settings = get_settings()

    try:
        async with httpx.AsyncClient(timeout=_GOOGLE_TOKEN_TIMEOUT) as client:
            response = await client.get(
                _GOOGLE_TOKENINFO_URL,
                params={"id_token": id_token},
            )
    except httpx.RequestError as exc:
        logger.error("Google tokeninfo request failed: %s", exc)
        raise ValueError("Could not reach Google to verify token") from exc

    if response.status_code != 200:
        logger.warning(
            "Google tokeninfo rejected token — status=%d body=%s",
            response.status_code,
            response.text[:200],
        )
        raise ValueError("Invalid or expired Google ID token")

    claims = response.json()

    # Validate audience when GOOGLE_CLIENT_ID is configured.
    # This prevents a token issued for a different app from being accepted.
    client_id = settings.GOOGLE_CLIENT_ID
    if client_id and claims.get("aud") != client_id:
        raise ValueError("Google token audience mismatch — wrong client_id")

    email = claims.get("email")
    if not email:
        raise ValueError("Google token missing email claim")

    return {
        "email": email,
        "name": claims.get("name", ""),
        "sub": claims.get("sub", ""),
    }
