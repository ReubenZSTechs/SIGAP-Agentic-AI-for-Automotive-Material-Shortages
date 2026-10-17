from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import AppError
from app.models import Material
from app.schemas.bom import (BOMItemCreate, BOMItemOut, BOMItemUpdate, BOMReplaceItem,
                             BOMTreeNode, ExplosionLine, SubPartCreate, SubPartUpdate)
from app.schemas.material import MaterialOut
from app.services import bom_service as svc

router = APIRouter()


@router.post("/items", response_model=BOMItemOut, status_code=status.HTTP_201_CREATED)
def add_bom_item(body: BOMItemCreate, db: Session = Depends(get_db)):
    return svc.add_item(db, body.parent_id, body.child_id, body.qty_per_parent)


@router.post("/sub-parts", response_model=BOMItemOut, status_code=status.HTTP_201_CREATED)
def add_sub_part(body: SubPartCreate, db: Session = Depends(get_db)):
    """Buat sub-part (kategori "Made") baru langsung dari BOM + pasang ke induk (atomik)."""
    return svc.add_sub_part(db, body.parent_id, body.sku, body.name, body.uom, body.qty_per_parent)


@router.patch("/sub-parts/{material_id}", response_model=MaterialOut)
def update_sub_part(material_id: int, body: SubPartUpdate, db: Session = Depends(get_db)):
    return svc.update_sub_part(db, material_id, body.model_dump(exclude_unset=True))


@router.put("/{parent_id}/items", response_model=list[BOMItemOut])
def replace_bom(parent_id: int, items: list[BOMReplaceItem], db: Session = Depends(get_db)):
    """Replace-all BOM satu parent (untuk builder UI)."""
    return svc.replace_items(db, parent_id, [(i.child_id, i.qty_per_parent) for i in items])


@router.patch("/items/{item_id}", response_model=BOMItemOut)
def update_bom_item(item_id: int, body: BOMItemUpdate, db: Session = Depends(get_db)):
    return svc.update_item(db, item_id, body.qty_per_parent)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bom_item(item_id: int, db: Session = Depends(get_db)):
    svc.delete_item(db, item_id)


@router.get("/{product_id}/tree", response_model=BOMTreeNode)
def bom_tree(product_id: int, db: Session = Depends(get_db)):
    return svc.build_tree(db, product_id)


@router.get("/{product_id}/explosion", response_model=list[ExplosionLine])
def bom_explosion(product_id: int, qty: float = Query(1.0, gt=0), db: Session = Depends(get_db)):
    gross = svc.explode(db, product_id, qty)
    mats = {m.id: m for m in db.query(Material).filter(Material.id.in_(gross.keys())).all()} if gross else {}
    if len(mats) != len(gross):
        raise AppError(500, "Inkonsistensi data material pada hasil eksplosi")
    return sorted(
        ({"material_id": mid, "sku": mats[mid].sku, "name": mats[mid].name, "uom": mats[mid].uom,
          "procurement_type": mats[mid].procurement_type, "gross_qty": q}
         for mid, q in gross.items()),
        key=lambda r: r["sku"])
