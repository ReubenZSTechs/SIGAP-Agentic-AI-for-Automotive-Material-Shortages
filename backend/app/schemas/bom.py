from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ItemCategory, ProcurementType
from app.schemas.material import MaterialOut


class BOMItemCreate(BaseModel):
    parent_id: int
    child_id: int
    qty_per_parent: float = Field(gt=0)


class BOMItemUpdate(BaseModel):
    qty_per_parent: float = Field(gt=0)


class SubPartCreate(BaseModel):
    """Buat sub-part baru (kategori "Made") sekaligus menambahkannya ke BOM induk — atomik."""
    parent_id: int
    sku: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    uom: str = Field(min_length=1, max_length=16)
    qty_per_parent: float = Field(gt=0)


class SubPartUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    uom: str | None = Field(default=None, min_length=1, max_length=16)
    is_active: bool | None = None


class BOMReplaceItem(BaseModel):
    child_id: int
    qty_per_parent: float = Field(gt=0)


class BOMItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    parent_id: int
    child_id: int
    qty_per_parent: float
    child_sku: str
    child_name: str
    child_uom: str
    child_category: ItemCategory


class BOMTreeNode(BaseModel):
    bom_item_id: int | None = None      # None untuk root (tidak punya induk)
    material: MaterialOut
    level: int
    qty_per_parent: float
    qty_cumulative: float
    children: list["BOMTreeNode"] = []


class ExplosionLine(BaseModel):
    material_id: int
    sku: str
    name: str
    uom: str
    procurement_type: ProcurementType = ProcurementType.BUY
    gross_qty: float
