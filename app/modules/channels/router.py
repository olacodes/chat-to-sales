"""
app/modules/channels/router.py

Channels API — manages per-tenant channel connections.

Endpoints:
  POST /api/v1/channels/whatsapp/connect
      Connect (or reconnect) a WhatsApp Business account to a tenant.
      Idempotent — safe to call repeatedly (e.g. after token rotation).
"""

from fastapi import APIRouter, status

from app.core.dependencies import DBSessionDep
from app.core.logging import get_logger
from app.modules.channels.schemas import WhatsAppConnectRequest, WhatsAppConnectResponse
from app.modules.channels.service import WhatsAppChannelService

logger = get_logger(__name__)
router = APIRouter(prefix="/channels", tags=["Channels"])


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
    db: DBSessionDep,
) -> WhatsAppConnectResponse:
    svc = WhatsAppChannelService(db)
    return await svc.connect(body)
