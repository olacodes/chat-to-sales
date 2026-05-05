"""
app/modules/orders/nlp.py

2-layer NLP pipeline for parsing customer and trader order messages.

Layer 1 — rule-based (always runs, < 5 ms, no external calls):
    Handles with high confidence (1.0):
        Trader commands  — CONFIRM / CANCEL / PAID / DELIVERED <ref>
        Customer YES/NO  — "yes", "oya", "no", "cancel", etc.
    Handles with medium confidence (0.7):
        Simple orders    — "<qty> <product-words>" pattern found
    Signals fallback (0.3):
        Order keywords present but no items extracted

Layer 2 — Claude Haiku (called only when Layer 1 confidence < 0.5):
    Handles complex Pidgin, multi-item, ambiguous, and mixed-language messages.
    Returns structured JSON parsed into a ParseResult.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_settings = get_settings()

# ── Intent constants ──────────────────────────────────────────────────────────

ORDER = "order"
CONFIRM = "confirm"              # customer confirms their order summary
CANCEL = "cancel"                # customer cancels / says NO
TRADER_CONFIRM = "trader_confirm"
TRADER_CANCEL = "trader_cancel"
TRADER_PAID = "trader_paid"
TRADER_DELIVERED = "trader_delivered"
TRADER_ADD = "trader_add"
TRADER_REMOVE = "trader_remove"
TRADER_PRICE = "trader_price"
TRADER_CATALOGUE = "trader_catalogue"
TRADER_MENU = "trader_menu"
UNKNOWN = "unknown"


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    intent: str
    items: list[dict[str, Any]] = field(default_factory=list)
    # items schema: {name: str, qty: int, unit_price: int | None}
    order_ref: str | None = None          # short hex ref for trader commands
    clarification_needed: bool = False
    clarification_question: str | None = None
    confidence: float = 1.0              # < 0.5 means Claude was/should be used


# ── Number word tables ────────────────────────────────────────────────────────

_YORUBA_NUMS: dict[str, int] = {
    "meji": 2, "meta": 3, "merin": 4, "marun": 5,
    "mefa": 6, "meje": 7, "mejo": 8, "mesan": 9, "mewa": 10,
    "ogun": 20, "ogoji": 40,
}
_ENGLISH_NUMS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_WORD_TO_NUM: dict[str, int] = {**_YORUBA_NUMS, **_ENGLISH_NUMS}

# ── Layer-1 regex patterns ────────────────────────────────────────────────────

# Trader commands: verb + 6-16 lowercase hex chars
_TRADER_CMD_RE = re.compile(
    r"^(confirm|cancel|paid|deliver(?:ed)?)\s+([a-f0-9]{6,16})\b",
    re.IGNORECASE,
)

_YES_RE = re.compile(
    r"^(yes|yep|yh|yeah|ok|okay|oya|correct|sure|go ahead|no problem|"
    r"e correct|na correct|that'?s (?:right|correct|fine)|confirm|affirm)$",
    re.IGNORECASE,
)
_NO_RE = re.compile(
    r"^(no|nope|nah|cancel|stop|na|forget(?: am| it)?|"
    r"don'?t(?: bother)?|abeg cancel|na lie|wrong)$",
    re.IGNORECASE,
)

# Trigger words that suggest a purchase intent
_ORDER_TRIGGER_RE = re.compile(
    r"\b(order|buy|want|need|send|give|get|bring|abeg|oya|"
    r"i go take|make it|i dey look for|add)\b",
    re.IGNORECASE,
)

# Stop words that end a product-name token sequence
_NAME_STOP = frozenset({"and", "with", "plus", "abeg", "oya", "for", "please"})

_TRADER_VERB_MAP = {
    "confirm": TRADER_CONFIRM,
    "cancel": TRADER_CANCEL,
    "paid": TRADER_PAID,
    "deliver": TRADER_DELIVERED,
    "delivered": TRADER_DELIVERED,
}

# Catalogue management commands
# ADD <product name> <price>  e.g. "ADD Milo 3500", "add Peak Milk Tin 1200"
# Also supports batch: "ADD Milo 3500, Garri 2500, Rice 63000"
_ADD_RE = re.compile(
    r"^add\s+(.+?)\s+(\d[\d,]*)\s*$",
    re.IGNORECASE,
)
_ADD_PREFIX_RE = re.compile(r"^add[\s\n]", re.IGNORECASE)
_ADD_ITEM_RE = re.compile(r"^(.+?)\s+(\d[\d,]*)\s*$")
# REMOVE <product name>  e.g. "REMOVE Garri", "remove Peak Milk"
_REMOVE_RE = re.compile(
    r"^(?:remove|delete)\s+(.+)$",
    re.IGNORECASE,
)
# PRICE <product name> <new price>  e.g. "PRICE Indomie 9000"
# Also batch: "PRICE Rice 75000, Milo 4000, Garri 3000"
_PRICE_RE = re.compile(
    r"^price\s+(.+?)\s+(\d[\d,]*)\s*$",
    re.IGNORECASE,
)
_PRICE_PREFIX_RE = re.compile(r"^price[\s\n]", re.IGNORECASE)
# CATALOGUE / CATALOG / MY PRODUCTS
_CATALOGUE_RE = re.compile(
    r"^(?:catalogue|catalog|my products|products|my catalogue|my catalog)$",
    re.IGNORECASE,
)
# MENU / HELP
_MENU_RE = re.compile(
    r"^(?:menu|help|commands|options)$",
    re.IGNORECASE,
)


# ── Layer-1 helpers ───────────────────────────────────────────────────────────

def _parse_qty(token: str) -> int | None:
    """Convert a word or digit string to a quantity integer, or return None."""
    lower = token.lower()
    if lower in _WORD_TO_NUM:
        return _WORD_TO_NUM[lower]
    try:
        return int(token)
    except ValueError:
        return None


def _extract_items(tokens: list[str]) -> list[dict[str, Any]]:
    """
    Scan tokens for <qty> <product-name-words> patterns.

    Stops collecting product words at the next quantity token or a stop word.
    """
    items: list[dict[str, Any]] = []
    i = 0
    while i < len(tokens):
        qty = _parse_qty(tokens[i])
        if qty is not None and i + 1 < len(tokens):
            name_parts: list[str] = []
            j = i + 1
            while j < len(tokens):
                t = tokens[j]
                if _parse_qty(t) is not None or t.lower() in _NAME_STOP:
                    break
                name_parts.append(t)
                j += 1
            if name_parts:
                raw_name = " ".join(name_parts)
                # Strip leading "of" ("2 cartons of Indomie" -> "cartons Indomie")
                raw_name = re.sub(r"^of\s+", "", raw_name, flags=re.IGNORECASE)
                if raw_name.strip():
                    items.append({"name": raw_name.strip(), "qty": qty, "unit_price": None})
                i = j
                continue
        i += 1
    return items


def _parse_add_items(message: str) -> list[dict[str, Any]]:
    """
    Parse single or batch ADD commands.

    Accepts:
        ADD Milo 3500
        ADD Milo 3500, Garri 2500, Rice 63000
        ADD Milo 3,500, Garri 2,500
        ADD
        Milo 3500
        Garri 2500

    Returns list of {name, qty, unit_price} dicts, or empty list on failure.
    """
    # Strip the leading "ADD" keyword
    body = re.sub(r"^add\s*", "", message.strip(), flags=re.IGNORECASE)
    if not body:
        return []

    # Remove commas inside numbers FIRST (e.g. "3,500" -> "3500")
    # so they don't interfere with the comma delimiter split.
    body = re.sub(r"(\d),(\d)", r"\1\2", body)

    # Split by comma or newline
    parts = re.split(r"[,\n]", body)
    items: list[dict[str, Any]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = _ADD_ITEM_RE.match(part)
        if m:
            name = m.group(1).strip()
            price = int(m.group(2))
            if name and price > 0:
                items.append({"name": name, "qty": 1, "unit_price": price})
    return items


# ── Layer-1 entry point ───────────────────────────────────────────────────────

def _layer1(message: str) -> ParseResult:
    """
    Rule-based parse. Returns ParseResult with confidence in [0.0, 1.0].

    confidence == 1.0  → definitive result, no Claude needed
    confidence == 0.7  → order with items found, but Claude may improve
    confidence == 0.3  → order intent only, no items — Claude needed
    confidence == 0.0  → no intent detected
    """
    stripped = message.strip()

    # ── Trader commands ───────────────────────────────────────────────────────
    m = _TRADER_CMD_RE.match(stripped)
    if m:
        verb = m.group(1).lower()
        ref = m.group(2).lower()
        return ParseResult(
            intent=_TRADER_VERB_MAP[verb],
            order_ref=ref,
            confidence=1.0,
        )

    # ── Catalogue management commands ────────────────────────────────────────
    if _ADD_PREFIX_RE.match(stripped):
        items = _parse_add_items(stripped)
        if items:
            return ParseResult(
                intent=TRADER_ADD,
                items=items,
                confidence=1.0,
            )

    if _PRICE_PREFIX_RE.match(stripped):
        # Reuse _parse_add_items logic: "PRICE X 100, Y 200" has same format as "ADD X 100, Y 200"
        items = _parse_add_items(re.sub(r"^price", "ADD", stripped, flags=re.IGNORECASE))
        if items:
            return ParseResult(
                intent=TRADER_PRICE,
                items=items,
                confidence=1.0,
            )

    m = _REMOVE_RE.match(stripped)
    if m:
        body = m.group(1).strip()
        # Support batch: "REMOVE Garri, Milo, Rice"
        parts = [p.strip() for p in body.split(",") if p.strip()]
        items = [{"name": name, "qty": 1, "unit_price": None} for name in parts]
        if items:
            return ParseResult(
                intent=TRADER_REMOVE,
                items=items,
                confidence=1.0,
            )

    if _CATALOGUE_RE.match(stripped):
        return ParseResult(intent=TRADER_CATALOGUE, confidence=1.0)

    if _MENU_RE.match(stripped):
        return ParseResult(intent=TRADER_MENU, confidence=1.0)

    # ── Customer YES / NO ─────────────────────────────────────────────────────
    if _YES_RE.match(stripped):
        return ParseResult(intent=CONFIRM, confidence=1.0)
    if _NO_RE.match(stripped):
        return ParseResult(intent=CANCEL, confidence=1.0)

    # ── Order intent ──────────────────────────────────────────────────────────
    if not _ORDER_TRIGGER_RE.search(stripped):
        return ParseResult(intent=UNKNOWN, confidence=0.0)

    items = _extract_items(stripped.split())
    if items:
        return ParseResult(intent=ORDER, items=items, confidence=0.7)

    # Order keywords found but items not extractable — Claude needed
    return ParseResult(intent=ORDER, items=[], confidence=0.3)


# ── Layer-2: Claude Haiku ─────────────────────────────────────────────────────

async def _layer2_claude(
    message: str,
    *,
    category: str,
    catalogue: dict[str, int],
) -> ParseResult:
    """
    Claude Haiku fallback for ambiguous or complex messages.

    Returns ParseResult(intent=UNKNOWN) on any API or JSON parse error so
    the caller can gracefully ask the customer to clarify.
    """
    if not _settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — Claude NLP fallback unavailable")
        return ParseResult(intent=UNKNOWN, confidence=0.0)

    cat_lines = (
        "\n".join(f"- {n}: N{p:,}" for n, p in catalogue.items())
        if catalogue
        else "(no catalogue available)"
    )

    prompt = (
        f"You help parse WhatsApp messages from customers of a Nigerian {category} trader.\n\n"
        f"Trader catalogue:\n{cat_lines}\n\n"
        f"Customer message: {json.dumps(message)}\n\n"
        "Return ONLY a JSON object — no markdown, no commentary.\n\n"
        'Format: {"intent":"order"|"confirm"|"cancel"|"unknown",'
        '"items":[{"name":"product name","qty":2,"unit_price":8500}],'
        '"clarification_needed":false,"clarification_question":null}\n\n'
        "Rules:\n"
        "- Match product names loosely to catalogue (Indomie -> Indomie Carton).\n"
        "- Set unit_price from catalogue. If unknown, use null.\n"
        "- Greetings or chitchat: intent=unknown.\n"
        "- Yoruba numbers: meji=2 meta=3 merin=4 marun=5 mefa=6 meje=7 mejo=8 ogun=20.\n"
        "- Pidgin: abeg=please, oya=let's go, na=is/it is.\n"
        "- If order but items are unclear, set clarification_needed=true and ask ONE "
        "specific question in clarification_question.\n"
        "JSON:"
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=_settings.ANTHROPIC_API_KEY)
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        # Strip markdown fences if Claude wrapped the output
        if "```" in raw:
            for part in raw.split("```"):
                part = part.strip().lstrip("json").strip()
                if part.startswith("{"):
                    raw = part
                    break
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("Claude NLP failed: %s | message=%.100s", exc, message)
        return ParseResult(intent=UNKNOWN, confidence=0.0)

    intent = data.get("intent", UNKNOWN)
    raw_items = data.get("items") or []
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        try:
            qty = max(1, int(item.get("qty", 1)))
        except (ValueError, TypeError):
            qty = 1
        raw_price = item.get("unit_price")
        try:
            unit_price = int(float(str(raw_price))) if raw_price is not None else None
        except (ValueError, TypeError):
            unit_price = None
        items.append({"name": name, "qty": qty, "unit_price": unit_price})

    return ParseResult(
        intent=intent,
        items=items,
        clarification_needed=bool(data.get("clarification_needed")),
        clarification_question=data.get("clarification_question"),
        confidence=0.5,
    )


# ── Public entry point ────────────────────────────────────────────────────────

async def parse_message(
    message: str,
    *,
    category: str = "",
    catalogue: dict[str, int] | None = None,
) -> ParseResult:
    """
    Parse an order-related message into a structured ParseResult.

    Layer 1 (rule-based) always runs first.  If confidence < 0.5 and the
    message looks like an order attempt, Layer 2 (Claude Haiku) is called.

    Args:
        message:   The raw customer or trader message text.
        category:  Trader's business category string (e.g. "provisions").
        catalogue: Dict of {product_name: price_naira} from the trader's store.
    """
    result = _layer1(message)
    if result.confidence < 0.5 and result.intent in (ORDER, UNKNOWN):
        result = await _layer2_claude(
            message,
            category=category,
            catalogue=catalogue or {},
        )
    return result
