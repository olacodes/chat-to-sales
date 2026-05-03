"""
app/modules/orders/product_descriptions.py

Model and repository for passive product image learning (Option 3 / Approach 2).

When a customer sends a product photo that doesn't match the catalogue, the
image is forwarded to the trader. When the trader replies with a product name
and price, the Claude Vision *text description* of that image is stored here
alongside the confirmed product name.

Next time a customer sends a similar photo, the new Claude Vision description
is compared against stored descriptions to find a match — no image storage
needed, just text-to-text similarity.
"""

from difflib import SequenceMatcher

from sqlalchemy import Boolean, Index, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.logging import get_logger
from app.core.models.base import BaseModel

logger = get_logger(__name__)

# Minimum similarity score (0–1) for a description to be considered a match.
_MATCH_THRESHOLD = 0.55


class ProductDescription(BaseModel):
    """A confirmed text description of a product image linked to a catalogue item."""

    __tablename__ = "product_descriptions"
    __table_args__ = (
        Index("ix_product_desc_trader_phone", "trader_phone"),
        Index("ix_product_desc_trader_product", "trader_phone", "product_name"),
    )

    # The trader who confirmed this description
    trader_phone: Mapped[str] = mapped_column(String(20), nullable=False)

    # The confirmed product name (matches a catalogue item)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # The Claude Vision text description of the customer's photo
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # True once the trader has confirmed the product identification
    confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


# ── Repository ───────────────────────────────────────────────────────────────


class ProductDescriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        *,
        trader_phone: str,
        product_name: str,
        description: str,
        confirmed: bool = True,
    ) -> ProductDescription:
        """Persist a new confirmed product description."""
        pd = ProductDescription(
            trader_phone=trader_phone,
            product_name=product_name,
            description=description,
            confirmed=confirmed,
        )
        self._session.add(pd)
        await self._session.flush()
        logger.info(
            "ProductDescription saved id=%s trader=%s product=%s",
            pd.id,
            trader_phone,
            product_name,
        )
        return pd

    async def list_confirmed_for_trader(
        self, *, trader_phone: str
    ) -> list[ProductDescription]:
        """Return all confirmed descriptions for a trader."""
        result = await self._session.execute(
            select(ProductDescription)
            .where(
                ProductDescription.trader_phone == trader_phone,
                ProductDescription.confirmed == True,  # noqa: E712
            )
            .order_by(ProductDescription.created_at.desc())
        )
        return list(result.scalars().all())

    async def find_best_match(
        self,
        *,
        trader_phone: str,
        new_description: str,
        catalogue: dict[str, int],
    ) -> dict | None:
        """
        Compare a new Claude Vision description against stored confirmed
        descriptions for this trader using text similarity.

        Returns {"product_name": str, "price": int, "similarity": float}
        if a match above the threshold is found, else None.

        Only returns matches for products that still exist in the catalogue
        (prices may have changed since the description was stored).
        """
        confirmed = await self.list_confirmed_for_trader(trader_phone=trader_phone)
        if not confirmed:
            return None

        new_lower = new_description.lower().strip()
        best_match: dict | None = None
        best_score = 0.0

        for pd in confirmed:
            score = SequenceMatcher(
                None, new_lower, pd.description.lower().strip()
            ).ratio()

            if score <= best_score or score < _MATCH_THRESHOLD:
                continue

            # Verify product still exists in catalogue (case-insensitive)
            price: int | None = None
            for cat_name, cat_price in catalogue.items():
                if cat_name.lower() == pd.product_name.lower():
                    price = cat_price
                    break

            if price is None:
                # Product was removed from catalogue — skip this description
                continue

            best_score = score
            best_match = {
                "product_name": pd.product_name,
                "price": price,
                "similarity": round(score, 3),
            }

        if best_match:
            logger.info(
                "Description match found trader=%s product=%s similarity=%.3f",
                trader_phone,
                best_match["product_name"],
                best_match["similarity"],
            )
        return best_match
