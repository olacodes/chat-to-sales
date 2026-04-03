from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import DBSessionDep
from app.modules.notifications.schemas import NotificationPayload
from app.modules.notifications.service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _service(db: DBSessionDep) -> NotificationService:
    return NotificationService(db)


ServiceDep = Annotated[NotificationService, Depends(_service)]


@router.post("/send", status_code=202)
async def send_notification(
    body: NotificationPayload, svc: ServiceDep
) -> dict[str, str]:
    await svc.send(body)
    return {"status": "queued"}
