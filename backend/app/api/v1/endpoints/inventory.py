from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import StockMovement
from app.models.enums import MovementType, StockStatus
from app.schemas.inventory import InventoryOut, InventoryUpdate, StockMovementOut
from app.services import inventory_service as svc

router = APIRouter()


@router.get("/inventory", response_model=list[InventoryOut])
def list_inventory(status: StockStatus | None = None, db: Session = Depends(get_db)):
    """Stok live: status dihitung dari `available` vs `safety_stock`."""
    return svc.list_inventory(db, status)


@router.put("/inventory/{material_id}", response_model=InventoryOut)
def update_inventory(material_id: int, body: InventoryUpdate, db: Session = Depends(get_db)):
    """Perubahan `on_hand` dicatat sebagai stock movement ADJUSTMENT."""
    return svc.update_inventory(db, material_id, body.on_hand, body.safety_stock)


@router.get("/stock-movements", response_model=list[StockMovementOut])
def list_stock_movements(material_id: int | None = None, type: MovementType | None = None,
                         skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                         db: Session = Depends(get_db)):
    stmt = select(StockMovement).order_by(StockMovement.id.desc())
    if material_id is not None:
        stmt = stmt.where(StockMovement.material_id == material_id)
    if type is not None:
        stmt = stmt.where(StockMovement.type == type)
    return list(db.scalars(stmt.offset(skip).limit(limit)))
