from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import PlanningRunStatus, SourcingStrategy, StockStatus


class PlanningRunCreate(BaseModel):
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def _check_range(self):
        if self.date_from > self.date_to:
            raise ValueError("date_from tidak boleh setelah date_to")
        return self


class PlanningLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    material_id: int
    sku: str | None = None
    material_name: str | None = None
    uom: str | None = None
    gross_requirement: float
    on_hand: float
    allocated: float
    available: float
    on_order: float
    safety_stock: float
    shortfall: float
    status: StockStatus
    needed_by: date | None = None
    selected_supplier_id: int | None
    selected_supplier_name: str | None = None
    order_qty: float | None
    unit_price: int | None = None
    lead_time_days: int | None = None


class PlanningRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    date_from: date
    date_to: date
    status: PlanningRunStatus
    created_at: datetime
    is_stale: bool = False
    n_critical: int = 0
    n_warning: int = 0
    n_safe: int = 0


class PlanningRunDetail(PlanningRunSummary):
    lines: list[PlanningLineOut] = []


class SourcingOption(BaseModel):
    supplier_id: int
    supplier_name: str
    unit_price: int
    lead_time_days: int
    moq: float
    suggested_qty: float
    est_total: int
    meets_moq: bool
    will_be_late: bool
    is_preferred: bool
    is_cheapest: bool
    is_fastest: bool
    rank: int


class SourcingItem(BaseModel):
    line: PlanningLineOut
    deficit: float
    no_supplier: bool = False
    options: list[SourcingOption]


class AutoSelectRequest(BaseModel):
    strategy: SourcingStrategy = SourcingStrategy.CHEAPEST


class AutoSelectResult(BaseModel):
    selected: int
    skipped_no_supplier: list[str]
    lines: list[PlanningLineOut]


class SelectionUpdate(BaseModel):
    supplier_id: int
    order_qty: float | None = Field(default=None, gt=0)
