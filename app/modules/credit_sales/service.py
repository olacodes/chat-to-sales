"""
app/modules/credit_sales/service.py
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.modules.credit_sales.models import CreditSale, CreditSaleStatus
from app.modules.credit_sales.repository import CreditSaleRepository
from app.modules.credit_sales.schemas import (
    CreditSaleCreate,
    CreditSaleListResponse,
    CreditSaleOut,
    ReminderOut,
)
from app.modules.conversation.repository import ConversationRepository
from app.modules.conversation.models import MessageSender

logger = get_logger(__name__)


class CreditSaleService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = CreditSaleRepository(db)
        self._conv_repo = ConversationRepository(db)

    async def create_credit_sale(
        self, *, tenant_id: str, body: CreditSaleCreate
    ) -> CreditSaleOut:
        # Prevent duplicate credit sales for the same order
        existing = await self._repo.get_by_order_id(body.order_id, tenant_id=tenant_id)
        if existing is not None:
            return CreditSaleOut.model_validate(existing)

        credit_sale = CreditSale(
            tenant_id=tenant_id,
            order_id=body.order_id,
            conversation_id=body.conversation_id,
            customer_name=body.customer_name,
            amount=body.amount,
            currency=body.currency,
            due_date=body.due_date,
            reminder_interval_days=body.reminder_interval_days,
            max_reminders=body.max_reminders,
            notes=body.notes,
        )
        await self._repo.create(credit_sale)
        await self._db.commit()
        logger.info(
            "CreditSale created id=%s order=%s tenant=%s",
            credit_sale.id,
            body.order_id,
            tenant_id,
        )
        return CreditSaleOut.model_validate(credit_sale)

    async def list_credit_sales(
        self,
        *,
        tenant_id: str,
        status: CreditSaleStatus | None = None,
    ) -> CreditSaleListResponse:
        items = await self._repo.list(tenant_id=tenant_id, status=status)
        return CreditSaleListResponse(
            items=[CreditSaleOut.model_validate(c) for c in items],
            total=len(items),
        )

    async def get_credit_sale(self, credit_sale_id: str, *, tenant_id: str) -> CreditSaleOut:
        credit_sale = await self._repo.get_by_id(credit_sale_id, tenant_id=tenant_id)
        if credit_sale is None:
            raise NotFoundError("CreditSale", credit_sale_id)
        return CreditSaleOut.model_validate(credit_sale)

    async def settle(self, credit_sale_id: str, *, tenant_id: str) -> CreditSaleOut:
        credit_sale = await self._repo.get_by_id(credit_sale_id, tenant_id=tenant_id)
        if credit_sale is None:
            raise NotFoundError("CreditSale", credit_sale_id)
        await self._repo.update_status(credit_sale, status=CreditSaleStatus.SETTLED)
        await self._db.commit()
        return CreditSaleOut.model_validate(credit_sale)

    async def dispute(self, credit_sale_id: str, *, tenant_id: str) -> CreditSaleOut:
        credit_sale = await self._repo.get_by_id(credit_sale_id, tenant_id=tenant_id)
        if credit_sale is None:
            raise NotFoundError("CreditSale", credit_sale_id)
        await self._repo.update_status(credit_sale, status=CreditSaleStatus.DISPUTED)
        await self._db.commit()
        return CreditSaleOut.model_validate(credit_sale)

    async def send_reminder(self, credit_sale_id: str, *, tenant_id: str) -> ReminderOut:
        credit_sale = await self._repo.get_by_id(credit_sale_id, tenant_id=tenant_id)
        if credit_sale is None:
            raise NotFoundError("CreditSale", credit_sale_id)

        if credit_sale.status != CreditSaleStatus.ACTIVE:
            raise ValueError(f"CreditSale {credit_sale_id} is not active")

        if credit_sale.conversation_id is None:
            raise ValueError(f"CreditSale {credit_sale_id} has no linked conversation")

        if credit_sale.reminders_sent >= credit_sale.max_reminders:
            raise ValueError(
                f"Maximum reminders ({credit_sale.max_reminders}) already sent"
            )

        # Build the reminder message
        amount_str = f"₦{credit_sale.amount:,.0f}" if credit_sale.currency == "NGN" else f"{credit_sale.currency} {credit_sale.amount:,.0f}"
        message_text = (
            f"Hi {credit_sale.customer_name}, just a friendly reminder — "
            f"{amount_str} is still outstanding. "
            f"Please let us know when you're able to settle. Thank you! 🙏"
        )

        # Persist the message into the conversation (also dispatches to WhatsApp)
        await self._conv_repo.save_message(
            conversation_id=credit_sale.conversation_id,
            tenant_id=tenant_id,
            sender_role=MessageSender.ASSISTANT,
            content=message_text,
        )

        await self._repo.increment_reminder(credit_sale)
        await self._db.commit()

        logger.info(
            "Reminder sent credit_sale=%s reminders_sent=%d",
            credit_sale_id,
            credit_sale.reminders_sent,
        )

        return ReminderOut(
            credit_sale_id=credit_sale_id,
            reminders_sent=credit_sale.reminders_sent,
            message_sent=message_text,
        )
