from pydantic import BaseModel, ConfigDict, Field


class SupplierCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    contact: str | None = Field(default=None, max_length=200)
    payment_term_days: int = Field(default=0, ge=0, le=365)      # Net N hari


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    contact: str | None = Field(default=None, max_length=200)
    payment_term_days: int | None = Field(default=None, ge=0, le=365)
    is_active: bool | None = None


class SupplierOut(SupplierCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool
