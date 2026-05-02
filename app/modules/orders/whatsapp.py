"""
app/modules/orders/whatsapp.py

Nigerian-English WhatsApp message templates for order management.

Every string here is written to pass the Bodija Test:
  "Can a fabric seller in Bodija Market understand this without instructions?"

Copy is warm, concise, and uses light Pidgin where it feels natural.
"""

from decimal import Decimal
from typing import Any


def _naira(amount: int | float | Decimal) -> str:
    return f"N{int(amount):,}"


def _item_line(item: dict[str, Any]) -> str:
    name = item["name"]
    qty = item.get("qty", 1)
    price = item.get("unit_price")
    if price:
        subtotal = qty * int(price)
        return f"  {qty}x {name} - {_naira(price)} each = {_naira(subtotal)}"
    return f"  {qty}x {name}"


# ── Customer-facing ───────────────────────────────────────────────────────────

def order_summary_to_customer(
    items: list[dict[str, Any]],
    total: int,
    trader_name: str,
) -> str:
    lines = "\n".join(_item_line(i) for i in items)
    return (
        f"Here is your order from *{trader_name}*:\n\n"
        f"{lines}\n\n"
        f"*Total: {_naira(total)}*\n\n"
        "Is this correct? Reply *YES* to confirm or *NO* to cancel."
    )


def order_summary_interactive(
    items: list[dict[str, Any]],
    total: int,
    trader_name: str,
) -> tuple[str, list[dict[str, str]]]:
    """Return (body_text, buttons) for a customer order confirmation."""
    lines = "\n".join(_item_line(i) for i in items)
    body = (
        f"Here is your order from *{trader_name}*:\n\n"
        f"{lines}\n\n"
        f"*Total: {_naira(total)}*"
    )
    buttons = [
        {"id": "YES", "title": "\u2705 Confirm"},
        {"id": "NO", "title": "\u274c Cancel"},
    ]
    return body, buttons


def order_pending_to_customer(trader_name: str) -> str:
    return (
        f"Your order has been sent to *{trader_name}*! "
        "I will let you know once they confirm it. Please hold on. \U0001f64f"
    )


def order_confirmed_to_customer(trader_name: str, total: int) -> str:
    return (
        f"\u2705 *{trader_name}* don confirm your order!\n\n"
        f"Total: {_naira(total)}\n\n"
        "They go reach out to you for delivery or pickup details. Thank you! \U0001f64f"
    )


def order_cancelled_to_customer(trader_name: str) -> str:
    return (
        f"Your order with *{trader_name}* don cancel.\n\n"
        "If you want to order something else, just message me anytime. \U0001f44d"
    )


def ask_clarification(question: str) -> str:
    return question


def unknown_order_prompt() -> str:
    return (
        "I no understand wetin you want o. \U0001f914\n\n"
        "To place an order, just tell me what you need. For example:\n"
        "_I want 2 cartons of Indomie and 1 bag of rice_"
    )


def store_order_prompt() -> str:
    return (
        "To place an order, visit your trader's store link, select your items, "
        "then tap *Order on WhatsApp*. \U0001f6d2\n\n"
        "Ask your trader for their store link if you don't have it."
    )


def voice_transcription_failed() -> str:
    return (
        "I no fit hear that voice note well well. \U0001f605\n\n"
        "Abeg type your order or send a clearer voice note."
    )


def price_missing_prompt(item_names: list[str]) -> str:
    lines = "\n".join(f"  - {n}" for n in item_names)
    return (
        "I see these items in your order but I no have their prices:\n\n"
        f"{lines}\n\n"
        "Abeg type the quantities and prices. For example:\n"
        "_2 cartons Indomie = 8500, 1 bag rice = 63000_"
    )


def no_active_session() -> str:
    return (
        "No active order to cancel.\n\n"
        "If you want to order something, just tell me what you need! \U0001f60a"
    )


# ── Trader-facing ─────────────────────────────────────────────────────────────

def order_received_to_trader(
    items: list[dict[str, Any]],
    total: int,
    customer_phone: str,
    order_ref: str,
) -> str:
    lines = "\n".join(_item_line(i) for i in items)
    return (
        f"\U0001f6d2 New order from +{customer_phone}:\n\n"
        f"{lines}\n\n"
        f"*Total: {_naira(total)}*\n"
        f"Ref: {order_ref}\n\n"
        f"Reply *CONFIRM {order_ref}* to accept\n"
        f"Reply *CANCEL {order_ref}* to decline"
    )


def order_received_interactive(
    items: list[dict[str, Any]],
    total: int,
    customer_phone: str,
    order_ref: str,
) -> tuple[str, list[dict[str, str]]]:
    """Return (body_text, buttons) for a trader order notification."""
    lines = "\n".join(_item_line(i) for i in items)
    body = (
        f"\U0001f6d2 New order from +{customer_phone}:\n\n"
        f"{lines}\n\n"
        f"*Total: {_naira(total)}*\n"
        f"Ref: {order_ref}"
    )
    buttons = [
        {"id": f"CONFIRM {order_ref}", "title": "\u2705 Confirm"},
        {"id": f"CANCEL {order_ref}", "title": "\u274c Decline"},
    ]
    return body, buttons


def order_confirmed_to_trader(order_ref: str) -> str:
    return (
        f"\u2705 Order {order_ref} confirmed. Customer don hear about am."
    )


def order_cancelled_to_trader(order_ref: str) -> str:
    return f"\u274c Order {order_ref} cancelled. Customer don hear about am."


def order_paid_to_trader(order_ref: str) -> str:
    return f"\U0001f4b0 Payment recorded for order {order_ref}. Order don mark as PAID."


def order_delivered_to_trader(order_ref: str) -> str:
    return f"\U0001f680 Order {order_ref} mark as delivered. Well done! \U0001f4aa"


def order_not_found_to_trader(ref: str) -> str:
    return (
        f"I no fit find order with ref {ref}.\n\n"
        "Check the exact ref code from the order notification and try again."
    )


def trader_command_guide() -> str:
    return (
        "To manage your orders, use these commands:\n\n"
        "  CONFIRM <ref>   - confirm a customer order\n"
        "  CANCEL <ref>    - cancel an order\n"
        "  PAID <ref>      - mark order as paid\n"
        "  DELIVERED <ref> - mark order as delivered\n\n"
        "The ref is the short code shown in each order notification.\n\n"
        "Visit your dashboard to see all orders."
    )


# ── Image inquiry ────────────────────────────────────────────────────────────


def image_inquiry_matched(
    product_name: str, price: int, trader_name: str
) -> str:
    return (
        f"This look like *{product_name}* from *{trader_name}*! \U0001f4f8\n\n"
        f"Price: {_naira(price)}\n\n"
        "You want order am? Tell me the quantity (e.g. _I want 2_) "
        "or reply *NO* if na different thing."
    )


def image_inquiry_forwarded(trader_name: str) -> str:
    return (
        f"I see the item! Let me ask *{trader_name}* about the price. \U0001f4f8\n\n"
        "I go get back to you once they reply. Small time! \U0001f64f"
    )


def image_inquiry_to_trader(customer_phone: str, description: str) -> str:
    return (
        f"\U0001f4f8 Customer +{customer_phone} dey ask about this item:\n\n"
        f"_{description}_\n\n"
        "Reply with the price (e.g. _8500_) and I go tell them."
    )


def image_processing_failed() -> str:
    return (
        "I no fit see that photo well well. \U0001f605\n\n"
        "Abeg send a clearer photo, or just tell me wetin you want to buy!"
    )
