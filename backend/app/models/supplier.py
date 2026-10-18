from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    contact: Mapped[str | None] = mapped_column(String(200), default=None)
    payment_term_days: Mapped[int] = mapped_column(default=0)     # termin pembayaran (Net N hari)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    material_links: Mapped[list["MaterialSupplier"]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan")
