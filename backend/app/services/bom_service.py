"""BOM Explosion, cycle detection, tree builder, dan CRUD BOM."""
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import BOMItem, Material
from app.models.enums import ItemCategory, ProcurementType


def _load_graph(db: Session):
    """Muat seluruh BOM sekali ke memori (adjacency map) -> tanpa N+1 query."""
    adj: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for b in db.scalars(select(BOMItem).order_by(BOMItem.id)):
        adj[b.parent_id].append((b.child_id, b.qty_per_parent))
    types = {m.id: m.procurement_type for m in db.scalars(select(Material))}
    return adj, types


def explode(db: Session, product_id: int, qty: float = 1.0, graph=None) -> dict[int, float]:
    """Return {material_id_BUY: gross_qty} untuk `qty` unit produk.

    Aturan: BUY = daun (masuk hasil); MAKE = sub-assembly (rekursi, multiplier
    dikalikan qty_per_parent); MAKE tanpa BOM -> 422; siklus -> 409.
    """
    adj, types = graph or _load_graph(db)
    if product_id not in types:
        raise AppError(404, "Produk tidak ditemukan")
    if types[product_id] != ProcurementType.MAKE:
        raise AppError(422, "Produk yang dijadwalkan harus bertipe MAKE")

    result: dict[int, float] = defaultdict(float)

    def walk(mid: int, mult: float, path: frozenset[int]) -> None:
        if mid in path:
            raise AppError(409, f"Siklus BOM terdeteksi pada material id={mid}")
        if types[mid] == ProcurementType.BUY:
            result[mid] += mult
            return
        edges = adj.get(mid)
        if not edges:
            raise AppError(422, f"Sub-assembly id={mid} (MAKE) belum memiliki BOM")
        for child_id, q in edges:
            walk(child_id, mult * q, path | {mid})

    walk(product_id, qty, frozenset())
    return {mid: round(q, 6) for mid, q in result.items()}


def would_create_cycle(db: Session, parent_id: int, child_id: int) -> bool:
    """Dipanggil sebelum INSERT bom_item: apakah `parent` terjangkau dari `child`?"""
    adj, _ = _load_graph(db)
    stack, seen = [child_id], set()
    while stack:
        node = stack.pop()
        if node == parent_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(c for c, _ in adj.get(node, []))
    return False


def build_tree(db: Session, root_id: int) -> dict:
    """Pohon BOM nested: {material, level, qty_per_parent, qty_cumulative, children[]}."""
    adj: dict[int, list[BOMItem]] = defaultdict(list)       # termasuk id baris BOM
    for b in db.scalars(select(BOMItem).order_by(BOMItem.id)):
        adj[b.parent_id].append(b)
    mats = {m.id: m for m in db.scalars(select(Material))}
    if root_id not in mats:
        raise AppError(404, "Produk tidak ditemukan")

    def node(mid: int, level: int, qpp: float, cum: float, item_id: int | None,
             path: frozenset[int]) -> dict:
        if mid in path:
            raise AppError(409, f"Siklus BOM terdeteksi pada material id={mid}")
        return {
            "bom_item_id": item_id, "material": mats[mid], "level": level,
            "qty_per_parent": qpp, "qty_cumulative": round(cum, 6),
            "children": [node(b.child_id, level + 1, b.qty_per_parent,
                              cum * b.qty_per_parent, b.id, path | {mid})
                         for b in adj.get(mid, [])],
        }

    return node(root_id, 0, 1.0, 1.0, None, frozenset())


def _after_change(db: Session) -> None:
    """Mutasi BOM mengubah kebutuhan jadwal PLANNED -> hitung ulang allocated (tidak memblokir)."""
    from app.services import allocation_service, planning_service   # import lokal: hindari siklus impor
    db.flush()                                    # sesi autoflush=False: tulis perubahan BOM dulu
    if allocation_service.recalc_allocated(db, strict=False):
        planning_service.mark_runs_stale(db)


# ----------------------------- CRUD BOM -----------------------------
def _get_material(db: Session, material_id: int, label: str) -> Material:
    m = db.get(Material, material_id)
    if m is None:
        raise AppError(404, f"{label} id={material_id} tidak ditemukan")
    return m


def _check_child(child: Material) -> None:
    if child.category == ItemCategory.FINISHED:
        raise AppError(422, "Produk Final tidak dapat menjadi komponen BOM; "
                            "gunakan material beli atau sub-part")


def add_item(db: Session, parent_id: int, child_id: int, qty: float) -> BOMItem:
    parent = _get_material(db, parent_id, "Parent")
    child = _get_material(db, child_id, "Child")
    if parent.procurement_type != ProcurementType.MAKE:
        raise AppError(422, "Parent BOM harus produk final atau sub-part (bukan material beli)")
    _check_child(child)
    dup = db.scalar(select(BOMItem).where(
        BOMItem.parent_id == parent_id, BOMItem.child_id == child_id))
    if dup is not None:
        raise AppError(409, "Relasi BOM parent-child sudah ada")
    if would_create_cycle(db, parent_id, child_id):
        raise AppError(409, "Penambahan item akan menyebabkan siklus BOM")
    item = BOMItem(parent_id=parent_id, child_id=child_id, qty_per_parent=qty)
    db.add(item)
    _after_change(db)
    db.commit()
    db.refresh(item)
    return item


def replace_items(db: Session, parent_id: int, new_items: list[tuple[int, float]]) -> list[BOMItem]:
    """Replace-all BOM satu parent (untuk builder UI). Atomik: gagal -> rollback."""
    parent = _get_material(db, parent_id, "Parent")
    if parent.procurement_type != ProcurementType.MAKE:
        raise AppError(422, "Parent BOM harus produk final atau sub-part (bukan material beli)")
    child_ids = [c for c, _ in new_items]
    if len(child_ids) != len(set(child_ids)):
        raise AppError(409, "Terdapat child duplikat pada daftar item BOM")
    try:
        for cid in child_ids:
            _check_child(_get_material(db, cid, "Child"))
        for old in db.scalars(select(BOMItem).where(BOMItem.parent_id == parent_id)).all():
            db.delete(old)
        db.flush()
        created: list[BOMItem] = []
        for cid, q in new_items:
            if would_create_cycle(db, parent_id, cid):
                raise AppError(409, f"Item child id={cid} akan menyebabkan siklus BOM")
            item = BOMItem(parent_id=parent_id, child_id=cid, qty_per_parent=q)
            db.add(item)
            db.flush()
            created.append(item)
        _after_change(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return list(db.scalars(select(BOMItem).where(BOMItem.parent_id == parent_id)
                           .order_by(BOMItem.id)))


def update_item(db: Session, item_id: int, qty: float) -> BOMItem:
    item = db.get(BOMItem, item_id)
    if item is None:
        raise AppError(404, "Item BOM tidak ditemukan")
    item.qty_per_parent = qty
    _after_change(db)
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, item_id: int) -> None:
    item = db.get(BOMItem, item_id)
    if item is None:
        raise AppError(404, "Item BOM tidak ditemukan")
    db.delete(item)
    _after_change(db)
    db.commit()


# ------------------------- Sub-part (kategori "Made") -------------------------
def add_sub_part(db: Session, parent_id: int, sku: str, name: str, uom: str, qty: float) -> BOMItem:
    """Buat sub-part baru dan pasang ke BOM induk dalam satu transaksi."""
    parent = _get_material(db, parent_id, "Parent")
    if parent.procurement_type != ProcurementType.MAKE:
        raise AppError(422, "Parent BOM harus produk final atau sub-part (bukan material beli)")
    if db.scalar(select(Material.id).where(Material.sku == sku).limit(1)) is not None:
        raise AppError(409, f"SKU '{sku}' sudah terdaftar")
    sub = Material(sku=sku, name=name, uom=uom, category=ItemCategory.SUB_PART)
    db.add(sub)
    db.flush()
    item = BOMItem(parent_id=parent_id, child_id=sub.id, qty_per_parent=qty)
    db.add(item)
    _after_change(db)
    db.commit()
    db.refresh(item)
    return item


def update_sub_part(db: Session, material_id: int, data: dict) -> Material:
    m = _get_material(db, material_id, "Sub-part")
    if m.category != ItemCategory.SUB_PART:
        raise AppError(422, "Item ini bukan sub-part")
    for k, v in data.items():
        if v is None:
            raise AppError(422, f"Field '{k}' tidak boleh null")
        setattr(m, k, v)
    db.commit()
    db.refresh(m)
    return m
