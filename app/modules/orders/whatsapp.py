"""
app/modules/orders/whatsapp.py

Nigerian-English WhatsApp message templates for order management.

Every string here is written to pass the Bodija Test:
  "Can a fabric seller in Bodija Market understand this without instructions?"

Copy is warm, concise, and uses light Pidgin where it feels natural.
"""

import math
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


_PAGE_SIZE = 8  # items per page when paginating (leaves room for up to 2 nav rows)


def _paginate_product_rows(
    products: list[tuple[str, int]],
    page: int,
    *,
    id_prefix: str,
    show_price: bool,
) -> tuple[list[dict], int]:
    """
    Slice a sorted product list into WhatsApp list-picker rows with pagination.

    Returns (rows, total_pages).  If total products <= 10 there is no
    pagination and all products are returned on page 1.

    Navigation rows use IDs like ``RM_NEXT_2`` / ``PR_PREV_1``.
    """
    total = len(products)

    # No pagination needed for 10 or fewer products
    if total <= 10:
        rows = []
        for name, price in products:
            desc = _naira(price) if show_price else f"Current: {_naira(price)}"
            rows.append({
                "id": f"{id_prefix}_{name}"[:72],
                "title": name[:24],
                "description": desc,
            })
        return rows, 1

    total_pages = math.ceil(total / _PAGE_SIZE)
    page = max(1, min(page, total_pages))

    start = (page - 1) * _PAGE_SIZE
    end = start + _PAGE_SIZE
    page_products = products[start:end]

    rows = []
    for name, price in page_products:
        desc = _naira(price) if show_price else f"Current: {_naira(price)}"
        rows.append({
            "id": f"{id_prefix}_{name}"[:72],
            "title": name[:24],
            "description": desc,
        })

    # Navigation rows
    if page > 1:
        rows.append({
            "id": f"{id_prefix}_PREV_{page - 1}",
            "title": "\u2b05 Previous page",
            "description": f"Page {page - 1} of {total_pages}",
        })
    if page < total_pages:
        rows.append({
            "id": f"{id_prefix}_NEXT_{page + 1}",
            "title": "Next page \u27a1",
            "description": f"Page {page + 1} of {total_pages}",
        })

    return rows, total_pages


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


def order_reminder_to_trader(
    customer_phone: str,
    total: int,
    order_ref: str,
    hours_ago: int,
) -> str:
    time_label = f"{hours_ago} hour{'s' if hours_ago != 1 else ''}"
    return (
        f"\u23f0 Reminder: You have an unconfirmed order from +{customer_phone} "
        f"({time_label} ago).\n\n"
        f"*Total: {_naira(total)}*\n"
        f"Ref: {order_ref}\n\n"
        f"Reply *CONFIRM {order_ref}* to accept\n"
        f"Reply *CANCEL {order_ref}* to decline"
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


def trader_menu() -> tuple[str, str, list[dict]]:
    """Return (body, button_label, sections) for the trader main menu list message."""
    body = "What you wan do? \U0001f4cb"
    button_label = "Open menu"
    sections = [
        {
            "title": "Orders",
            "rows": [
                {"id": "MENU_HELP", "title": "\u2753 Help", "description": "See order commands"},
            ],
        },
        {
            "title": "Catalogue",
            "rows": [
                {"id": "MENU_CATALOGUE", "title": "\U0001f4cb My Catalogue", "description": "View all your products"},
                {"id": "MENU_ADD", "title": "\u2795 Add Product", "description": "Add new product + price"},
                {"id": "MENU_REMOVE", "title": "\u2796 Remove Product", "description": "Remove a product"},
                {"id": "MENU_PRICE", "title": "\U0001f4b0 Update Price", "description": "Change a product's price"},
                {"id": "MENU_PRICELIST", "title": "\U0001f4f7 Upload Price List", "description": "Photo/voice to update catalogue"},
            ],
        },
        {
            "title": "Store",
            "rows": [
                {"id": "MENU_STORE", "title": "\U0001f6cd My Store", "description": "View store link"},
                {"id": "MENU_CATEGORY", "title": "\U0001f3f7 Change Category", "description": "Switch business category"},
            ],
        },
    ]
    return body, button_label, sections


# ── Catalogue management templates ───────────────────────────────────────────


def catalogue_list(catalogue: dict[str, int], business_name: str) -> str:
    """Format the trader's catalogue as a readable list (empty catalogue only)."""
    if not catalogue:
        return (
            f"*{business_name}* — Your catalogue is empty.\n\n"
            "Add products by typing:\n"
            "_ADD Indomie Carton 8500_\n\n"
            "Or send MENU for more options."
        )
    lines = []
    for i, (name, price) in enumerate(sorted(catalogue.items()), 1):
        lines.append(f"  {i}. {name} — {_naira(price)}")
    return (
        f"*{business_name}* — Your catalogue ({len(catalogue)} products):\n\n"
        + "\n".join(lines)
        + "\n\nTo update, type:\n"
        "_ADD <product> <price>_\n"
        "_REMOVE <product>_\n"
        "_PRICE <product> <new price>_"
    )


def catalogue_picker(
    catalogue: dict[str, int], business_name: str, page: int = 1
) -> tuple[str, str, list[dict]]:
    """
    Return (body, button_label, sections) — catalogue as a list picker.

    Tapping a product enters the price-update flow (PR_ prefix).
    Body text shows the full product list for readability.
    """
    lines = []
    for i, (name, price) in enumerate(sorted(catalogue.items()), 1):
        lines.append(f"  {i}. {name} — {_naira(price)}")
    body = (
        f"*{business_name}* — {len(catalogue)} products:\n\n"
        + "\n".join(lines)
        + "\n\nTap a product below to update its price."
    )
    # Truncate body to WhatsApp's 1024-char limit for list messages
    if len(body) > 1024:
        body = (
            f"*{business_name}* — {len(catalogue)} products.\n\n"
            "Tap a product below to update its price."
        )
    button_label = "Edit price"
    products = sorted(catalogue.items())
    rows, _ = _paginate_product_rows(
        products, page, id_prefix="PR", show_price=False
    )
    sections = [{"title": "Your products", "rows": rows}]
    return body, button_label, sections


def product_added(name: str, price: int) -> str:
    return f"\u2705 Added *{name}* at {_naira(price)} to your catalogue."


def products_added_batch(items: list[tuple[str, int]]) -> str:
    lines = "\n".join(f"  {name} — {_naira(price)}" for name, price in items)
    return (
        f"\u2705 Added {len(items)} products to your catalogue:\n\n"
        f"{lines}"
    )


def product_removed(name: str) -> str:
    return f"\u2705 Removed *{name}* from your catalogue."


def products_removed_batch(names: list[str]) -> str:
    lines = "\n".join(f"  - {name}" for name in names)
    return f"\u2705 Removed {len(names)} products from your catalogue:\n\n{lines}"


def product_price_updated(name: str, old_price: int, new_price: int) -> str:
    return (
        f"\u2705 *{name}* price updated: {_naira(old_price)} \u2192 {_naira(new_price)}"
    )


def prices_updated_batch(items: list[tuple[str, int, int]]) -> str:
    lines = "\n".join(
        f"  {name}: {_naira(old)} \u2192 {_naira(new)}"
        for name, old, new in items
    )
    return f"\u2705 Updated {len(items)} prices:\n\n{lines}"


def product_not_found(name: str) -> str:
    return (
        f"I no fit find *{name}* in your catalogue. \U0001f914\n\n"
        "Type _CATALOGUE_ to see all your products."
    )


def add_product_prompt() -> str:
    return (
        "Type the product name and price. For example:\n\n"
        "_Milo 3500_\n\n"
        "Or add many at once:\n"
        "_Milo 3500, Garri 2500, Rice 63000_"
    )


def remove_product_list(
    catalogue: dict[str, int], page: int = 1
) -> tuple[str, str, list[dict]]:
    """Return (body, button_label, sections) for product removal picker with pagination."""
    products = sorted(catalogue.items())
    rows, total_pages = _paginate_product_rows(
        products, page, id_prefix="RM", show_price=True
    )
    page_label = f" (page {page}/{total_pages})" if total_pages > 1 else ""
    body = f"Which product you wan remove?{page_label}"
    button_label = "Select product"
    sections = [{"title": "Your products", "rows": rows}]
    return body, button_label, sections


def price_product_list(
    catalogue: dict[str, int], page: int = 1
) -> tuple[str, str, list[dict]]:
    """Return (body, button_label, sections) for price update picker with pagination."""
    products = sorted(catalogue.items())
    rows, total_pages = _paginate_product_rows(
        products, page, id_prefix="PR", show_price=False
    )
    page_label = f" (page {page}/{total_pages})" if total_pages > 1 else ""
    body = f"Which product you wan update?{page_label}"
    button_label = "Select product"
    sections = [{"title": "Your products", "rows": rows}]
    return body, button_label, sections


def price_enter_prompt(name: str, current_price: int) -> str:
    return (
        f"*{name}* — current price: {_naira(current_price)}\n\n"
        "Type the new price (e.g. _9000_):"
    )


def store_info(slug: str, business_name: str, product_count: int) -> str:
    return (
        f"\U0001f6cd *{business_name}*\n\n"
        f"Store link: https://chattosales.com/stores/{slug}\n"
        f"Products: {product_count}\n\n"
        "Share this link with your customers!"
    )


# ── Category change templates ───────────────────────────────────────────────


def category_picker(current_category: str) -> tuple[str, str, list[dict]]:
    """Return (body, button_label, sections) for category selection."""
    from app.modules.onboarding.catalogue_templates import (
        CATEGORY_DISPLAY_NAMES,
    )
    from app.modules.onboarding.models import BusinessCategory

    body = f"Your current category: *{CATEGORY_DISPLAY_NAMES.get(current_category, current_category)}*\n\nSelect your new category:"
    button_label = "Pick category"
    rows = []
    for cat in BusinessCategory:
        rows.append({
            "id": f"CAT_{cat.value}",
            "title": CATEGORY_DISPLAY_NAMES.get(cat.value, cat.value)[:24],
        })
    sections = [{"title": "Business categories", "rows": rows}]
    return body, button_label, sections


def category_changed(new_category_display: str) -> str:
    return f"\u2705 Category changed to *{new_category_display}*."


# ── Pricelist upload templates ──────────────────────────────────────────────


def pricelist_prompt() -> tuple[str, list[dict[str, str]]]:
    """Return (body_text, buttons) for the pricelist upload prompt."""
    body = (
        "Send me *photos of your price list* and I go update your catalogue. \U0001f4f7\n\n"
        "You fit send *multiple photos* — I go read all of them.\n"
        "You fit also send a *voice note* reading out your products and prices.\n\n"
        "When you done sending, tap the button below."
    )
    buttons = [{"id": "PRICELIST_DONE", "title": "\u2705 Done sending"}]
    return body, buttons


def pricelist_photo_received(count: int) -> tuple[str, list[dict[str, str]]]:
    """Return (body_text, buttons) acknowledging a received photo/voice."""
    photo_word = "photo" if count == 1 else "photos"
    body = (
        f"\U0001f4f8 Got it! {count} {photo_word} received.\n\n"
        "Send more or tap *Done* when you're finished."
    )
    buttons = [{"id": "PRICELIST_DONE", "title": "\u2705 Done sending"}]
    return body, buttons


def pricelist_processing() -> str:
    return "Reading your price list... \U0001f50d"


def pricelist_extracted(
    items: list[dict], new_count: int, updated_count: int
) -> tuple[str, list[dict[str, str]]]:
    """Return (body_text, buttons) for an interactive pricelist confirmation."""
    lines = "\n".join(
        f"  {item['name']} — {_naira(item['price'])}" for item in items
    )
    summary_parts = []
    if new_count:
        summary_parts.append(f"{new_count} new")
    if updated_count:
        summary_parts.append(f"{updated_count} price updates")
    summary = ", ".join(summary_parts) if summary_parts else "no changes"
    body = f"I found *{len(items)} products* ({summary}):\n\n{lines}"
    buttons = [
        {"id": "PRICELIST_YES", "title": "\u2705 Update catalogue"},
        {"id": "PRICELIST_NO", "title": "\u274c Cancel"},
    ]
    return body, buttons


def pricelist_confirmed(new_count: int, updated_count: int, total: int) -> str:
    parts = []
    if new_count:
        parts.append(f"{new_count} new products added")
    if updated_count:
        parts.append(f"{updated_count} prices updated")
    detail = ", ".join(parts) if parts else "no changes"
    return (
        f"\u2705 Catalogue updated! {detail}.\n\n"
        f"You now have *{total} products* in your catalogue."
    )


def pricelist_cancelled() -> str:
    return "No wahala, your catalogue stays the same. \U0001f44d"


def pricelist_empty() -> str:
    return (
        "I no fit find any products in that. \U0001f914\n\n"
        "Make sure the price list show product names and prices clearly.\n"
        "Try again or type _MENU_ for other options."
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


def image_inquiry_matched_list(
    product_name: str, price: int, trader_name: str
) -> tuple[str, str, list[dict]]:
    """
    Return (body_text, button_label, sections) for a WhatsApp list message.

    The customer taps the button to open a quantity picker, selects a qty
    (or Cancel), and the list_reply.id comes back as 'QTY_1' etc.
    They can also type freely (e.g. 'I want 7') — NLP handles that.
    """
    body = (
        f"This look like *{product_name}* from *{trader_name}*! \U0001f4f8\n\n"
        f"Price: {_naira(price)} each\n\n"
        "Select quantity below, or type how many you want (e.g. _I want 7_)."
    )
    button_label = "Select quantity"
    rows = []
    for q in range(1, 6):
        total = price * q
        rows.append({
            "id": f"QTY_{q}",
            "title": f"Buy {q}",
            "description": (
                _naira(price) if q == 1
                else f"{q} \u00d7 {_naira(price)} = {_naira(total)}"
            ),
        })
    rows.append({
        "id": "NO",
        "title": "Cancel order",
        "description": "Not what I'm looking for",
    })
    sections = [{"title": "Quantity", "rows": rows}]
    return body, button_label, sections


def image_inquiry_forwarded(trader_name: str) -> str:
    return (
        f"I see the item! Let me ask *{trader_name}* about the price. \U0001f4f8\n\n"
        "I go get back to you once they reply. Small time! \U0001f64f"
    )


def image_inquiry_to_trader(customer_phone: str) -> str:
    return (
        f"\U0001f4f8 Customer +{customer_phone} dey ask about this item.\n\n"
        "Reply with the product name and price (e.g. _iPhone 8500_)\n"
        "or just the price if no name (e.g. _8500_)."
    )


def image_inquiry_price_saved(product_name: str, price: int) -> str:
    return (
        f"\u2705 Got it! I don save *{product_name}* at {_naira(price)}.\n\n"
        "Next time a customer send photo of this product, I go answer them automatically. \U0001f4aa"
    )


def image_inquiry_price_to_customer(
    product_name: str, price: int, trader_name: str
) -> str:
    return (
        f"*{trader_name}* say this na *{product_name}*! \U0001f4f8\n\n"
        f"Price: {_naira(price)}\n\n"
        "You want order am? Reply *YES* to confirm or *NO* to cancel."
    )


def image_processing_failed() -> str:
    return (
        "I no fit see that photo well well. \U0001f605\n\n"
        "Abeg send a clearer photo, or just tell me wetin you want to buy!"
    )
