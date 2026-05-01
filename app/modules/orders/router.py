from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentUserDep, DBSessionDep
from app.modules.orders.models import OrderState
from app.modules.orders.schemas import (
    OrderCreate,
    OrderItemsAdd,
    OrderListResponse,
    OrderOut,
)
from app.modules.orders.service import OrderService

router = APIRouter(prefix="/orders", tags=["Orders"])


def _service(db: DBSessionDep) -> OrderService:
    return OrderService(db)


ServiceDep = Annotated[OrderService, Depends(_service)]


@router.get("")
async def list_orders(
    user: CurrentUserDep,
    svc: ServiceDep,
    state: OrderState | None = Query(default=None),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> OrderListResponse:
    return await svc.list_orders(
        tenant_id=user.tenant_id,
        state=state,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


@router.post("", status_code=201)
async def create_order(body: OrderCreate, user: CurrentUserDep, svc: ServiceDep) -> OrderOut:
    body.tenant_id = user.tenant_id
    return await svc.create_order(body)


@router.get("/{order_id}")
async def get_order(
    order_id: str,
    user: CurrentUserDep,
    svc: ServiceDep,
) -> OrderOut:
    return await svc.get_by_id(order_id, tenant_id=user.tenant_id)


@router.post("/{order_id}/confirm")
async def confirm_order(order_id: str, user: CurrentUserDep, svc: ServiceDep) -> OrderOut:
    return await svc.confirm_order(order_id)


@router.post("/{order_id}/pay")
async def pay_order(order_id: str, user: CurrentUserDep, svc: ServiceDep) -> OrderOut:
    return await svc.mark_order_paid(order_id)


@router.post("/{order_id}/complete")
async def complete_order(order_id: str, user: CurrentUserDep, svc: ServiceDep) -> OrderOut:
    return await svc.complete_order(order_id)


@router.post("/{order_id}/fail")
async def fail_order(order_id: str, user: CurrentUserDep, svc: ServiceDep) -> OrderOut:
    return await svc.fail_order(order_id)


@router.post("/{order_id}/items", status_code=201)
async def add_items_to_order(
    order_id: str, body: OrderItemsAdd, user: CurrentUserDep, svc: ServiceDep
) -> OrderOut:
    return await svc.add_items(order_id, body.items)
