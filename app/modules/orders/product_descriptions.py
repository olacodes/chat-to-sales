"""
app/modules/orders/product_descriptions.py

Model and repository for passive product image learning (Option 3).

When a customer sends a product photo that doesn't match the catalogue, the
image is forwarded to the trader. When the trader replies with a product name
and price, the image's perceptual hash (pHash) is stored here alongside the
confirmed product name and price.

Next time a customer sends a similar photo, the new image's pHash is compared
against stored hashes using Hamming distance — this compares images directly
without going through text descriptions, making it robust to different
backgrounds, lighting, and minor angle changes.
"""

from sqlalchemy import Boolean, Index, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.logging import get_logger
from app.core.models.base import BaseModel

logger = get_logger(__name__)

# Maximum Hamming distance for two pHashes to be considered a match.
# 0 = identical, ≤12 = same product, >20 = different product.
_MAX_HAMMING_DISTANCE = 12


# ── Model ────────────────────────────────────────────────────────────────────


class ProductDescription(BaseModel):
    """A confirmed product image linked to a catalogue item via its perceptual hash."""

    __tablename__ = "product_descriptions"
    __table_args__ = (
        Index("ix_product_desc_trader_phone", "trader_phone"),
        Index("ix_product_desc_trader_product", "trader_phone", "product_name"),
    )

    # The trader who confirmed this description
    trader_phone: Mapped[str] = mapped_column(String(20), nullable=False)

    # The confirmed product name (matches a catalogue item)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Price confirmed by the trader (Naira, whole number)
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The Claude Vision text description (kept for display/forwarding, not for matching)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # OpenAI text embedding (legacy, no longer used for matching)
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Perceptual hash of the product image (hex string, used for matching)
    image_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

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
        price: int | None = None,
        image_hash: str | None = None,
        confirmed: bool = True,
    ) -> ProductDescription:
        """Persist a new confirmed product description with its image hash."""
        pd = ProductDescription(
            trader_phone=trader_phone,
            product_name=product_name,
            price=price,
            description=description,
            image_hash=image_hash,
            confirmed=confirmed,
        )
        self._session.add(pd)
        await self._session.flush()
        logger.info(
            "ProductDescription saved id=%s trader=%s product=%s has_hash=%s",
            pd.id,
            trader_phone,
            product_name,
            image_hash is not None,
        )
        return pd

    async def list_confirmed_for_trader(
        self, *, trader_phone: str
    ) -> list[ProductDescription]:
        """Return all confirmed descriptions with an image hash for a trader."""
        result = await self._session.execute(
            select(ProductDescription)
            .where(
                ProductDescription.trader_phone == trader_phone,
                ProductDescription.confirmed == True,  # noqa: E712
                ProductDescription.image_hash.is_not(None),
            )
            .order_by(ProductDescription.created_at.desc())
        )
        return list(result.scalars().all())

    async def find_best_match(
        self,
        *,
        trader_phone: str,
        new_image_hash: str,
        catalogue: dict[str, int],
    ) -> dict | None:
        """
        Compare a new image's pHash against stored confirmed image hashes
        for this trader using Hamming distance.

        Returns {"product_name": str, "price": int, "distance": int}
        if a match within the threshold is found, else None.

        Price resolution order:
        1. Catalogue price (latest, if the product exists there)
        2. Stored price from the ProductDescription (trader-confirmed)
        """
        from app.modules.onboarding.media import phash_hamming_distance

        confirmed = await self.list_confirmed_for_trader(trader_phone=trader_phone)
        if not confirmed:
            return None

        best_match: dict | None = None
        best_distance = _MAX_HAMMING_DISTANCE + 1  # start above threshold

        for pd in confirmed:
            if not pd.image_hash:
                continue

            try:
                distance = phash_hamming_distance(new_image_hash, pd.image_hash)
            except (ValueError, TypeError):
                continue

            if distance >= best_distance or distance > _MAX_HAMMING_DISTANCE:
                continue

            # Price resolution: catalogue first (may have updated), then stored price
            price: int | None = None
            for cat_name, cat_price in catalogue.items():
                if cat_name.lower() == pd.product_name.lower():
                    price = cat_price
                    break
            if price is None:
                price = pd.price

            if price is None:
                continue

            best_distance = distance
            best_match = {
                "product_name": pd.product_name,
                "price": price,
                "distance": distance,
            }

        if best_match:
            logger.info(
                "Image hash match found trader=%s product=%s distance=%d",
                trader_phone,
                best_match["product_name"],
                best_match["distance"],
            )
        return best_match
