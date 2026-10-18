"""CRUD Master Material, Supplier, dan relasi Material-Supplier (Phase 0)."""
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (BOMItem, Inventory, Material, MaterialSupplier, PlanningLine,
                        POItem, PurchaseOrder, Schedule, StockMovement, Supplier)
from app.models.enums import ItemCategory


def _get(db: Session, model, obj_id: int, label: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise AppError(404, f"{label} id={obj_id} tidak ditemukan")
    return obj


def _exists(db: Session, stmt) -> bool:
    return db.scalar(stmt.limit(1)) is not None


# ------------------------------ Material ------------------------------
def _require_category(m: Material, category: ItemCategory, hint: str) -> None:
    if m.category != category:
        raise AppError(422, hint)


_NOT_PURCHASED = ("Item ini bukan material beli. Produk final dikelola di Master Produk Final, "
                  "sub-part dikelola di BOM.")


def create_material(db: Session, data: dict) -> Material:
    """Material yang dibuat lewat halaman Material selalu berkategori PURCHASED."""
    if _exists(db, select(Material.id).where(Material.sku == data["sku"])):
        raise AppError(409, f"SKU '{data['sku']}' sudah terdaftar")
    m = Material(**data, category=ItemCategory.PURCHASED)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def list_materials(db: Session, category: ItemCategory | None, q: str | None,
                   skip: int, limit: int) -> list[Material]:
    stmt = select(Material).order_by(Material.sku)
    if category is not None:
        stmt = stmt.where(Material.category == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Material.sku.ilike(like), Material.name.ilike(like)))
    return list(db.scalars(stmt.offset(skip).limit(limit)))


def get_material(db: Session, material_id: int) -> Material:
    return _get(db, Material, material_id, "Material")


def update_material(db: Session, material_id: int, data: dict) -> Material:
    m = get_material(db, material_id)
    _require_category(m, ItemCategory.PURCHASED, _NOT_PURCHASED)
    for k, v in data.items():
        setattr(m, k, v)
    db.commit()
    db.refresh(m)
    return m


def _is_used(db: Session, material_id: int) -> bool:
    return (
        _exists(db, select(BOMItem.id).where(or_(BOMItem.parent_id == material_id,
                                                 BOMItem.child_id == material_id)))
        or _exists(db, select(POItem.id).where(POItem.material_id == material_id))
        or _exists(db, select(Schedule.id).where(Schedule.product_id == material_id))
        or _exists(db, select(PlanningLine.id).where(PlanningLine.material_id == material_id))
        or _exists(db, select(StockMovement.id).where(StockMovement.material_id == material_id))
        or _exists(db, select(Inventory.id).where(Inventory.material_id == material_id,
                                                  Inventory.on_hand != 0))
    )


def delete_material(db: Session, material_id: int) -> None:
    m = get_material(db, material_id)
    _require_category(m, ItemCategory.PURCHASED, _NOT_PURCHASED)
    if _is_used(db, material_id):
        raise AppError(409, "Material masih dipakai (BOM/PO/jadwal/planning/stok); "
                            "nonaktifkan dengan PATCH is_active=false")
    db.delete(m)
    db.commit()


# ------------------------- Produk Final (FINISHED) -------------------------
def _product_out(m: Material, count: int) -> dict:
    return {"id": m.id, "sku": m.sku, "name": m.name, "uom": m.uom,
            "selling_price": m.selling_price or 0, "specification": m.specification,
            "is_active": m.is_active, "bom_item_count": count}


def _bom_count(db: Session, material_id: int) -> int:
    return db.scalar(select(func.count()).select_from(BOMItem)
                     .where(BOMItem.parent_id == material_id)) or 0


def create_product(db: Session, data: dict) -> dict:
    if _exists(db, select(Material.id).where(Material.sku == data["sku"])):
        raise AppError(409, f"SKU '{data['sku']}' sudah terdaftar")
    m = Material(**data, category=ItemCategory.FINISHED)
    db.add(m)
    db.commit()
    db.refresh(m)
    return _product_out(m, 0)


def list_products(db: Session, q: str | None, is_active: bool | None,
                  skip: int, limit: int) -> list[dict]:
    stmt = select(Material).where(Material.category == ItemCategory.FINISHED).order_by(Material.sku)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Material.sku.ilike(like), Material.name.ilike(like)))
    if is_active is not None:
        stmt = stmt.where(Material.is_active == is_active)
    rows = list(db.scalars(stmt.offset(skip).limit(limit)))
    counts = dict(db.execute(
        select(BOMItem.parent_id, func.count()).where(
            BOMItem.parent_id.in_([m.id for m in rows])).group_by(BOMItem.parent_id)).all()) if rows else {}
    return [_product_out(m, counts.get(m.id, 0)) for m in rows]


def _get_product(db: Session, product_id: int) -> Material:
    m = db.get(Material, product_id)
    if m is None or m.category != ItemCategory.FINISHED:
        raise AppError(404, f"Produk final id={product_id} tidak ditemukan")
    return m


def get_product(db: Session, product_id: int) -> dict:
    m = _get_product(db, product_id)
    return _product_out(m, _bom_count(db, m.id))


def update_product(db: Session, product_id: int, data: dict) -> dict:
    m = _get_product(db, product_id)
    for k, v in data.items():
        if v is None and k in ("name", "uom", "selling_price", "is_active"):
            raise AppError(422, f"Field '{k}' tidak boleh null")
        setattr(m, k, v)
    db.commit()
    db.refresh(m)
    return _product_out(m, _bom_count(db, m.id))


def delete_product(db: Session, product_id: int) -> None:
    m = _get_product(db, product_id)
    if _is_used(db, product_id):
        raise AppError(409, "Produk masih dipakai (BOM/jadwal/planning); "
                            "nonaktifkan dengan PATCH is_active=false")
    db.delete(m)
    db.commit()


# ------------------------------ Supplier ------------------------------
def create_supplier(db: Session, data: dict) -> Supplier:
    if _exists(db, select(Supplier.id).where(Supplier.code == data["code"])):
        raise AppError(409, f"Kode supplier '{data['code']}' sudah terdaftar")
    s = Supplier(**data)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def list_suppliers(db: Session, q: str | None, is_active: bool | None) -> list[Supplier]:
    stmt = select(Supplier).order_by(Supplier.name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Supplier.code.ilike(like), Supplier.name.ilike(like)))
    if is_active is not None:
        stmt = stmt.where(Supplier.is_active == is_active)
    return list(db.scalars(stmt))


def get_supplier(db: Session, supplier_id: int) -> Supplier:
    return _get(db, Supplier, supplier_id, "Supplier")


def update_supplier(db: Session, supplier_id: int, data: dict) -> Supplier:
    s = get_supplier(db, supplier_id)
    for k, v in data.items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s


def delete_supplier(db: Session, supplier_id: int) -> None:
    s = get_supplier(db, supplier_id)
    used = (
        _exists(db, select(MaterialSupplier.id).where(MaterialSupplier.supplier_id == supplier_id))
        or _exists(db, select(PurchaseOrder.id).where(PurchaseOrder.supplier_id == supplier_id))
        or _exists(db, select(PlanningLine.id).where(PlanningLine.selected_supplier_id == supplier_id))
    )
    if used:
        raise AppError(409, "Supplier masih dipakai (relasi material/PO/planning); "
                            "nonaktifkan dengan PATCH is_active=false")
    db.delete(s)
    db.commit()


# ------------------------ Relasi Material-Supplier ------------------------
def _link_out(l: MaterialSupplier, min_price: int | None, min_lead: int | None) -> dict:
    return {
        "supplier_id": l.supplier_id, "supplier_code": l.supplier.code,
        "supplier_name": l.supplier.name, "unit_price": l.unit_price,
        "lead_time_days": l.lead_time_days, "moq": l.moq,
        "is_preferred": l.is_preferred, "is_active": l.is_active,
        "is_cheapest": l.is_active and l.unit_price == min_price,
        "is_fastest": l.is_active and l.lead_time_days == min_lead,
    }


def list_links(db: Session, material_id: int) -> list[dict]:
    get_material(db, material_id)
    links = list(db.scalars(select(MaterialSupplier)
                            .where(MaterialSupplier.material_id == material_id)
                            .order_by(MaterialSupplier.unit_price)))
    active = [l for l in links if l.is_active]
    min_price = min((l.unit_price for l in active), default=None)
    min_lead = min((l.lead_time_days for l in active), default=None)
    return [_link_out(l, min_price, min_lead) for l in links]


def _find_link(db: Session, material_id: int, supplier_id: int) -> MaterialSupplier:
    link = db.scalar(select(MaterialSupplier).where(
        MaterialSupplier.material_id == material_id,
        MaterialSupplier.supplier_id == supplier_id))
    if link is None:
        raise AppError(404, "Relasi material-supplier tidak ditemukan")
    return link


def add_link(db: Session, material_id: int, data: dict) -> dict:
    get_material(db, material_id)
    get_supplier(db, data["supplier_id"])
    if _exists(db, select(MaterialSupplier.id).where(
            MaterialSupplier.material_id == material_id,
            MaterialSupplier.supplier_id == data["supplier_id"])):
        raise AppError(409, "Supplier sudah terhubung dengan material ini")
    db.add(MaterialSupplier(material_id=material_id, **data))
    db.commit()
    return next(l for l in list_links(db, material_id) if l["supplier_id"] == data["supplier_id"])


def update_link(db: Session, material_id: int, supplier_id: int, data: dict) -> dict:
    get_material(db, material_id)
    link = _find_link(db, material_id, supplier_id)
    for k, v in data.items():
        setattr(link, k, v)
    db.commit()
    return next(l for l in list_links(db, material_id) if l["supplier_id"] == supplier_id)


def delete_link(db: Session, material_id: int, supplier_id: int) -> None:
    link = _find_link(db, material_id, supplier_id)
    db.delete(link)
    db.commit()
