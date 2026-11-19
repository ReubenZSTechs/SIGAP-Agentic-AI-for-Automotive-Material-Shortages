from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ItemCategory, ProcurementType


class MaterialCreate(BaseModel):
    """Input Material = hanya material BELI (purchased). Produk final -> /products, sub-part -> BOM."""
    model_config = ConfigDict(extra="forbid")   # tolak field lama seperti procurement_type
    sku: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    uom: str = Field(min_length=1, max_length=16)


class MaterialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    uom: str | None = Field(default=None, min_length=1, max_length=16)
    is_active: bool | None = None


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sku: str
    name: str
    uom: str
    category: ItemCategory
    procurement_type: ProcurementType        # turunan: PURCHASED=BUY, selain itu MAKE
    selling_price: int | None = None
    specification: str | None = None
    is_active: bool


# ---------- Relasi Material <-> Supplier ----------
class MaterialSupplierCreate(BaseModel):
    supplier_id: int
    unit_price: int = Field(ge=0)
    lead_time_days: int = Field(ge=0)
    moq: float = Field(default=1, gt=0)
    is_preferred: bool = False


class MaterialSupplierUpdate(BaseModel):
    unit_price: int | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0)
    moq: float | None = Field(default=None, gt=0)
    is_preferred: bool | None = None
    is_active: bool | None = None


class MaterialSupplierOut(BaseModel):
    supplier_id: int
    supplier_code: str
    supplier_name: str
    unit_price: int
    lead_time_days: int
    moq: float
    is_preferred: bool
    is_active: bool
    is_cheapest: bool = False
    is_fastest: bool = False
