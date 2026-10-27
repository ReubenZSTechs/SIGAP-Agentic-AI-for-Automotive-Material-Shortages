"""Inventory, Goods Receipt, dan jejak stock movement (Phase 5)."""
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.exceptions import AppError
from app.models import Inventory, Material, PurchaseOrder, StockMovement
from app.models.enums import MovementType, POStatus, StockStatus
from app.services import planning_service
from app.services.planning_service import classify

_EPS = 1e-9


def get_or_create_inventory(db: Session, material_id: int) -> Inventory:
    inv = db.scalar(select(Inventory).where(Inventory.material_id == material_id))
    if inv is None:
        if db.get(Material, material_id) is None:
            raise AppError(404, f"Material id={material_id} tidak ditemukan")
        inv = Inventory(material_id=material_id, on_hand=0.0, allocated=0.0, safety_stock=0.0)
        db.add(inv)
        db.flush()
    return inv


def to_out(inv: Inventory, on_order: dict[int, float] | None = None) -> dict:
    return {
        "material_id": inv.material_id, "sku": inv.material.sku,
        "name": inv.material.name, "uom": inv.material.uom,
        "on_hand": inv.on_hand, "allocated": inv.allocated,
        "available": inv.available, "safety_stock": inv.safety_stock,
        "on_order": round((on_order or {}).get(inv.material_id, 0.0), 6),   # sisa PO terhitung (lihat COUNTED)
        "status": classify(inv.available, inv.safety_stock),
    }


def list_inventory(db: Session, status: StockStatus | None = None) -> list[dict]:
    # joinedload: muat Material dalam query yang sama (to_out membaca inv.material per baris;
    # tanpa ini terjadi N+1 query, satu round-trip ke DB per baris).
    rows = db.scalars(select(Inventory).join(Material, Inventory.material_id == Material.id)
                      .options(joinedload(Inventory.material))
                      .order_by(Material.sku)).all()
    on_order = planning_service._on_order_map(db)
    out = [to_out(i, on_order) for i in rows]
    if status is not None:
        out = [o for o in out if o["status"] == status]
    return out


def update_inventory(db: Session, material_id: int, on_hand: float | None,
                     safety_stock: float | None) -> dict:
    inv = get_or_create_inventory(db, material_id)
    if on_hand is not None and abs(on_hand - inv.on_hand) > _EPS:
        db.add(StockMovement(material_id=material_id, type=MovementType.ADJUSTMENT,
                             qty=on_hand - inv.on_hand, ref_type="MANUAL",
                             note=f"Penyesuaian stok {inv.on_hand:g} → {on_hand:g}"))
        inv.on_hand = on_hand
    changed = on_hand is not None or safety_stock is not None
    if safety_stock is not None:
        inv.safety_stock = safety_stock
    if changed:                                   # on_hand/safety memengaruhi shortfall -> run DRAFT basi
        planning_service.mark_runs_stale(db)      # (allocated TIDAK pernah diubah dari sini)
    db.commit()
    db.refresh(inv)
    return to_out(inv, planning_service._on_order_map(db))


def receive_goods(db: Session, po: PurchaseOrder, receipts: list[tuple[int, float]]) -> list[dict]:
    """Penerimaan barang atomik: validasi semua item dulu, baru mutasi stok."""
    if po.status not in (POStatus.ISSUED, POStatus.PARTIALLY_RECEIVED):
        raise AppError(409, f"PO berstatus {po.status.value} tidak dapat menerima barang")
    items = {i.id: i for i in po.items}

    merged: dict[int, float] = defaultdict(float)              # gabungkan item duplikat di payload
    for po_item_id, qty in receipts:
        merged[po_item_id] += qty

    for po_item_id, qty in merged.items():                     # 1) validasi dulu
        it = items.get(po_item_id)
        if it is None:
            raise AppError(400, f"po_item_id={po_item_id} bukan bagian dari PO ini")
        if qty <= 0 or qty > it.qty_ordered - it.qty_received + _EPS:
            raise AppError(400, f"Qty penerimaan tidak valid (melebihi sisa) untuk item {po_item_id}")

    changes = []
    for po_item_id, qty in merged.items():                     # 2) baru mutasi
        it = items[po_item_id]
        inv = get_or_create_inventory(db, it.material_id)
        old = inv.on_hand
        inv.on_hand += qty
        it.qty_received += qty
        db.add(StockMovement(material_id=it.material_id, type=MovementType.GOODS_RECEIPT,
                             qty=qty, ref_type="PO", ref_id=po.id, note=po.po_number))
        changes.append({"material_id": it.material_id, "sku": it.material.sku,
                        "old_on_hand": old, "received": qty, "new_on_hand": inv.on_hand,
                        "available": inv.available,
                        "status": classify(inv.available, inv.safety_stock)})

    all_done = all(i.qty_received >= i.qty_ordered - _EPS for i in po.items)
    po.status = POStatus.RECEIVED if all_done else POStatus.PARTIALLY_RECEIVED
    db.commit()
    return changes