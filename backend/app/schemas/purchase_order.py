from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import POSource, POStatus, StockStatus


class POItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    material_id: int
    sku: str
    name: str
    uom: str
    planning_line_id: int | None
    qty_ordered: float
    unit_price: int
    line_total: int
    qty_received: float
    needed_by_date: date | None = None


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    po_number: str
    supplier_id: int
    supplier_name: str
    planning_run_id: int | None
    status: POStatus
    total_amount: int
    created_at: datetime
    source: POSource
    po_date: date
    notes: str | None = None
    payment_term_days: int = 0
    submitted_at: datetime | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    rejection_reason: str | None = None
    warnings: list[str] = []     # hanya terisi pada respons POST/PATCH Manual PO
    items: list[POItemOut] = []


class POStatusUpdate(BaseModel):
    status: Literal["ISSUED", "CANCELLED"]


class ReceiptItem(BaseModel):
    po_item_id: int
    qty_received: float = Field(gt=0)


class GoodsReceiptRequest(BaseModel):
    items: list[ReceiptItem] = Field(min_length=1)


class StockChange(BaseModel):
    material_id: int
    sku: str
    old_on_hand: float
    received: float
    new_on_hand: float
    available: float
    status: StockStatus


class GoodsReceiptOut(BaseModel):
    po_id: int
    po_number: str
    po_status: POStatus
    changes: list[StockChange]


# ------------------------------- Manual PO -------------------------------
class ManualPOItemIn(BaseModel):
    material_id: int
    qty_ordered: float = Field(gt=0)
    unit_price: int = Field(ge=0)                  # Rupiah (integer, konsisten dengan skema harga)
    needed_by_date: date | None = None


def _no_duplicate(items: list[ManualPOItemIn] | None):
    if items is not None:
        ids = [i.material_id for i in items]
        if len(ids) != len(set(ids)):
            raise ValueError("Material tidak boleh duplikat dalam satu PO")
    return items


class ManualPOCreate(BaseModel):
    supplier_id: int
    po_date: date | None = None                    # default: hari ini
    notes: str | None = Field(default=None, max_length=500)
    items: list[ManualPOItemIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self):
        _no_duplicate(self.items)
        return self


class ManualPOUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_id: int | None = None
    po_date: date | None = None
    notes: str | None = Field(default=None, max_length=500)
    items: list[ManualPOItemIn] | None = Field(default=None, min_length=1)   # replace-all

    @model_validator(mode="after")
    def _check(self):
        _no_duplicate(self.items)
        return self


class ApproveRequest(BaseModel):
    approved_by: str = Field(min_length=2, max_length=80)


class RejectRequest(BaseModel):
    rejected_by: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=3, max_length=300)
