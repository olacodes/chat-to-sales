"""
app/modules/orders/whatsapp.py

WhatsApp message templates for order management.

Copy is warm, professional, and in proper English. The app still
understands Nigerian Pidgin, Yoruba numbers, and informal text as input —
only the output is in standard English.
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
        "I'll let you know once they confirm it. Please hold on. \U0001f64f"
    )


def order_confirmed_to_customer(trader_name: str, total: int) -> str:
    return (
        f"\u2705 *{trader_name}* has confirmed your order!\n\n"
        f"Total: {_naira(total)}\n\n"
        "They will reach out to you for delivery or pickup details. Thank you! \U0001f64f"
    )


def order_cancelled_to_customer(trader_name: str) -> str:
    return (
        f"Your order with *{trader_name}* has been cancelled.\n\n"
        "If you'd like to order something else, just message me anytime. \U0001f44d"
    )


def ask_clarification(question: str) -> str:
    return question


def unknown_order_prompt() -> str:
    return (
        "I didn't understand that. \U0001f914\n\n"
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
        "I couldn't understand that voice note. \U0001f605\n\n"
        "Please type your order or send a clearer voice note."
    )


def price_missing_prompt(item_names: list[str]) -> str:
    lines = "\n".join(f"  - {n}" for n in item_names)
    return (
        "I found these items in your order but I don't have their prices:\n\n"
        f"{lines}\n\n"
        "Please type the quantities and prices. For example:\n"
        "_2 cartons Indomie = 8500, 1 bag rice = 63000_"
    )


def negotiation_hold_customer() -> str:
    return (
        "I've asked the trader about the price. "
        "I'll let you know when they respond! \U0001f64f\n\n"
        "You can keep ordering in the meantime."
    )


def negotiation_to_trader_with_price(
    customer_phone: str, customer_name: str | None,
    product_name: str, original_price: int, offered_price: int,
) -> tuple[str, list[dict[str, str]]]:
    """Return (body, buttons) for a negotiation escalation with a specific offer."""
    display = customer_name or f"+{customer_phone}"
    body = (
        f"\U0001f4ac *{display}* wants to negotiate:\n\n"
        f"Product: {product_name}\n"
        f"Your price: {_naira(original_price)}\n"
        f"Their offer: {_naira(offered_price)}\n\n"
        "Would you like to accept their price?"
    )
    buttons = [
        {"id": f"NEGACCEPT_{customer_phone}", "title": "\u2705 Accept"},
        {"id": f"NEGCOUNTER_{customer_phone}", "title": "\U0001f4b0 Counter-offer"},
        {"id": f"NEGDECLINE_{customer_phone}", "title": "\u274c Decline"},
    ]
    return body, buttons


def negotiation_to_trader_general(
    customer_phone: str, customer_name: str | None,
    product_name: str, price: int,
) -> str:
    """Notify trader that customer is asking for a discount (no specific price)."""
    display = customer_name or f"+{customer_phone}"
    return (
        f"\U0001f4ac *{display}* is asking for a better price on "
        f"*{product_name}* ({_naira(price)}).\n\n"
        "You can message them directly to negotiate."
    )


def negotiation_accepted_to_customer(trader_name: str, accepted_price: int) -> str:
    return (
        f"Great news! *{trader_name}* accepted {_naira(accepted_price)}. \U0001f389\n\n"
        "Would you like to confirm your order? Reply *YES* to proceed."
    )


def negotiation_counter_prompt(original_price: int, offered_price: int) -> str:
    """Ask the trader to type their counter-offer price."""
    return (
        f"Your price: {_naira(original_price)}\n"
        f"Their offer: {_naira(offered_price)}\n\n"
        "Type your counter-offer price (e.g. _7500_):"
    )


def negotiation_counter_to_customer(
    trader_name: str, counter_price: int,
) -> str:
    return (
        f"*{trader_name}* can do {_naira(counter_price)}.\n\n"
        "Would you like to proceed? Reply *YES* to confirm or *NO* to cancel."
    )


def negotiation_declined_to_customer(trader_name: str, original_price: int) -> str:
    return (
        f"Sorry, *{trader_name}* can't go below {_naira(original_price)} for this item.\n\n"
        f"Would you like to order at {_naira(original_price)}? Reply *YES* or *NO*."
    )


def no_active_session() -> str:
    return (
        "No active order to cancel.\n\n"
        "If you want to order something, just tell me what you need! \U0001f60a"
    )


# ── Trader-facing ─────────────────────────────────────────────────────────────

def _customer_label(customer_name: str | None, customer_phone: str) -> str:
    """Return the best display name for a customer."""
    if customer_name:
        return f"*{customer_name}*"
    return f"+{customer_phone}"


def order_received_to_trader(
    items: list[dict[str, Any]],
    total: int,
    customer_phone: str,
    order_ref: str,
    customer_name: str | None = None,
) -> str:
    display = _customer_label(customer_name, customer_phone)
    lines = "\n".join(_item_line(i) for i in items)
    return (
        f"\U0001f6d2 New order from {display}:\n\n"
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
    customer_name: str | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """Return (body_text, buttons) for a trader order notification."""
    display = _customer_label(customer_name, customer_phone)
    lines = "\n".join(_item_line(i) for i in items)
    body = (
        f"\U0001f6d2 New order from {display}:\n\n"
        f"{lines}\n\n"
        f"*Total: {_naira(total)}*\n"
        f"Ref: {order_ref}"
    )
    buttons = [
        {"id": f"CONFIRM {order_ref}", "title": "\u2705 Confirm"},
        {"id": f"CANCEL {order_ref}", "title": "\u274c Decline"},
    ]
    return body, buttons


def order_confirmed_to_trader(
    order_ref: str, customer_name: str | None = None, customer_phone: str = "",
) -> tuple[str, list[dict[str, str]]]:
    """Return (body_text, buttons) for post-confirm payment options."""
    display = _customer_label(customer_name, customer_phone) if (customer_name or customer_phone) else "The customer"
    body = (
        f"\u2705 {display}'s order confirmed.\n\n"
        "When they pay, tap *Paid*.\n"
        "If it's on credit (pay later), tap *Credit*."
    )
    buttons = [
        {"id": f"PAID {order_ref}", "title": "\U0001f4b0 Paid"},
        {"id": f"CREDIT {order_ref}", "title": "\U0001f4dd Credit"},
    ]
    return body, buttons


def order_credit_buttons(
    order_ref: str, customer_display: str, amount: int,
) -> tuple[str, list[dict[str, str]]]:
    """Return (body, buttons) for a confirmed credit order — Paid in Full / Partial Payment."""
    body = (
        f"*{customer_display}* (Credit)\n"
        f"Amount: {_naira(amount)}\n"
        f"Ref: {order_ref}"
    )
    buttons = [
        {"id": f"CREDITPAID {order_ref}", "title": "\u2705 Paid in Full"},
        {"id": f"CREDITPART {order_ref}", "title": "\U0001f4b0 Partial Payment"},
    ]
    return body, buttons


def order_already_on_credit(order_ref: str, customer_name: str | None = None) -> str:
    display = f"*{customer_name}*'s order" if customer_name else f"Order {order_ref}"
    return (
        f"{display} is already on credit.\n\n"
        "Type _WHO OWES ME_ to manage your debt book."
    )


def credit_partial_prompt(
    order_ref: str, outstanding: int, customer_name: str | None = None,
) -> str:
    display = f"*{customer_name}*" if customer_name else f"Order {order_ref}"
    return (
        f"{display} — outstanding: {_naira(outstanding)}\n\n"
        "How much did the customer pay? Type the amount (e.g. _5000_):"
    )


def credit_paid_in_full(
    order_ref: str, amount: int, customer_name: str | None = None,
) -> str:
    display = f"*{customer_name}*" if customer_name else f"Order {order_ref}"
    return (
        f"\u2705 {display} fully paid! {_naira(amount)} debt cleared.\n\n"
        "The order has been marked as PAID."
    )


def credit_partial_received(
    order_ref: str, paid: int, remaining: int, customer_name: str | None = None,
) -> str:
    display = f"*{customer_name}*" if customer_name else f"order {order_ref}"
    return (
        f"\U0001f4b0 Received {_naira(paid)} from {display}.\n\n"
        f"Remaining balance: *{_naira(remaining)}*"
    )


def order_cancelled_to_trader(order_ref: str, customer_name: str | None = None) -> str:
    display = f"*{customer_name}*'s order" if customer_name else f"Order {order_ref}"
    return f"\u274c {display} cancelled. The customer has been notified."


def order_paid_to_trader(order_ref: str, customer_name: str | None = None) -> str:
    display = f"*{customer_name}*'s" if customer_name else f"Order {order_ref}:"
    return f"\U0001f4b0 Payment recorded for {display}. Marked as PAID."




def order_not_found_to_trader(ref: str) -> str:
    return (
        f"Could not find an order with ref {ref}.\n\n"
        "Check the exact ref code from the order notification and try again."
    )


def order_reminder_to_trader(
    customer_phone: str,
    total: int,
    order_ref: str,
    hours_ago: int,
    customer_name: str | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """Return (body_text, buttons) for an interactive order reminder."""
    display = _customer_label(customer_name, customer_phone)
    time_label = f"{hours_ago} hour{'s' if hours_ago != 1 else ''}"
    body = (
        f"\u23f0 Reminder: {display} has an unconfirmed order "
        f"({time_label} ago).\n\n"
        f"*Total: {_naira(total)}*\n"
        f"Ref: {order_ref}"
    )
    buttons = [
        {"id": f"CONFIRM {order_ref}", "title": "\u2705 Confirm"},
        {"id": f"CANCEL {order_ref}", "title": "\u274c Decline"},
    ]
    return body, buttons


def trader_command_guide() -> str:
    return (
        "To manage your orders, use these commands:\n\n"
        "  CONFIRM <ref>   - confirm a customer order\n"
        "  CANCEL <ref>    - cancel an order\n"
        "  PAID <ref>      - mark order as paid\n\n"
        "The ref is the short code shown in each order notification.\n\n"
        "Visit your dashboard to see all orders."
    )


def trader_menu() -> tuple[str, str, list[dict]]:
    """Return (body, button_label, sections) for the main menu (4 items → sub-menus)."""
    body = "What would you like to do? \U0001f4cb"
    button_label = "Open menu"
    sections = [
        {
            "title": "Menu",
            "rows": [
                {"id": "SUB_ORDERS", "title": "\U0001f4cb Orders & Debts", "description": "View orders, track who owes you"},
                {"id": "SUB_CATALOGUE", "title": "\U0001f4e6 Catalogue", "description": "Add, remove, update products"},
                {"id": "SUB_STORE", "title": "\U0001f6cd Store & Settings", "description": "Store link, bank, category"},
                {"id": "SUB_MARKETING", "title": "\U0001f4e3 Marketing", "description": "Create Status posts and videos"},
            ],
        },
    ]
    return body, button_label, sections


def trader_submenu_orders() -> tuple[str, str, list[dict]]:
    """Orders & Debts sub-menu."""
    body = "\U0001f4cb *Orders & Debts*"
    button_label = "Select"
    sections = [
        {
            "title": "Orders & Debts",
            "rows": [
                {"id": "MENU_ORDERS", "title": "\U0001f4cb Active Orders", "description": "View and manage your orders"},
                {"id": "MENU_DEBTS", "title": "\U0001f4d6 Who Owes Me", "description": "See your debt book"},
                {"id": "MENU_WHOIS", "title": "\U0001f464 Customer Lookup", "description": "Look up a customer's history"},
            ],
        },
    ]
    return body, button_label, sections


def trader_submenu_catalogue() -> tuple[str, str, list[dict]]:
    """Catalogue sub-menu."""
    body = "\U0001f4e6 *Catalogue*"
    button_label = "Select"
    sections = [
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
    ]
    return body, button_label, sections


def trader_submenu_store() -> tuple[str, str, list[dict]]:
    """Store & Settings sub-menu."""
    body = "\U0001f6cd *Store & Settings*"
    button_label = "Select"
    sections = [
        {
            "title": "Store & Settings",
            "rows": [
                {"id": "MENU_STORE", "title": "\U0001f6cd My Store", "description": "View store link"},
                {"id": "MENU_CATEGORY", "title": "\U0001f3f7 Change Category", "description": "Switch business category"},
                {"id": "MENU_BANK", "title": "\U0001f3e6 Bank Details", "description": "Set or update bank account"},
            ],
        },
    ]
    return body, button_label, sections


def trader_submenu_marketing() -> tuple[str, str, list[dict]]:
    """Marketing sub-menu."""
    body = "\U0001f4e3 *Marketing*"
    button_label = "Select"
    sections = [
        {
            "title": "Marketing",
            "rows": [
                {"id": "MENU_BROADCAST", "title": "\U0001f4e2 Broadcast Message", "description": "Send a message to your customers"},
                {"id": "MENU_STATUS_IMAGE", "title": "\U0001f4f8 Status Image", "description": "Generate a product image for Status"},
                {"id": "MENU_STATUS_VIDEO", "title": "\U0001f3ac Status Video", "description": "Generate a Ken Burns video for Status"},
                {"id": "MENU_STATUS_POST", "title": "\U0001f4e3 Create Status Post", "description": "Auto-generate image + video for Status"},
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
        f"Could not find *{name}* in your catalogue. \U0001f914\n\n"
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
    body = f"Which product would you like to remove?{page_label}"
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
    body = f"Which product would you like to update?{page_label}"
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
        "Send me *photos of your price list* and I'll update your catalogue. \U0001f4f7\n\n"
        "You can send *multiple photos* — I'll read all of them.\n"
        "You can also send a *voice note* reading out your products and prices.\n\n"
        "When you're done sending, tap the button below."
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
    return "No problem, your catalogue stays the same. \U0001f44d"


def pricelist_empty() -> str:
    return (
        "Couldn't find any products in that. \U0001f914\n\n"
        "Make sure the price list shows product names and prices clearly.\n"
        "Try again or type _MENU_ for other options."
    )


# ── Debt tracker templates ───────────────────────────────────────────────────


_STATE_LABELS: dict[str, str] = {
    "inquiry": "New",
    "confirmed": "Confirmed",
    "paid": "Paid",
    "failed": "Cancelled",
}


def pending_orders_list(
    orders: list[dict],
) -> tuple[str, str, list[dict]] | None:
    """
    Return (body, button_label, sections) for a list picker of active orders.

    Each order dict: {ref, customer_phone, amount, date, state, is_credit}
    Returns None if no orders.
    """
    if not orders:
        return None
    lines = []
    for i, o in enumerate(orders, 1):
        customer = o.get("customer_name") or (f"+{o['customer_phone']}" if o.get("customer_phone") else o["ref"])
        state_label = _STATE_LABELS.get(o.get("state", ""), o.get("state", ""))
        credit_tag = " | Credit" if o.get("is_credit") else ""
        lines.append(f"  {i}. {customer} — {_naira(o['amount'])} — {state_label}{credit_tag}")
    body = (
        f"You have *{len(orders)} active order{'s' if len(orders) != 1 else ''}*:\n\n"
        + "\n".join(lines)
        + "\n\nTap an order below to see actions."
    )
    if len(body) > 1024:
        body = (
            f"You have *{len(orders)} active order{'s' if len(orders) != 1 else ''}*.\n\n"
            "Tap an order below to see actions."
        )
    button_label = "View orders"
    rows = []
    for o in orders[:10]:  # WhatsApp max 10 rows
        state_label = _STATE_LABELS.get(o.get("state", ""), o.get("state", ""))
        credit_tag = " | Credit" if o.get("is_credit") else ""
        desc = f"{_naira(o['amount'])} — {state_label}{credit_tag} — {o['date']}"
        rows.append({
            "id": f"ORDACT_{o['ref']}",
            "title": (o.get("customer_name") or (f"+{o['customer_phone']}" if o.get("customer_phone") else o["ref"]))[:24],
            "description": desc[:72],
        })
    sections = [{"title": "Active orders", "rows": rows}]
    return body, button_label, sections


def pending_order_actions(
    order_ref: str, customer_display: str, amount: int, is_credit: bool = False,
) -> tuple[str, list[dict[str, str]]]:
    """Return (body, buttons) for action on a confirmed order."""
    if is_credit:
        return order_credit_buttons(order_ref, customer_display, amount)
    body = (
        f"*{customer_display}*\n"
        f"Amount: {_naira(amount)}\n"
        f"Ref: {order_ref}"
    )
    buttons = [
        {"id": f"PAID {order_ref}", "title": "\U0001f4b0 Paid"},
        {"id": f"CREDIT {order_ref}", "title": "\U0001f4dd Credit"},
    ]
    return body, buttons


def order_action_buttons(
    order_ref: str, customer_display: str, amount: int, state: str, is_credit: bool,
) -> tuple[str, list[dict[str, str]]]:
    """Return (body, buttons) with context-appropriate actions per order state."""
    credit_tag = " | Credit" if is_credit else ""
    state_label = _STATE_LABELS.get(state, state)
    body = (
        f"*{customer_display}*\n"
        f"Amount: {_naira(amount)}\n"
        f"Status: {state_label}{credit_tag}\n"
        f"Ref: {order_ref}"
    )
    buttons: list[dict[str, str]] = []
    if state == "inquiry":
        buttons = [
            {"id": f"CONFIRM {order_ref}", "title": "\u2705 Confirm"},
            {"id": f"CANCEL {order_ref}", "title": "\u274c Cancel"},
        ]
    elif state == "confirmed" and is_credit:
        buttons = [
            {"id": f"CREDITPAID {order_ref}", "title": "\u2705 Paid in Full"},
            {"id": f"CREDITPART {order_ref}", "title": "\U0001f4b0 Partial Payment"},
        ]
    # PAID is terminal — no buttons needed
    return body, buttons


# ── Bank details templates ───────────────────────────────────────────────


def product_photo_saved(product_name: str, price: int) -> str:
    return (
        f"\U0001f4f8 Photo saved for *{product_name}* ({_naira(price)}).\n\n"
        "This will be used in your Status posts and store page."
    )


def product_photo_which_product(
    catalogue: dict[str, int],
) -> tuple[str, str, list[dict]] | None:
    """Return (body, button_label, sections) list picker to match a photo to a product."""
    if not catalogue:
        return None
    body = "Nice photo! Which product is this for?"
    button_label = "Select product"
    rows = []
    for name, price in sorted(catalogue.items()):
        rows.append({
            "id": f"PHOT_{name}"[:72],
            "title": name[:24],
            "description": _naira(price),
        })
    if len(rows) > 10:
        rows = rows[:10]
    sections = [{"title": "Your products", "rows": rows}]
    return body, button_label, sections


# ── Status generation templates ──────────────────────────────────────────────


def status_product_picker(
    catalogue: dict[str, int], mode: str = "image",
) -> tuple[str, str, list[dict]] | None:
    """Return (body, button_label, sections) for picking a product to generate Status content."""
    if not catalogue:
        return None
    label_map = {"image": "Status image", "video": "Status video", "post": "Status post"}
    prefix_map = {"image": "STIMG", "video": "STVID", "post": "STPOST"}
    label = label_map.get(mode, "Status post")
    prefix = prefix_map.get(mode, "STPOST")
    body = f"Which product do you want to create a {label} for?"
    button_label = "Select product"
    rows = []
    for name, price in sorted(catalogue.items()):
        rows.append({
            "id": f"{prefix}_{name}"[:72],
            "title": name[:24],
            "description": _naira(price),
        })
    if len(rows) > 10:
        rows = rows[:10]
    sections = [{"title": "Your products", "rows": rows}]
    return body, button_label, sections


def status_generating(mode: str = "image") -> str:
    label = "image" if mode == "image" else "video"
    return f"Generating your Status {label}... This may take a moment."


def status_no_photo_for_video(product_name: str) -> str:
    return (
        f"No photo found for *{product_name}*. "
        "Videos need a product photo. Send a photo of this product first, "
        "or try *Status Image* instead (works without a photo)."
    )


def status_share_prompt() -> str:
    return (
        "Your Status content is ready! Save it and share to your WhatsApp Status."
    )


def bank_details_prompt() -> str:
    return (
        "To set up your bank details, type your bank name and account number.\n\n"
        "For example:\n_GTBank 0123456789_"
    )


def bank_details_saved(bank_name: str, account_number: str, account_name: str) -> str:
    return (
        f"\u2705 Bank details saved!\n\n"
        f"Bank: {bank_name}\n"
        f"Account: {account_number}\n"
        f"Name: {account_name}\n\n"
        "Your bank details will be sent to customers after you confirm their orders."
    )


def bank_details_current(bank_name: str, account_number: str, account_name: str) -> str:
    return (
        f"\U0001f3e6 Your bank details:\n\n"
        f"Bank: {bank_name}\n"
        f"Account: {account_number}\n"
        f"Name: {account_name}\n\n"
        "To update, type your new bank name and account number.\n"
        "For example: _GTBank 0123456789_"
    )


def bank_details_not_set() -> str:
    return (
        "You haven't set up your bank details yet.\n\n"
        "Type your bank name and account number.\n"
        "For example: _GTBank 0123456789_"
    )


def bank_verify_confirm(
    bank_name: str, account_number: str, account_name: str,
) -> tuple[str, list[dict[str, str]]]:
    """Ask trader to confirm the resolved account name."""
    body = (
        f"\U0001f3e6 I found this account:\n\n"
        f"Bank: *{bank_name}*\n"
        f"Account: *{account_number}*\n"
        f"Name: *{account_name}*\n\n"
        "Is this correct?"
    )
    buttons = [
        {"id": "BANK_YES", "title": "\u2705 Yes, save it"},
        {"id": "BANK_NO", "title": "\u274c No, re-enter"},
    ]
    return body, buttons


def bank_verify_failed(bank_name: str) -> str:
    """Paystack couldn't resolve the account — save with business name as fallback."""
    return (
        f"I couldn't verify the account name for *{bank_name}*.\n\n"
        "I'll save it with your business name. You can update it later by "
        "typing _BANK_ again."
    )


def bank_unknown_bank(bank_name: str) -> str:
    """Bank name not recognized."""
    return (
        f"I don't recognise *{bank_name}* as a bank name.\n\n"
        "Please type a Nigerian bank name and your 10-digit account number.\n"
        "For example: _GTBank 0123456789_ or _Kuda 1234567890_"
    )


def payment_details_to_customer(
    trader_name: str, total: int, bank_name: str,
    account_number: str, account_name: str, order_ref: str,
) -> str:
    return (
        f"\u2705 *{trader_name}* has confirmed your order!\n\n"
        f"*Total: {_naira(total)}*\n\n"
        f"Pay to:\n"
        f"\U0001f3e6 Bank: *{bank_name}*\n"
        f"\U0001f4b3 Account: *{account_number}*\n"
        f"\U0001f464 Name: *{account_name}*\n\n"
        f"After payment, send your receipt here or type *PAID*."
    )


def no_pending_orders() -> str:
    return "You have no active orders right now. \U0001f389"


def order_credit_to_trader(order_ref: str, customer_display: str, amount: int) -> str:
    return (
        f"\U0001f4dd *{customer_display}*'s order marked as credit.\n\n"
        f"Amount: {_naira(amount)}\n"
        f"Ref: {order_ref}\n\n"
        "I'll track this for you. Type _WHO OWES ME_ to see your debt book."
    )


def debt_created(customer_name: str, amount: int) -> str:
    return (
        f"\u2705 Recorded: *{customer_name}* owes you {_naira(amount)}.\n\n"
        "Type _WHO OWES ME_ to see your full debt book."
    )


def debt_settled(customer_name: str, amount: int) -> str:
    return f"\u2705 *{customer_name}* debt of {_naira(amount)} fully settled! Debt cleared."


def debt_partial_payment(customer_name: str, paid: int, remaining: int) -> str:
    return (
        f"\U0001f4b0 Received {_naira(paid)} from *{customer_name}*.\n\n"
        f"Remaining balance: *{_naira(remaining)}*"
    )


def debt_not_found(customer_name: str) -> str:
    return (
        f"Could not find any active debt for *{customer_name}*. \U0001f914\n\n"
        "Type _WHO OWES ME_ to see your debt book."
    )


def debt_reminder_to_trader(customer_name: str, amount: int, days_ago: int) -> str:
    """Remind the trader about an outstanding debt they need to follow up on."""
    return (
        f"\U0001f4ac Reminder: *{customer_name}* still owes you {_naira(amount)} "
        f"({days_ago} day{'s' if days_ago != 1 else ''} ago).\n\n"
        "Please follow up with them when you can."
    )


def debt_customer_reminded_notification(customer_name: str, amount: int, reminders_sent: int) -> str:
    """Notify the trader that an automated reminder was sent to the customer."""
    return (
        f"\U0001f514 I sent a friendly reminder to *{customer_name}* "
        f"about their outstanding balance of {_naira(amount)}.\n\n"
        f"This is reminder #{reminders_sent}."
    )


def debt_list_empty() -> str:
    return (
        "Your debt book is clean — nobody owes you right now! \U0001f389\n\n"
        "To track a debt, type:\n_DEBT Iya Bimpe 5000_"
    )


def debt_list_picker(
    debts: list[dict], total: int,
) -> tuple[str, str, list[dict]]:
    """
    Return (body, button_label, sections) for an interactive debt list.

    Each debt dict: {id, name, amount, days_ago}
    """
    lines = []
    for i, d in enumerate(debts, 1):
        days_label = f"({d['days_ago']}d ago)" if d.get("days_ago") else ""
        lines.append(f"  {i}. {d['name']} — {_naira(d['amount'])} {days_label}")
    body = (
        f"\U0001f4d6 *Who owes you* ({len(debts)} debtor{'s' if len(debts) != 1 else ''}):\n\n"
        + "\n".join(lines)
        + f"\n\n*Total outstanding: {_naira(total)}*\n\n"
        "Tap a name below to settle or send a reminder."
    )
    if len(body) > 1024:
        body = (
            f"\U0001f4d6 *Who owes you* ({len(debts)} debtor{'s' if len(debts) != 1 else ''})\n\n"
            f"*Total outstanding: {_naira(total)}*\n\n"
            "Tap a name below to settle or send a reminder."
        )
    button_label = "View debtors"
    rows = []
    for d in debts[:10]:  # WhatsApp max 10 rows
        days_label = f"{d['days_ago']}d ago" if d.get("days_ago") else ""
        rows.append({
            "id": f"DEBTACT_{d['id']}"[:72],
            "title": d["name"][:24],
            "description": f"{_naira(d['amount'])} — {days_label}"[:72],
        })
    sections = [{"title": "Outstanding debts", "rows": rows}]
    return body, button_label, sections


def debt_action_buttons(
    customer_name: str, amount: int, days_ago: int, credit_sale_id: str,
) -> tuple[str, list[dict[str, str]]]:
    """Return (body, buttons) for Settled/Remind actions on a debt."""
    body = (
        f"*{customer_name}* owes you {_naira(amount)}"
        f" ({days_ago} day{'s' if days_ago != 1 else ''} ago)"
    )
    buttons = [
        {"id": f"SETTLE_{credit_sale_id}", "title": "\u2705 Settled"},
        {"id": f"REMIND_{credit_sale_id}", "title": "\U0001f514 Remind"},
    ]
    return body, buttons


def debt_remind_sent(customer_name: str) -> str:
    return f"\U0001f514 Reminder sent to *{customer_name}*."


def debt_remind_failed(customer_name: str) -> str:
    return (
        f"Could not send a reminder for *{customer_name}*.\n\n"
        "This debt has no linked conversation. Please follow up with them directly."
    )


# ── Image inquiry ────────────────────────────────────────────────────────────


def image_inquiry_matched(
    product_name: str, price: int, trader_name: str
) -> str:
    return (
        f"This looks like *{product_name}* from *{trader_name}*! \U0001f4f8\n\n"
        f"Price: {_naira(price)}\n\n"
        "Would you like to order it? Tell me the quantity (e.g. _I want 2_) "
        "or reply *NO* if it's something different."
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
        f"This looks like *{product_name}* from *{trader_name}*! \U0001f4f8\n\n"
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
        "I'll get back to you once they reply. One moment! \U0001f64f"
    )


def image_inquiry_to_trader(customer_phone: str) -> str:
    return (
        f"\U0001f4f8 Customer +{customer_phone} is asking about this item.\n\n"
        "Reply with the product name and price (e.g. _iPhone 8500_)\n"
        "or just the price if there's no name (e.g. _8500_)."
    )


def image_inquiry_price_saved(product_name: str, price: int) -> str:
    return (
        f"\u2705 Got it! Saved *{product_name}* at {_naira(price)}.\n\n"
        "Next time a customer sends a photo of this product, I'll answer them automatically. \U0001f4aa"
    )


def image_inquiry_price_to_customer(
    product_name: str, price: int, trader_name: str
) -> str:
    return (
        f"*{trader_name}* says this is *{product_name}*! \U0001f4f8\n\n"
        f"Price: {_naira(price)}\n\n"
        "Would you like to order it? Reply *YES* to confirm or *NO* to cancel."
    )


def image_inquiry_more_pending(remaining: int) -> str:
    return (
        f"\U0001f4f8 You still have {remaining} more product "
        f"{'inquiry' if remaining == 1 else 'inquiries'} waiting.\n\n"
        "Reply with the product name and price for each one."
    )


# ── Payment receipt detection ─────────────────────────────────────────────


def payment_receipt_to_trader(
    customer_phone: str,
    customer_name: str | None,
    amount: int,
    order_ref: str,
    has_screenshot: bool = False,
) -> tuple[str, list[dict[str, str]]]:
    """Return (body, buttons) notifying trader that customer says they've paid."""
    display = customer_name or f"+{customer_phone}"
    screenshot_line = "\nThey also sent a payment screenshot." if has_screenshot else ""
    body = (
        f"\U0001f4b3 *{display}* says they have paid for order {order_ref}.\n\n"
        f"Amount: {_naira(amount)}{screenshot_line}\n\n"
        "Please check your account and confirm."
    )
    buttons = [
        {"id": f"PAYRCVD {order_ref}", "title": "\u2705 Payment Received"},
        {"id": f"PAYNOTRCVD {order_ref}", "title": "\u274c Not Received"},
    ]
    return body, buttons


def payment_receipt_ack_to_customer(trader_name: str) -> str:
    """Acknowledge customer's payment notification."""
    return (
        f"Thank you! I've notified *{trader_name}* about your payment. \U0001f4b3\n\n"
        "They will confirm once they've checked. Please hold on. \U0001f64f"
    )


def payment_confirmed_to_customer(trader_name: str, order_ref: str) -> str:
    """Notify customer that trader confirmed receiving payment."""
    return (
        f"\u2705 *{trader_name}* has confirmed receiving your payment for order {order_ref}!\n\n"
        "Thank you for your purchase! \U0001f389"
    )


def payment_not_received_to_customer(trader_name: str, order_ref: str) -> str:
    """Notify customer that trader hasn't received payment yet."""
    return (
        f"*{trader_name}* hasn't received the payment for order {order_ref} yet.\n\n"
        "Please double-check the bank details and try again, "
        "or contact the trader directly. \U0001f64f"
    )


def no_confirmed_order_for_payment(trader_name: str) -> str:
    """Customer says paid but no confirmed order found."""
    return (
        f"I don't see a confirmed order with *{trader_name}* to match your payment to. \U0001f914\n\n"
        "If you've placed an order, please wait for the trader to confirm it first."
    )


def image_processing_failed() -> str:
    return (
        "I couldn't process that photo. \U0001f605\n\n"
        "Please send a clearer photo, or just tell me what you'd like to buy!"
    )


# ── Broadcast templates ─────────────────────────────────────────────────────


_SEGMENT_DISPLAY: dict[str, tuple[str, str]] = {
    # key: (label, section)
    "all_customers": ("All Customers", "Audience"),
    # Behaviour
    "vip": ("VIP Customers", "By Behaviour"),
    "repeat_buyer": ("Repeat Buyers", "By Behaviour"),
    "paid_once": ("Bought Once", "By Behaviour"),
    "new_lead": ("New Leads", "By Behaviour"),
    "lapsed": ("Lapsed Customers", "By Behaviour"),
    "abandoned_cart": ("Abandoned Cart", "By Behaviour"),
    "browsed_only": ("Browsed Only", "By Behaviour"),
    # Interest
    "diverse_buyer": ("Diverse Buyers", "By Interest"),
    "price_sensitive": ("Price Sensitive", "By Interest"),
    "premium": ("Premium Buyers", "By Interest"),
    # Timing
    "weekly": ("Weekly Shoppers", "By Timing"),
    "monthly": ("Monthly Shoppers", "By Timing"),
    "payday": ("Payday Buyers", "By Timing"),
    "weekend": ("Weekend Shoppers", "By Timing"),
}

# Order segments should appear in the picker
_SEGMENT_ORDER = [
    "all_customers",
    "vip", "repeat_buyer", "paid_once", "new_lead", "lapsed", "abandoned_cart",
    "diverse_buyer", "price_sensitive", "premium",
    "weekly", "monthly", "payday", "weekend",
]


def broadcast_segment_picker(
    segment_counts: dict[str, int],
) -> tuple[str, str, list[dict]]:
    """Return (body, button_label, sections) for picking a broadcast segment."""
    total = segment_counts.get("all_customers", 0)
    if total == 0:
        return "You have no customers yet.", "Select", []

    body = (
        f"You have *{total} customers* in total.\n\n"
        "Who should receive this broadcast?"
    )
    button_label = "Select audience"
    rows = []
    for seg_key in _SEGMENT_ORDER:
        count = segment_counts.get(seg_key, 0)
        if count > 0:
            label, _ = _SEGMENT_DISPLAY.get(seg_key, (seg_key, "Other"))
            rows.append({
                "id": f"BCSEG_{seg_key}"[:72],
                "title": label[:24],
                "description": f"{count} customer{'s' if count != 1 else ''}",
            })
    # WhatsApp max 10 rows
    rows = rows[:10]
    sections = [{"title": "Audience", "rows": rows}]
    return body, button_label, sections


def broadcast_compose_prompt(segment_label: str, count: int) -> str:
    return (
        f"Sending to *{segment_label}* ({count} customer{'s' if count != 1 else ''}).\n\n"
        "Type your broadcast message now. I'll polish it before sending.\n\n"
        "Tips:\n"
        "- Keep it short and warm\n"
        "- Mention what's new or on offer\n"
        "- No ALL CAPS or spam words"
    )


def broadcast_quality_issues(issues: list[str]) -> str:
    lines = "\n".join(f"  - {issue}" for issue in issues)
    return (
        f"Hold on — I found some issues with your message:\n\n"
        f"{lines}\n\n"
        "Please rewrite your message and try again."
    )


def broadcast_preview(
    rewritten_text: str, segment_label: str, count: int,
) -> tuple[str, list[dict[str, str]]]:
    """Return (body, buttons) for the broadcast preview + confirm step."""
    body = (
        f"Here's how your broadcast will look:\n\n"
        f"---\n{rewritten_text}\n---\n\n"
        f"This will be sent to *{count}* {segment_label} customer{'s' if count != 1 else ''}."
    )
    buttons = [
        {"id": "BCYES", "title": "Send now"},
        {"id": "BCNO", "title": "Cancel"},
    ]
    return body, buttons


def broadcast_sending(count: int) -> str:
    return (
        f"Sending your broadcast to {count} customer{'s' if count != 1 else ''}... "
        "This may take a few minutes. I'll update you on progress."
    )


def broadcast_progress(sent: int, total: int) -> str:
    pct = int(sent / total * 100) if total else 0
    return f"Broadcast progress: {sent}/{total} sent ({pct}%)"


def broadcast_complete(sent: int, total: int, skipped: int = 0) -> str:
    parts = [f"Broadcast complete! Sent to *{sent}* customer{'s' if sent != 1 else ''}."]
    if skipped:
        parts.append(f"\n{skipped} skipped (opted out or recently messaged).")
    return " ".join(parts)


def broadcast_no_customers() -> str:
    return (
        "You don't have any customers yet.\n\n"
        "Customers are added automatically when they place orders. "
        "Once you have customers, you can send them broadcasts."
    )


def broadcast_cancelled() -> str:
    return "Broadcast cancelled. No messages were sent."


# ── Smart follow-up templates ───────────────────────────────────────────────


def followup_to_customer(
    customer_name: str | None,
    product_name: str,
    price: int | None,
    trader_name: str,
) -> str:
    """Warm follow-up sent to customer 24h after they showed interest."""
    greeting = f"Hi {customer_name}!" if customer_name else "Hi there!"
    price_line = f" ({_naira(price)})" if price else ""
    return (
        f"{greeting} Still interested in *{product_name}*{price_line} "
        f"from *{trader_name}*?\n\n"
        "Reply *YES* to place your order, or just let me know if you need anything else."
    )


def followup_notification_to_trader(
    customer_name: str | None,
    customer_phone: str,
    product_name: str,
) -> str:
    """Notify trader that an auto follow-up was sent."""
    display = f"*{customer_name}*" if customer_name else f"+{customer_phone}"
    return (
        f"I sent a follow-up to {display} about *{product_name}*.\n\n"
        "I'll let you know if they reply."
    )


def who_is_result(
    customer_name: str | None,
    customer_phone: str,
    total_orders: int,
    total_spend: int,
    first_order_date: str | None,
    last_order_date: str | None,
    segments: list[str],
    outstanding_debt: int = 0,
) -> str:
    """Format customer summary for WHO IS command."""
    display = customer_name or f"+{customer_phone}"
    lines = [f"*{display}*", f"Phone: +{customer_phone}", ""]

    # Orders & spend
    lines.append(f"Orders: {total_orders}")
    lines.append(f"Total spend: {_naira(total_spend)}")
    if first_order_date:
        lines.append(f"First order: {first_order_date}")
    if last_order_date:
        lines.append(f"Last order: {last_order_date}")

    # Debt
    if outstanding_debt > 0:
        lines.append(f"Outstanding debt: {_naira(outstanding_debt)}")

    # Segments
    segment_labels = {
        "vip": "VIP", "repeat_buyer": "Repeat Buyer", "paid_once": "Bought Once",
        "new_lead": "New Lead", "lapsed": "Lapsed", "abandoned_cart": "Abandoned Cart",
        "premium": "Premium", "price_sensitive": "Price Sensitive",
        "diverse_buyer": "Diverse Buyer", "weekly": "Weekly Shopper",
        "monthly": "Monthly Shopper", "payday": "Payday Buyer", "weekend": "Weekend Shopper",
    }
    if segments:
        tags = ", ".join(segment_labels.get(s, s) for s in segments)
        lines.append(f"\nSegments: {tags}")

    return "\n".join(lines)


def who_is_not_found(query: str) -> str:
    return (
        f"No customer found matching *{query}*.\n\n"
        "Try the full phone number or name. Customers are added when orders are paid."
    )


def followup_converted_to_trader(
    customer_name: str | None,
    customer_phone: str,
    product_name: str,
) -> str:
    """Notify trader that a follow-up converted into an order."""
    display = f"*{customer_name}*" if customer_name else f"+{customer_phone}"
    return (
        f"The follow-up worked! {display} just ordered *{product_name}*."
    )


def broadcast_segment_cooldown(segment_label: str, hours_left: int) -> str:
    return (
        f"You already sent a broadcast to *{segment_label}* recently.\n\n"
        f"To protect your WhatsApp reputation, you can broadcast to this "
        f"group again in *{hours_left} hour{'s' if hours_left != 1 else ''}*.\n\n"
        "Try a different segment, or wait and try again later."
    )


def broadcast_skip_warning(
    segment_label: str, total: int, will_skip: int, will_receive: int,
) -> str:
    return (
        f"Sending to *{segment_label}* ({total} customer{'s' if total != 1 else ''}).\n\n"
        f"*{will_skip}* will be skipped (already messaged in the last 7 days).\n"
        f"*{will_receive}* will receive your broadcast.\n\n"
        "Type your broadcast message now. I'll polish it before sending.\n\n"
        "Tips:\n"
        "- Keep it short and warm\n"
        "- Mention what's new or on offer\n"
        "- No ALL CAPS or spam words"
    )


def broadcast_wide_audience_warning(
    count: int, segment_label: str,
) -> tuple[str, list[dict[str, str]]]:
    """Extra confirmation for 100+ recipients."""
    body = (
        f"This broadcast will go to *{count}* customers ({segment_label}).\n\n"
        "Sending to a large audience increases the risk of WhatsApp flagging "
        "your number. Make sure your message is personal and relevant.\n\n"
        "Do you want to proceed?"
    )
    buttons = [
        {"id": "BCWIDEYES", "title": "Yes, proceed"},
        {"id": "BCNO", "title": "Cancel"},
    ]
    return body, buttons
