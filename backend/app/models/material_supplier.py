from sqlalchemy import ForeignKey, UniqueConstraint, CheckConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MaterialSupplier(Base):
    """Relasi many-to-many Material <-> Supplier dengan atribut komersial."""
    __tablename__ = "material_suppliers"
    __table_args__ = (
        UniqueConstraint("material_id", "supplier_id"),
        CheckConstraint("unit_price >= 0"),
        CheckConstraint("lead_time_days >= 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    unit_price: Mapped[int]  # Rupiah
    lead_time_days: Mapped[int]
    moq: Mapped[float] = mapped_column(default=1.0)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    material: Mapped["Material"] = relationship(back_populates="supplier_links")
    supplier: Mapped["Supplier"] = relationship(back_populates="material_links")
