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

    # ── Paystack ───────────────────────────────────────────────────────────────
    # Set this to your Paystack secret key in production.
    # Leave empty in development to skip webhook signature verification.
    PAYSTACK_SECRET_KEY: str = ""

    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = "change-this-secret-key-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

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
