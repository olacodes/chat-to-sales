"""
app/modules/channels/repository.py

Data-access layer for TenantChannel.

All methods are scoped by tenant_id. The upsert logic uses a
SELECT-then-INSERT-or-UPDATE pattern which is compatible with all
async SQLAlchemy backends and avoids dialect-specific ON CONFLICT syntax.
The database UniqueConstraint acts as a safety net against races.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.channels.models import ChannelName, TenantChannel

logger = get_logger(__name__)


class ChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_tenant_and_channel(
        self,
        *,
        tenant_id: str,
        channel: str,
    ) -> TenantChannel | None:
        """Return the channel record for a tenant, or None if not exists."""
        result = await self._session.execute(
            select(TenantChannel).where(
                TenantChannel.tenant_id == tenant_id,
                TenantChannel.channel == channel,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_phone_number_id(
        self,
        *,
        phone_number_id: str,
        channel: str = "whatsapp",
    ) -> TenantChannel | None:
        """
        Look up a channel record by Meta phone_number_id.

        Used by the inbound webhook to resolve which tenant owns the
        receiving phone number, enabling multi-tenant routing.
        """
        result = await self._session.execute(
            select(TenantChannel).where(
                TenantChannel.phone_number_id == phone_number_id,
                TenantChannel.channel == channel,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        tenant_id: str,
        channel: str,
        phone_number_id: str,
        encrypted_access_token: str,
        webhook_registered: bool,
    ) -> tuple[TenantChannel, bool]:
        """
        Insert a new channel record or update the existing one.

        Returns (TenantChannel, created: bool).
        created=True means a new row was inserted; False means an existing row
        was updated. Both outcomes are semantically successful.
        """
        existing = await self.get_by_tenant_and_channel(
            tenant_id=tenant_id,
            channel=channel,
        )

        if existing:
            # UPDATE — overwrite token and phone_number_id in case of rotation
            existing.phone_number_id = phone_number_id
            existing.encrypted_access_token = encrypted_access_token
            existing.webhook_registered = webhook_registered
            await self._session.flush()
            logger.debug(
                "TenantChannel updated tenant=%s channel=%s", tenant_id, channel
            )
            return existing, False

        # INSERT
        record = TenantChannel(
            tenant_id=tenant_id,
            channel=channel,
            phone_number_id=phone_number_id,
            encrypted_access_token=encrypted_access_token,
            webhook_registered=webhook_registered,
        )
        self._session.add(record)
        await self._session.flush()
        logger.debug(
            "TenantChannel created id=%s tenant=%s channel=%s",
            record.id,
            tenant_id,
            channel,
        )
        return record, True
