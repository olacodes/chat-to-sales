"""
app/core/models/user.py

User, Tenant, and UserTenant ORM models.

Design notes:
- User is system-level (no tenant_id on the row itself) because a user can
  belong to multiple tenants via UserTenant.
- Tenant is also system-level — it is its own root aggregate.
- UserTenant is the join table with a role column (owner | member).
- password_hash is nullable to accommodate OAuth-only users.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models.base import BaseModel


# ── Enums ─────────────────────────────────────────────────────────────────────


class AuthProvider(StrEnum):
    EMAIL = "email"
    GOOGLE = "google"


class UserRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


# ── Tenant ────────────────────────────────────────────────────────────────────


class Tenant(BaseModel):
    """
    A tenant represents one business / workspace.

    Every signup creates a new tenant automatically — users are always
    the owner of at least one tenant.
    """

    __tablename__ = "tenants"

    # Human-readable name set during onboarding (optional at signup time).
    name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        comment="Business / workspace display name",
    )

    # Relationships
    user_tenants: Mapped[list["UserTenant"]] = relationship(
        "UserTenant", back_populates="tenant", lazy="selectin"
    )


# ── User ──────────────────────────────────────────────────────────────────────


class User(BaseModel):
    """
    An authenticated principal.

    A user can belong to multiple tenants (e.g. agency staff managing
    several business accounts) via the UserTenant join table.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    email: Mapped[str] = mapped_column(
        String(254),
        nullable=False,
        index=True,
        comment="RFC 5321 email address — unique across all tenants",
    )
    # NULL for Google / OAuth users who have no password.
    password_hash: Mapped[str | None] = mapped_column(
        String(72),  # bcrypt output is always 60 chars; 72 gives headroom
        nullable=True,
        comment="bcrypt hash — NULL for OAuth-only accounts",
    )
    auth_provider: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AuthProvider.EMAIL,
        comment="Primary auth method: email | google",
    )
    # Optional display name — populated from Google profile on OAuth signup.
    display_name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    # Relationships
    user_tenants: Mapped[list["UserTenant"]] = relationship(
        "UserTenant", back_populates="user", lazy="selectin"
    )


# ── UserTenant (join table with role) ─────────────────────────────────────────


class UserTenant(BaseModel):
    """
    Links a user to a tenant with a role.

    A user can be an owner of one tenant and a member of others.
    The first user linked to a tenant is always the owner.
    """

    __tablename__ = "user_tenants"
    __table_args__ = (
        # One membership record per (user, tenant) pair.
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenants_user_tenant"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=UserRole.MEMBER,
        comment="owner | member",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="user_tenants")
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="user_tenants")


# ── InviteToken ───────────────────────────────────────────────────────────────


class InviteToken(BaseModel):
    """
    A single-use invite link token.

    An owner generates a token; the recipient uses it to create their account
    and join the tenant as a member.  No email required — the owner shares the
    URL via WhatsApp/Slack/etc.
    """

    __tablename__ = "invite_tokens"

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        comment="URL-safe random token — treated as a secret",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=UserRole.MEMBER,
        comment="Role to assign when the invite is accepted",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Token expires after this timestamp (UTC)",
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Set when the token is consumed — single-use",
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")
