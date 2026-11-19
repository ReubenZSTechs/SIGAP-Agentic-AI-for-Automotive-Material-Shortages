from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate
from app.services import master_service as svc

router = APIRouter()


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(body: ProductCreate, db: Session = Depends(get_db)):
    return svc.create_product(db, body.model_dump())


@router.get("", response_model=list[ProductOut])
def list_products(q: str | None = None, is_active: bool | None = None,
                  skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                  db: Session = Depends(get_db)):
    return svc.list_products(db, q, is_active, skip, limit)


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    return svc.get_product(db, product_id)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, body: ProductUpdate, db: Session = Depends(get_db)):
    return svc.update_product(db, product_id, body.model_dump(exclude_unset=True))


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    svc.delete_product(db, product_id)
