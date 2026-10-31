from sqlalchemy import BigInteger, String, Enum, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import ItemCategory, ProcurementType


class Material(Base):
    """Satu tabel untuk tiga jenis item, dibedakan oleh `category`:
    PURCHASED (material beli), SUB_PART (internal/"Made"), FINISHED (produk final/barang jual).
    """
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    uom: Mapped[str] = mapped_column(String(16))  # Buah, kg, ml, m²
    category: Mapped[ItemCategory] = mapped_column(
        Enum(ItemCategory, native_enum=False, length=10),
        default=ItemCategory.PURCHASED, index=True)
    selling_price: Mapped[int | None] = mapped_column(BigInteger, default=None)   # Rp; khusus FINISHED
    specification: Mapped[str | None] = mapped_column(String(500), default=None)  # khusus FINISHED
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    supplier_links: Mapped[list["MaterialSupplier"]] = relationship(
        back_populates="material", cascade="all, delete-orphan")
    inventory: Mapped["Inventory | None"] = relationship(
        back_populates="material", uselist=False, cascade="all, delete-orphan")

    @property
    def procurement_type(self) -> ProcurementType:
        """Diturunkan dari kategori (single source of truth): hanya PURCHASED yang BUY."""
        if self.category in (None, ItemCategory.PURCHASED):
            return ProcurementType.BUY
        return ProcurementType.MAKE
