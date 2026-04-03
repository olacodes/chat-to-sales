from enum import StrEnum

from pydantic import BaseModel


class NotificationChannel(StrEnum):
    WHATSAPP = "whatsapp"
    SMS = "sms"
    EMAIL = "email"


class NotificationPayload(BaseModel):
    recipient: str  # phone number or email
    channel: NotificationChannel
    template_name: str
    variables: dict[str, str] = {}
