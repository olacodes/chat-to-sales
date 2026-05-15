"""
app/modules/orders/product_images.py

ProductImage model + repository for storing product photos in Cloudflare R2.

One image per product per trader (unique constraint on trader_phone + product_name).
Image URL points to R2. pHash stored for image matching.
"""

from sqlalchemy import Index, String, UniqueConstraint, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import BaseModel


class ProductImage(BaseModel):
    __tablename__ = "product_images"
    __table_args__ = (
        UniqueConstraint("trader_phone", "product_name", name="uq_product_images_trader_product"),
        Index("ix_product_images_trader", "trader_phone"),
    )

    trader_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    image_nobg_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ProductImageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, trader_phone: str, product_name: str) -> ProductImage | None:
        result = await self._session.execute(
            select(ProductImage).where(
                ProductImage.trader_phone == trader_phone,
                ProductImage.product_name == product_name,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        trader_phone: str,
        product_name: str,
        image_url: str,
        image_nobg_url: str | None = None,
        image_hash: str | None = None,
    ) -> ProductImage:
        """Insert or update the image for a product."""
        existing = await self.get(trader_phone, product_name)
        if existing:
            existing.image_url = image_url
            if image_nobg_url is not None:
                existing.image_nobg_url = image_nobg_url
            if image_hash:
                existing.image_hash = image_hash
            await self._session.flush()
            return existing

        img = ProductImage(
            trader_phone=trader_phone,
            product_name=product_name,
            image_url=image_url,
            image_nobg_url=image_nobg_url,
            image_hash=image_hash,
        )
        self._session.add(img)
        await self._session.flush()
        return img

    async def list_for_trader(self, trader_phone: str) -> list[ProductImage]:
        result = await self._session.execute(
            select(ProductImage)
            .where(ProductImage.trader_phone == trader_phone)
            .order_by(ProductImage.product_name)
        )
        return list(result.scalars().all())

    async def delete(self, trader_phone: str, product_name: str) -> None:
        existing = await self.get(trader_phone, product_name)
        if existing:
            await self._session.delete(existing)
            await self._session.flush()
