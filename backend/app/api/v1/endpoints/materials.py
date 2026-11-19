from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.enums import ItemCategory
from app.schemas.material import (MaterialCreate, MaterialOut, MaterialSupplierCreate,
                                  MaterialSupplierOut, MaterialSupplierUpdate, MaterialUpdate)
from app.services import master_service as svc

router = APIRouter()


@router.post("", response_model=MaterialOut, status_code=status.HTTP_201_CREATED)
def create_material(body: MaterialCreate, db: Session = Depends(get_db)):
    return svc.create_material(db, body.model_dump())


@router.get("", response_model=list[MaterialOut])
def list_materials(category: ItemCategory | None = None, q: str | None = None,
                   skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                   db: Session = Depends(get_db)):
    return svc.list_materials(db, category, q, skip, limit)


@router.get("/{material_id}", response_model=MaterialOut)
def get_material(material_id: int, db: Session = Depends(get_db)):
    return svc.get_material(db, material_id)


@router.patch("/{material_id}", response_model=MaterialOut)
def update_material(material_id: int, body: MaterialUpdate, db: Session = Depends(get_db)):
    return svc.update_material(db, material_id, body.model_dump(exclude_unset=True))


@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material(material_id: int, db: Session = Depends(get_db)):
    svc.delete_material(db, material_id)


# ---------- Relasi Material <-> Supplier (many-to-many) ----------
@router.post("/{material_id}/suppliers", response_model=MaterialSupplierOut,
             status_code=status.HTTP_201_CREATED)
def add_supplier_link(material_id: int, body: MaterialSupplierCreate, db: Session = Depends(get_db)):
    return svc.add_link(db, material_id, body.model_dump())


@router.get("/{material_id}/suppliers", response_model=list[MaterialSupplierOut])
def list_supplier_links(material_id: int, db: Session = Depends(get_db)):
    return svc.list_links(db, material_id)


@router.patch("/{material_id}/suppliers/{supplier_id}", response_model=MaterialSupplierOut)
def update_supplier_link(material_id: int, supplier_id: int, body: MaterialSupplierUpdate,
                         db: Session = Depends(get_db)):
    return svc.update_link(db, material_id, supplier_id, body.model_dump(exclude_unset=True))


@router.delete("/{material_id}/suppliers/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier_link(material_id: int, supplier_id: int, db: Session = Depends(get_db)):
    svc.delete_link(db, material_id, supplier_id)
