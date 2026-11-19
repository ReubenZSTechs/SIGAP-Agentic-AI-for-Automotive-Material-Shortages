from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.supplier import SupplierCreate, SupplierOut, SupplierUpdate
from app.services import master_service as svc

router = APIRouter()


@router.post("", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier(body: SupplierCreate, db: Session = Depends(get_db)):
    return svc.create_supplier(db, body.model_dump())


@router.get("", response_model=list[SupplierOut])
def list_suppliers(q: str | None = None, is_active: bool | None = None,
                   db: Session = Depends(get_db)):
    return svc.list_suppliers(db, q, is_active)


@router.get("/{supplier_id}", response_model=SupplierOut)
def get_supplier(supplier_id: int, db: Session = Depends(get_db)):
    return svc.get_supplier(db, supplier_id)


@router.patch("/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: int, body: SupplierUpdate, db: Session = Depends(get_db)):
    return svc.update_supplier(db, supplier_id, body.model_dump(exclude_unset=True))


@router.delete("/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier(supplier_id: int, db: Session = Depends(get_db)):
    svc.delete_supplier(db, supplier_id)
