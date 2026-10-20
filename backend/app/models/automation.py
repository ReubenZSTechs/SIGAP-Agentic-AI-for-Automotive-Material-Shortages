"""Jejak audit setiap perubahan PO yang diusulkan/dijalankan oleh agent dari chat Dashboard."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import AutomationOperation, AutomationStatus


class AutomationAction(Base):
    __tablename__ = "automation_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)          # uuid4 hex
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[AutomationOperation] = mapped_column(Enum(AutomationOperation, native_enum=False, length=12))
    status: Mapped[AutomationStatus] = mapped_column(Enum(AutomationStatus, native_enum=False, length=24),
                                                     default=AutomationStatus.PROPOSED)
    proposal: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, default=None)
    po_id: Mapped[int | None] = mapped_column(default=None)                # tanpa FK: PO bisa dihapus
    po_number: Mapped[str | None] = mapped_column(String(24), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
