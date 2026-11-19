from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MovementType, StockStatus


class InventoryUpdate(BaseModel):
    on_hand: float | None = Field(default=None, ge=0)
    safety_stock: float | None = Field(default=None, ge=0)


class InventoryOut(BaseModel):
    material_id: int
    sku: str
    name: str
    uom: str
    on_hand: float          # Stok Fisik
    allocated: float        # Stok Terkunci
    available: float        # Stok Tersedia = on_hand - allocated
    safety_stock: float
    on_order: float = 0.0   # sisa PO terhitung (manual: PENDING/APPROVED/ISSUED/PARTIAL; planning: DRAFT/ISSUED/PARTIAL)
    status: StockStatus


class StockMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    material_id: int
    sku: str
    type: MovementType
    qty: float
    ref_type: str | None
    ref_id: int | None
    note: str | None
    created_at: datetime
