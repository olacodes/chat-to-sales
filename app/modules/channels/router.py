"""
app/modules/channels/router.py

Channels API — manages per-tenant channel connections.

Endpoints:
  GET  /api/v1/channels
      List all connected channels for the authenticated tenant.
  POST /api/v1/channels/whatsapp/connect
      Connect (or reconnect) a WhatsApp Business account to a tenant.
      Idempotent — safe to call repeatedly (e.g. after token rotation).
"""

from fastapi import APIRouter, Query, status

from app.core.dependencies import CurrentUserDep, DBSessionDep
from app.core.logging import get_logger
from app.modules.channels.repository import ChannelRepository
from app.modules.channels.schemas import (
    ChannelListResponse,
    ChannelOut,
    WhatsAppConnectRequest,
    WhatsAppConnectResponse,
    WhatsAppEmbeddedSignupRequest,
)
from app.modules.channels.service import WhatsAppChannelService

logger = get_logger(__name__)
router = APIRouter(prefix="/channels", tags=["Channels"])


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    summary="List connected channels for a tenant",
)
async def list_channels(
    user: CurrentUserDep,
    db: DBSessionDep,
) -> ChannelListResponse:
    repo = ChannelRepository(db)
    channels = await repo.list_by_tenant(tenant_id=user.tenant_id)
    return ChannelListResponse(
        items=[
            ChannelOut(
                channel=ch.channel,
                phone_number_id=ch.phone_number_id,
                webhook_registered=ch.webhook_registered,
            )
            for ch in channels
        ]
    )


@router.post(
    "/whatsapp/connect",
    status_code=status.HTTP_200_OK,
    summary="Connect WhatsApp Business to a tenant",
    description=(
        "Stores encrypted WhatsApp credentials for the tenant, registers the "
        "webhook with Meta's Graph API v25.0, and emits a `channel.connected` "
        "event. Safe to call repeatedly — repeated requests update credentials "
        "in place without creating duplicates."
    ),
)
async def connect_whatsapp(
    body: WhatsAppConnectRequest,
    user: CurrentUserDep,
    db: DBSessionDep,
) -> WhatsAppConnectResponse:
    svc = WhatsAppChannelService(db)
    return await svc.connect(body)


@router.post(
    "/whatsapp/embedded-signup",
    status_code=status.HTTP_200_OK,
    summary="Connect WhatsApp via Meta Embedded Signup",
    description=(
        "Exchanges the short-lived code returned by the Meta Embedded Signup popup "
        "for an access token, then stores the channel credentials and registers the "
        "webhook. Call this immediately after the Meta popup completes — the code "
        "expires in 30 seconds."
    ),
)
async def connect_whatsapp_embedded_signup(
    body: WhatsAppEmbeddedSignupRequest,
    user: CurrentUserDep,
    db: DBSessionDep,
) -> WhatsAppConnectResponse:
    svc = WhatsAppChannelService(db)
    return await svc.connect_from_embedded_signup(body)
