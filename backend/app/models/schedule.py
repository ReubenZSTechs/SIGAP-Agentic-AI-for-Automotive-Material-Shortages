from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import ScheduleStatus

# Satu-satunya sumber aturan transisi status jadwal (dipakai service & dikirim ke UI).
NEXT_STATUS = {
    ScheduleStatus.PLANNED: [ScheduleStatus.IN_PROGRESS, ScheduleStatus.CANCELLED],
    ScheduleStatus.IN_PROGRESS: [ScheduleStatus.COMPLETED],
}


class Schedule(Base):
    """Master Production Schedule (jadwal produksi harian = satu batch)."""
    __tablename__ = "schedules"
    __table_args__ = (CheckConstraint("target_qty > 0"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_code: Mapped[str] = mapped_column(String(24), unique=True)   # BATCH-YYYYMMDD-NNN, immutable
    product_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    production_line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"))
    production_date: Mapped[date] = mapped_column(Date, index=True)
    target_qty: Mapped[int]
    status: Mapped[ScheduleStatus] = mapped_column(
        Enum(ScheduleStatus, native_enum=False, length=12),
        default=ScheduleStatus.PLANNED)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    product: Mapped["Material"] = relationship()
    line: Mapped["ProductionLine"] = relationship()

    @property
    def product_sku(self) -> str:
        return self.product.sku

    @property
    def product_name(self) -> str:
        return self.product.name

    @property
    def line_code(self) -> str:
        return self.line.code

    @property
    def line_name(self) -> str:
        return self.line.name

    @property
    def allowed_transitions(self) -> list[ScheduleStatus]:
        return NEXT_STATUS.get(self.status, [])

    @property
    def editable(self) -> bool:
        return self.status == ScheduleStatus.PLANNED
