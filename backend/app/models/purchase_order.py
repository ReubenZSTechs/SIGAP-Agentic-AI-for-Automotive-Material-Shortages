from datetime import date, datetime

from sqlalchemy import BigInteger, Date, ForeignKey, Enum, String, DateTime, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import POSource, POStatus


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(24), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    planning_run_id: Mapped[int | None] = mapped_column(ForeignKey("planning_runs.id"))
    status: Mapped[POStatus] = mapped_column(
        Enum(POStatus, native_enum=False, length=20), default=POStatus.DRAFT)
    total_amount: Mapped[int] = mapped_column(BigInteger, default=0)   # Rp (BIGINT: total > 2,1 miliar)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    source: Mapped[POSource] = mapped_column(
        Enum(POSource, native_enum=False, length=10), default=POSource.PLANNING)
    po_date: Mapped[date] = mapped_column(Date, default=date.today)
    notes: Mapped[str | None] = mapped_column(String(500), default=None)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    # Approval tanpa auth (MVP): nama teks. Satu pasangan kolom untuk setuju DAN tolak.
    decided_by: Mapped[str | None] = mapped_column(String(80), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    rejection_reason: Mapped[str | None] = mapped_column(String(300), default=None)

    supplier: Mapped["Supplier"] = relationship()
    items: Mapped[list["POItem"]] = relationship(
        back_populates="po", cascade="all, delete-orphan", order_by="POItem.id")

    @property
    def supplier_name(self) -> str:
        return self.supplier.name

    @property
    def payment_term_days(self) -> int:
        return self.supplier.payment_term_days

    warnings: list = []   # transien (tidak disimpan): peringatan validasi saat buat/ubah Manual PO


class POItem(Base):
    __tablename__ = "po_items"
    __table_args__ = (CheckConstraint("qty_ordered > 0"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    planning_line_id: Mapped[int | None] = mapped_column(ForeignKey("planning_lines.id"))
    qty_ordered: Mapped[float]
    unit_price: Mapped[int] = mapped_column(BigInteger)
    line_total: Mapped[int] = mapped_column(BigInteger)
    qty_received: Mapped[float] = mapped_column(default=0.0)
    needed_by_date: Mapped[date | None] = mapped_column(Date, default=None)

    po: Mapped["PurchaseOrder"] = relationship(back_populates="items")
    material: Mapped["Material"] = relationship()

    @property
    def sku(self) -> str:
        return self.material.sku

    @property
    def name(self) -> str:
        return self.material.name

    @property
    def uom(self) -> str:
        return self.material.uom
