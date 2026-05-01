"""
app/modules/credit_sales/router.py
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUserDep, DBSessionDep
from app.modules.credit_sales.models import CreditSaleStatus
from app.modules.credit_sales.schemas import (
    CreditSaleCreate,
    CreditSaleListResponse,
    CreditSaleOut,
    ReminderOut,
)
from app.modules.credit_sales.service import CreditSaleService

router = APIRouter(prefix="/credit-sales", tags=["Credit Sales"])


def _service(db: DBSessionDep) -> CreditSaleService:
    return CreditSaleService(db)


ServiceDep = Annotated[CreditSaleService, Depends(_service)]


@router.get("")
async def list_credit_sales(
    user: CurrentUserDep,
    svc: ServiceDep,
    status: CreditSaleStatus | None = None,
) -> CreditSaleListResponse:
    return await svc.list_credit_sales(tenant_id=user.tenant_id, status=status)


@router.post("/", status_code=201)
async def create_credit_sale(
    user: CurrentUserDep,
    body: CreditSaleCreate,
    svc: ServiceDep,
) -> CreditSaleOut:
    return await svc.create_credit_sale(tenant_id=user.tenant_id, body=body)


@router.get("/{credit_sale_id}")
async def get_credit_sale(
    credit_sale_id: str,
    user: CurrentUserDep,
    svc: ServiceDep,
) -> CreditSaleOut:
    return await svc.get_credit_sale(credit_sale_id, tenant_id=user.tenant_id)


@router.post("/{credit_sale_id}/settle")
async def settle_credit_sale(
    credit_sale_id: str,
    user: CurrentUserDep,
    svc: ServiceDep,
) -> CreditSaleOut:
    return await svc.settle(credit_sale_id, tenant_id=user.tenant_id)


@router.post("/{credit_sale_id}/dispute")
async def dispute_credit_sale(
    credit_sale_id: str,
    user: CurrentUserDep,
    svc: ServiceDep,
) -> CreditSaleOut:
    return await svc.dispute(credit_sale_id, tenant_id=user.tenant_id)


@router.post("/{credit_sale_id}/write-off")
async def write_off_credit_sale(
    credit_sale_id: str,
    user: CurrentUserDep,
    svc: ServiceDep,
) -> CreditSaleOut:
    return await svc.write_off(credit_sale_id, tenant_id=user.tenant_id)


@router.post("/{credit_sale_id}/remind")
async def send_reminder(
    credit_sale_id: str,
    user: CurrentUserDep,
    svc: ServiceDep,
) -> ReminderOut:
    return await svc.send_reminder(credit_sale_id, tenant_id=user.tenant_id)
