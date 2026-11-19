from datetime import datetime

from sqlalchemy import ForeignKey, Enum, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import MovementType


class Inventory(Base):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), unique=True)
    on_hand: Mapped[float] = mapped_column(default=0.0)       # Stok Fisik
    allocated: Mapped[float] = mapped_column(default=0.0)     # Stok Terkunci
    safety_stock: Mapped[float] = mapped_column(default=0.0)

    material: Mapped["Material"] = relationship(back_populates="inventory")

    @property
    def available(self) -> float:                             # Stok Tersedia
        return self.on_hand - self.allocated


class StockMovement(Base):
    """Jejak audit setiap perubahan stok fisik."""
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    type: Mapped[MovementType] = mapped_column(
        Enum(MovementType, native_enum=False, length=16))
    qty: Mapped[float]                                        # bertanda (+ masuk / - keluar)
    ref_type: Mapped[str | None] = mapped_column(String(16), default=None)
    ref_id: Mapped[int | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    material: Mapped["Material"] = relationship()

    @property
    def sku(self) -> str:
        return self.material.sku
