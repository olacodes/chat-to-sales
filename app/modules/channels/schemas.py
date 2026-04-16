"""
app/modules/channels/schemas.py

Pydantic request/response models for the channels API.
"""

from pydantic import BaseModel, Field, field_validator


class WhatsAppConnectRequest(BaseModel):
    """
    Payload for POST /api/v1/channels/whatsapp/connect.

    tenant_id is passed in the body so that gateway/admin tooling can
    onboard any tenant without needing a JWT subject claim.
    In a multi-admin setup, pull tenant_id from the verified JWT instead.
    """

    tenant_id: str = Field(
        ...,
        min_length=1,
        max_length=36,
        description="UUID of the tenant connecting WhatsApp",
    )
    phone_number_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Meta WhatsApp phone_number_id from the App Dashboard",
    )
    access_token: str = Field(
        ...,
        min_length=10,
        description="Meta System User access token (stored encrypted)",
    )

    @field_validator("tenant_id", "phone_number_id", mode="before")
    @classmethod
    def strip_fields(cls, v: str) -> str:
        return v.strip()


class WhatsAppConnectResponse(BaseModel):
    """Returned after a successful connect or reconnect."""

    status: str = "connected"
    channel: str = "whatsapp"
    phone_number_id: str
    webhook_registered: bool = Field(
        description="Whether the webhook was successfully registered with Meta"
    )
