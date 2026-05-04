"""
app/modules/orders/product_descriptions.py

Model and repository for passive product image learning (Option 3 / Approach 2).

When a customer sends a product photo that doesn't match the catalogue, the
image is forwarded to the trader. When the trader replies with a product name
and price, the Claude Vision *text description* of that image is stored here
alongside the confirmed product name and its embedding vector.

Next time a customer sends a similar photo, the new Claude Vision description
is converted to an embedding and compared against stored embeddings using
cosine similarity — this captures semantic meaning, not just word overlap.
"""

import json
import math

import openai

from sqlalchemy import Boolean, Index, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.models.base import BaseModel

logger = get_logger(__name__)

# Minimum cosine similarity (0–1) for a description to be considered a match.
_MATCH_THRESHOLD = 0.82

_EMBEDDING_MODEL = "text-embedding-3-small"


# ── Embedding helpers ────────────────────────────────────────────────────────


async def _generate_embedding(text: str) -> list[float]:
    """Generate an embedding vector for a text description via OpenAI."""
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set — embeddings unavailable")

    client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await client.embeddings.create(
        model=_EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── Model ────────────────────────────────────────────────────────────────────


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

    # Price confirmed by the trader (Naira, whole number)
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The Claude Vision text description of the customer's photo
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # OpenAI text-embedding-3-small vector stored as JSON array
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)

    # True once the trader has confirmed the product identification
    confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    def get_embedding(self) -> list[float] | None:
        """Parse the stored JSON embedding back to a list of floats."""
        if not self.embedding:
            return None
        try:
            return json.loads(self.embedding)
        except (json.JSONDecodeError, TypeError):
            return None


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
        confirmed: bool = True,
    ) -> ProductDescription:
        """Persist a new confirmed product description with its embedding."""
        # Generate embedding for the description
        embedding_json: str | None = None
        try:
            embedding = await _generate_embedding(description)
            embedding_json = json.dumps(embedding)
        except Exception as exc:
            logger.warning(
                "Embedding generation failed for description (saving without): %s", exc
            )

        pd = ProductDescription(
            trader_phone=trader_phone,
            product_name=product_name,
            price=price,
            description=description,
            embedding=embedding_json,
            confirmed=confirmed,
        )
        self._session.add(pd)
        await self._session.flush()
        logger.info(
            "ProductDescription saved id=%s trader=%s product=%s has_embedding=%s",
            pd.id,
            trader_phone,
            product_name,
            embedding_json is not None,
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
        descriptions for this trader using embedding cosine similarity.

        Returns {"product_name": str, "price": int, "similarity": float}
        if a match above the threshold is found, else None.

        Price resolution order:
        1. Catalogue price (latest, if the product exists there)
        2. Stored price from the ProductDescription (trader-confirmed)
        """
        confirmed = await self.list_confirmed_for_trader(trader_phone=trader_phone)
        if not confirmed:
            return None

        # Generate embedding for the new description
        try:
            new_embedding = await _generate_embedding(new_description)
        except Exception as exc:
            logger.warning("Embedding generation failed for matching: %s", exc)
            return None

        best_match: dict | None = None
        best_score = 0.0

        for pd in confirmed:
            stored_embedding = pd.get_embedding()
            if stored_embedding is None:
                continue

            score = _cosine_similarity(new_embedding, stored_embedding)

            if score <= best_score or score < _MATCH_THRESHOLD:
                continue

            # Price resolution: catalogue first (may have updated), then stored price
            price: int | None = None
            for cat_name, cat_price in catalogue.items():
                if cat_name.lower() == pd.product_name.lower():
                    price = cat_price
                    break
            if price is None:
                price = pd.price  # fall back to the trader-confirmed price

            if price is None:
                continue  # no price at all — cannot create an order

            best_score = score
            best_match = {
                "product_name": pd.product_name,
                "price": price,
                "similarity": round(score, 3),
            }

        if best_match:
            logger.info(
                "Embedding match found trader=%s product=%s similarity=%.3f",
                trader_phone,
                best_match["product_name"],
                best_match["similarity"],
            )
        return best_match
