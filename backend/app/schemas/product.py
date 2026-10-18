from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    uom: str = Field(default="Unit", min_length=1, max_length=16)
    selling_price: int = Field(ge=0)                       # Rp
    specification: str | None = Field(default=None, max_length=500)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    uom: str | None = Field(default=None, min_length=1, max_length=16)
    selling_price: int | None = Field(default=None, ge=0)
    specification: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sku: str
    name: str
    uom: str
    selling_price: int
    specification: str | None = None
    is_active: bool
    bom_item_count: int = 0                                # jumlah komponen level-1 di BOM
