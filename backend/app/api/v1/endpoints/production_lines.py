from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import ProductionLine
from app.schemas.production_line import ProductionLineOut

router = APIRouter()


@router.get("", response_model=list[ProductionLineOut])
def list_production_lines(is_active: bool | None = None, db: Session = Depends(get_db)):
    stmt = select(ProductionLine).order_by(ProductionLine.code)
    if is_active is not None:
        stmt = stmt.where(ProductionLine.is_active == is_active)
    return list(db.scalars(stmt))
