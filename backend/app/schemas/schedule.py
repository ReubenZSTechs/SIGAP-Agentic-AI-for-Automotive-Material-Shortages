from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ScheduleStatus, StockStatus


class ScheduleCreate(BaseModel):
    product_id: int
    production_date: date
    target_qty: int = Field(gt=0)
    production_line_id: int | None = Field(
        default=None, description="Opsional; bila kosong dipakai production line aktif pertama (urut kode).")


class ScheduleUpdate(BaseModel):
    """Hanya untuk jadwal PLANNED. Status diubah lewat PATCH /schedules/{id}/status."""
    model_config = ConfigDict(extra="forbid")
    production_date: date | None = None
    target_qty: int | None = Field(default=None, gt=0)
    product_id: int | None = None
    production_line_id: int | None = None


class ScheduleStatusUpdate(BaseModel):
    status: Literal["IN_PROGRESS", "COMPLETED", "CANCELLED"]


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    batch_code: str
    product_id: int
    product_sku: str
    product_name: str
    production_line_id: int
    line_code: str
    line_name: str
    production_date: date
    target_qty: int
    status: ScheduleStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    editable: bool                                   # true hanya saat PLANNED
    allowed_transitions: list[ScheduleStatus]        # aturan transisi berasal dari server


class ScheduleMaterialLine(BaseModel):
    material_id: int
    sku: str
    name: str
    uom: str
    required_qty: float
    on_hand: float
    allocated: float
    available: float
    safety_stock: float
    on_hand_after: float | None = None               # on_hand − required; null bila bukan PLANNED
    enough: bool                                     # on_hand >= required
    status: StockStatus                              # status GLOBAL material, bukan per batch


class ScheduleMaterialsOut(BaseModel):
    schedule_id: int
    batch_code: str
    basis: Literal["CURRENT_BOM"]
    scope: Literal["GLOBAL_STOCK_STATUS"]
    can_start: bool
    lines: list[ScheduleMaterialLine]
