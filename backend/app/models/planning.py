from datetime import date, datetime

from sqlalchemy import Boolean, ForeignKey, UniqueConstraint, Enum, Date, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import PlanningRunStatus, StockStatus


class PlanningRun(Base):
    __tablename__ = "planning_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    status: Mapped[PlanningRunStatus] = mapped_column(
        Enum(PlanningRunStatus, native_enum=False, length=16),
        default=PlanningRunStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # True bila jadwal / PO terhitung / stok berubah setelah run dibuat -> harus dijalankan ulang
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)

    lines: Mapped[list["PlanningLine"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="PlanningLine.id")


class PlanningLine(Base):
    __tablename__ = "planning_lines"
    __table_args__ = (UniqueConstraint("run_id", "material_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("planning_runs.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    # --- snapshot hasil Stock Planning ---
    gross_requirement: Mapped[float]
    on_hand: Mapped[float]
    allocated: Mapped[float]
    available: Mapped[float]
    on_order: Mapped[float] = mapped_column(default=0.0)
    safety_stock: Mapped[float]
    shortfall: Mapped[float]
    status: Mapped[StockStatus] = mapped_column(
        Enum(StockStatus, native_enum=False, length=10))
    needed_by: Mapped[date | None] = mapped_column(Date)      # tanggal produksi paling awal
    # --- pilihan user (Smart Sourcing) ---
    selected_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    order_qty: Mapped[float | None]
    unit_price: Mapped[int | None]                            # snapshot harga saat dipilih
    lead_time_days: Mapped[int | None]

    run: Mapped["PlanningRun"] = relationship(back_populates="lines")
    material: Mapped["Material"] = relationship()
    selected_supplier: Mapped["Supplier | None"] = relationship()

    # properti bantu untuk schema output
    @property
    def sku(self) -> str:
        return self.material.sku

    @property
    def material_name(self) -> str:
        return self.material.name

    @property
    def uom(self) -> str:
        return self.material.uom

    @property
    def selected_supplier_name(self) -> str | None:
        return self.selected_supplier.name if self.selected_supplier else None
