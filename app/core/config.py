from functools import lru_cache
from typing import Annotated, Literal

from pydantic import (
    PostgresDsn,
    RedisDsn,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

# Short-form aliases accepted in ENV/ENVIRONMENT variable
_ENV_ALIASES: dict[str, str] = {
    "dev": "development",
    "prod": "production",
    "stg": "staging",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Also read ENVIRONMENT from the shorter ENV key when present
        env_nested_delimiter="__",
    )

    # ── Application ──────────────────────────────────────────────────────────
    APP_NAME: str = "ChatToSales"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False

    # ── API ───────────────────────────────────────────────────────────────────
    API_PREFIX: str = "/api/v1"
    ALLOWED_HOSTS: list[str] = ["*"]

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/chattosales"
    )

    # ── Redis / Cache ─────────────────────────────────────────────────────────
    REDIS_URL: RedisDsn = RedisDsn("redis://localhost:6379/0")

    # ── WhatsApp / Meta ───────────────────────────────────────────────────────
    WHATSAPP_VERIFY_TOKEN: str = "changeme"
    WHATSAPP_APP_SECRET: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_ACCESS_TOKEN: str = ""

    # ── Tenant ────────────────────────────────────────────────────────────────
    # The default tenant ID used for event routing and listener registration.
    # Must match across the ingestion router and the event listener startup.
    TENANT_ID: str = "tenant-abc-123"

    # ── Paystack ───────────────────────────────────────────────────────────────
    # Set this to your Paystack secret key in production.
    # Leave empty in development to skip webhook signature verification.
    PAYSTACK_SECRET_KEY: str = ""

    # ── Encryption ─────────────────────────────────────────────────────────────
    # Fernet key for encrypting sensitive credentials (e.g. access tokens).
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY: str = ""

    # ── Google OAuth ───────────────────────────────────────────────────────────
    # Your Google OAuth 2.0 Client ID from console.cloud.google.com.
    # When set, Google ID tokens are validated against this audience (aud claim).
    # Leave empty to skip audience validation (development only).
    GOOGLE_CLIENT_ID: str = ""

    # ── App public URL (used for webhook registration) ────────────────────────
    # Set to your public HTTPS URL, e.g. https://chattosales.duckdns.org
    APP_BASE_URL: str = "http://localhost:8000"

    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = "change-this-secret-key-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ── Weekly report ──────────────────────────────────────────────────────────
    # Shared secret for the POST /reports/trigger-weekly endpoint.
    # Set a strong random value in production (e.g. openssl rand -hex 32).
    REPORT_SECRET: str = "change-this-report-secret"

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def normalize_env(cls, v: str) -> str:
        """Accept short forms (dev, prod, stg) and normalise to full form."""
        v = str(v).strip().lower()
        return _ENV_ALIASES.get(v, v)

    @model_validator(mode="after")
    def enforce_production_requirements(self) -> "Settings":
        """Prevent insecure defaults from reaching production."""
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY == "change-this-secret-key-in-production":
                raise ValueError("SECRET_KEY must be overridden in production.")
            if not self.ENCRYPTION_KEY:
                raise ValueError("ENCRYPTION_KEY must be set in production.")
            if self.APP_BASE_URL == "http://localhost:8000":
                raise ValueError(
                    "APP_BASE_URL must be set to the public HTTPS URL in production."
                )
            if self.DEBUG:
                raise ValueError("DEBUG must be False in production.")
        return self

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_staging(self) -> bool:
        return self.ENVIRONMENT == "staging"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def database_url_str(self) -> str:
        """String form of DATABASE_URL — required by SQLAlchemy create_engine."""
        return str(self.DATABASE_URL)

    @property
    def redis_url_str(self) -> str:
        """String form of REDIS_URL — required by redis.asyncio."""
        return str(self.REDIS_URL)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton. Use this everywhere — never instantiate Settings directly."""
    return Settings()
