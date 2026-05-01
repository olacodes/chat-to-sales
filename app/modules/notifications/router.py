from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUserDep, DBSessionDep
from app.modules.notifications.schemas import NotificationPayload
from app.modules.notifications.service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _service(db: DBSessionDep) -> NotificationService:
    return NotificationService(db)


ServiceDep = Annotated[NotificationService, Depends(_service)]


@router.post("/send", status_code=202)
async def send_notification(
    body: NotificationPayload, user: CurrentUserDep, svc: ServiceDep
) -> dict[str, str]:
    await svc.send(body)
    return {"status": "queued"}
