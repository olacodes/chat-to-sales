"""
app/infra/paystack.py

Paystack utility for bank account verification.

Uses the free POST /bank/resolve endpoint to look up the account holder's
name given a bank code + account number. No Paystack account or payment
setup is required — only a secret key.
"""

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_PAYSTACK_BASE = "https://api.paystack.co"

# ── Nigerian bank name → Paystack bank code mapping ─────────────────────────
# Covers major banks. Names are lowercased for fuzzy matching.

_BANK_CODES: dict[str, str] = {
    "access": "044",
    "access bank": "044",
    "access diamond": "044",
    "citibank": "023",
    "ecobank": "050",
    "fidelity": "070",
    "fidelity bank": "070",
    "first bank": "011",
    "firstbank": "011",
    "first city monument bank": "214",
    "fcmb": "214",
    "globus": "00103",
    "globus bank": "00103",
    "gtbank": "058",
    "gtb": "058",
    "guaranty trust bank": "058",
    "gt bank": "058",
    "heritage": "030",
    "heritage bank": "030",
    "jaiz": "301",
    "jaiz bank": "301",
    "keystone": "082",
    "keystone bank": "082",
    "kuda": "50211",
    "kuda bank": "50211",
    "lotus": "303",
    "lotus bank": "303",
    "moniepoint": "50515",
    "moniepoint mfb": "50515",
    "opay": "999992",
    "palmpay": "999991",
    "parallex": "104",
    "parallex bank": "104",
    "polaris": "076",
    "polaris bank": "076",
    "providus": "101",
    "providus bank": "101",
    "stanbic": "221",
    "stanbic ibtc": "221",
    "stanbic ibtc bank": "221",
    "standard chartered": "068",
    "standard chartered bank": "068",
    "sterling": "232",
    "sterling bank": "232",
    "suntrust": "100",
    "suntrust bank": "100",
    "taj": "302",
    "taj bank": "302",
    "titan trust": "102",
    "titan trust bank": "102",
    "uba": "033",
    "united bank for africa": "033",
    "union": "032",
    "union bank": "032",
    "unity": "215",
    "unity bank": "215",
    "wema": "035",
    "wema bank": "035",
    "alat": "035",
    "zenith": "057",
    "zenith bank": "057",
}


def resolve_bank_code(bank_name: str) -> str | None:
    """
    Map a Nigerian bank name to its Paystack bank code.

    Returns None if the bank name is not recognized.
    """
    normalized = bank_name.strip().lower()
    return _BANK_CODES.get(normalized)


async def resolve_account_name(
    bank_code: str,
    account_number: str,
) -> str | None:
    """
    Call Paystack's POST /bank/resolve to get the account holder's name.

    Returns the account name string on success, or None on failure.
    This is a free API — no charges, no Paystack account needed.
    """
    settings = get_settings()
    secret_key = settings.PAYSTACK_SECRET_KEY
    if not secret_key:
        logger.warning("PAYSTACK_SECRET_KEY not set — skipping account resolve")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_PAYSTACK_BASE}/bank/resolve",
                params={
                    "account_number": account_number,
                    "bank_code": bank_code,
                },
                headers={"Authorization": f"Bearer {secret_key}"},
            )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status"):
                name = data.get("data", {}).get("account_name", "")
                if name:
                    logger.info(
                        "Paystack resolve: bank_code=%s acct=%s*** → %s",
                        bank_code, account_number[:4], name,
                    )
                    return name
        logger.warning(
            "Paystack resolve failed: status=%s body=%.200s",
            resp.status_code, resp.text,
        )
    except Exception as exc:
        logger.warning("Paystack resolve error: %s", exc)

    return None
