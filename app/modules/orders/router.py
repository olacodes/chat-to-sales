from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import DBSessionDep
from app.modules.orders.schemas import OrderCreate, OrderItemsAdd, OrderOut
from app.modules.orders.service import OrderService

router = APIRouter(prefix="/orders", tags=["Orders"])


def _service(db: DBSessionDep) -> OrderService:
    return OrderService(db)


ServiceDep = Annotated[OrderService, Depends(_service)]


@router.post("/", status_code=201)
async def create_order(body: OrderCreate, svc: ServiceDep) -> OrderOut:
    return await svc.create_order(body)


@router.get("/{order_id}")
async def get_order(order_id: str, svc: ServiceDep) -> OrderOut:
    return await svc.get_by_id(order_id)


@router.post("/{order_id}/confirm")
async def confirm_order(order_id: str, svc: ServiceDep) -> OrderOut:
    return await svc.confirm_order(order_id)


@router.post("/{order_id}/pay")
async def pay_order(order_id: str, svc: ServiceDep) -> OrderOut:
    return await svc.mark_order_paid(order_id)


@router.post("/{order_id}/complete")
async def complete_order(order_id: str, svc: ServiceDep) -> OrderOut:
    return await svc.complete_order(order_id)


@router.post("/{order_id}/fail")
async def fail_order(order_id: str, svc: ServiceDep) -> OrderOut:
    return await svc.fail_order(order_id)


@router.post("/{order_id}/items", status_code=201)
async def add_items_to_order(
    order_id: str, body: OrderItemsAdd, svc: ServiceDep
) -> OrderOut:
    return await svc.add_items(order_id, body.items)
