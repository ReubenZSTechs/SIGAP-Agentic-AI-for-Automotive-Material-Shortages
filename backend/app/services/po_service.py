"""Purchase Order: auto-grouping dari planning (Phase 4), Manual PO + approval, dan mesin transisi status."""
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (Material, MaterialSupplier, POItem, PlanningRun, PurchaseOrder, Supplier)
from app.models.enums import ItemCategory, PlanningRunStatus, POSource, POStatus
from app.services import planning_service

S, SRC = POStatus, POSource

# (source, status) -> status berikutnya yang valid.
# ISSUED -> PARTIALLY_RECEIVED -> RECEIVED hanya lewat Goods Receipt (kedua source).
TRANSITIONS: dict[tuple[POSource, POStatus], set[POStatus]] = {
    (SRC.MANUAL, S.DRAFT): {S.PENDING_APPROVAL, S.CANCELLED},
    (SRC.MANUAL, S.PENDING_APPROVAL): {S.APPROVED, S.REJECTED, S.CANCELLED},
    (SRC.MANUAL, S.APPROVED): {S.ISSUED, S.CANCELLED},
    (SRC.MANUAL, S.REJECTED): {S.PENDING_APPROVAL, S.CANCELLED},      # edit lalu submit ulang
    (SRC.MANUAL, S.ISSUED): {S.CANCELLED},
    (SRC.PLANNING, S.DRAFT): {S.ISSUED, S.CANCELLED},                  # alur lama, tanpa approval
    (SRC.PLANNING, S.ISSUED): {S.CANCELLED},
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _next_po_number(db: Session) -> str:
    """Nomor terbesar yang PERNAH dipakai bulan ini + 1.

    Bukan COUNT: setelah hard delete, COUNT bisa menghasilkan nomor yang masih dipakai PO lain.
    Nomor PO yang sudah dihapus (tercatat di percakapan supplier / audit agent) juga tidak dipakai ulang.
    """
    from app.models import AutomationAction, SupplierConversation   # hindari import siklik
    prefix = f"PO-{datetime.now():%Y%m}-"
    used = [db.scalar(select(func.max(col)).where(col.like(f"{prefix}%")))
            for col in (PurchaseOrder.po_number, SupplierConversation.po_number, AutomationAction.po_number)]
    last = max((u for u in used if u), default=None)
    seq = int(last.rsplit("-", 1)[1]) if last else 0
    return f"{prefix}{seq + 1:04d}"


def transition(db: Session, po: PurchaseOrder, new: POStatus) -> None:
    """Satu-satunya pintu perubahan status (kecuali Goods Receipt). Tidak commit."""
    if new not in TRANSITIONS.get((po.source, po.status), set()):
        raise AppError(409, f"Transisi {po.status.value} → {new.value} tidak valid untuk PO {po.source.value}")
    counted = planning_service.COUNTED[po.source]
    before = po.status in counted
    po.status = new
    if (po.status in counted) != before:        # himpunan on_order berubah -> run DRAFT basi (cegah pesan ganda)
        planning_service.mark_runs_stale(db)


def get_po(db: Session, po_id: int) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise AppError(404, "Purchase Order tidak ditemukan")
    return po


def _require_manual(po: PurchaseOrder) -> None:
    if po.source != POSource.MANUAL:
        raise AppError(409, "Hanya Manual PO yang melalui alur approval/edit; PO hasil planning tidak dapat diubah")


# ---------------------------- PO hasil planning (Phase 4) ----------------------------
def generate_pos(db: Session, run: PlanningRun) -> list[PurchaseOrder]:
    if run.status == PlanningRunStatus.PO_GENERATED:
        raise AppError(409, "PO untuk planning run ini sudah dibuat")
    if run.is_stale:
        raise AppError(409, "Run basi — jadwal, PO, atau stok berubah sejak run dibuat. Jalankan ulang planning.")
    lines = [l for l in run.lines if l.shortfall > 0]
    if not lines:
        raise AppError(400, "Tidak ada defisit; tidak ada PO yang perlu dibuat")
    missing = [l.material.sku for l in lines if l.selected_supplier_id is None]
    if missing:
        raise AppError(400, f"Supplier belum dipilih untuk: {', '.join(missing)}")

    groups: dict[int, list] = defaultdict(list)                # auto-grouping per supplier
    for l in lines:
        groups[l.selected_supplier_id].append(l)

    pos = []
    for supplier_id, ls in groups.items():
        po = PurchaseOrder(po_number=_next_po_number(db), supplier_id=supplier_id,
                           planning_run_id=run.id, status=POStatus.DRAFT, source=POSource.PLANNING,
                           po_date=date.today())
        for l in ls:
            po.items.append(POItem(
                material_id=l.material_id, planning_line_id=l.id,
                qty_ordered=l.order_qty, unit_price=l.unit_price,
                line_total=round(l.order_qty * l.unit_price)))
        po.total_amount = sum(i.line_total for i in po.items)
        db.add(po)
        db.flush()                                             # agar nomor PO berikutnya benar
        pos.append(po)
    run.status = PlanningRunStatus.PO_GENERATED
    db.commit()
    for po in pos:
        db.refresh(po)
    return pos


def change_status(db: Session, po: PurchaseOrder, new_status: POStatus) -> PurchaseOrder:
    """PATCH /status: ISSUED & CANCELLED (submit/approve/reject punya endpoint sendiri)."""
    transition(db, po, new_status)
    db.commit()
    db.refresh(po)
    return po


# ------------------------------------ Manual PO ------------------------------------
def _active_supplier(db: Session, supplier_id: int) -> Supplier:
    sup = db.get(Supplier, supplier_id)
    if sup is None:
        raise AppError(404, "Supplier tidak ditemukan")
    if not sup.is_active:
        raise AppError(422, "Supplier nonaktif")
    return sup


def _build_items(db: Session, supplier: Supplier, po_date: date, items: list[dict]) -> tuple[list[POItem], list[str]]:
    ids = [i["material_id"] for i in items]
    if len(ids) != len(set(ids)):
        raise AppError(422, "Material tidak boleh duplikat dalam satu PO")
    mats = {m.id: m for m in db.scalars(select(Material).where(Material.id.in_(ids)))}
    linked = {l.material_id for l in db.scalars(select(MaterialSupplier).where(
        MaterialSupplier.supplier_id == supplier.id, MaterialSupplier.is_active))}
    out, warnings = [], []
    for it in items:
        m = mats.get(it["material_id"])
        if m is None:
            raise AppError(404, f"Material id={it['material_id']} tidak ditemukan")
        if m.category != ItemCategory.PURCHASED or not m.is_active:
            raise AppError(422, f"{m.sku}: hanya material beli yang aktif dari master yang dapat dipesan")
        if it.get("needed_by_date") and it["needed_by_date"] < po_date:
            raise AppError(422, f"{m.sku}: tanggal kebutuhan tidak boleh sebelum tanggal PO")
        if m.id not in linked:
            warnings.append(f"{m.sku}: supplier belum terdaftar untuk material ini")
        out.append(POItem(material_id=m.id, qty_ordered=it["qty_ordered"], unit_price=it["unit_price"],
                          line_total=round(it["qty_ordered"] * it["unit_price"]),
                          needed_by_date=it.get("needed_by_date")))
    return out, warnings


def create_manual(db: Session, data: dict) -> PurchaseOrder:
    supplier = _active_supplier(db, data["supplier_id"])
    po_date = data.get("po_date") or date.today()
    items, warnings = _build_items(db, supplier, po_date, data["items"])
    po = PurchaseOrder(po_number=_next_po_number(db), supplier_id=supplier.id, planning_run_id=None,
                       source=POSource.MANUAL, status=POStatus.DRAFT, po_date=po_date,
                       notes=data.get("notes"))
    po.items = items
    po.total_amount = sum(i.line_total for i in items)
    db.add(po)
    db.commit()
    db.refresh(po)
    po.warnings = warnings
    return po


def update_manual(db: Session, po: PurchaseOrder, data: dict) -> PurchaseOrder:
    _require_manual(po)
    if po.status not in (POStatus.DRAFT, POStatus.REJECTED):
        raise AppError(409, f"PO berstatus {po.status.value} tidak dapat diedit")
    supplier = _active_supplier(db, data.get("supplier_id", po.supplier_id))
    po_date = data.get("po_date", po.po_date)
    warnings: list[str] = []
    if "items" in data:
        items, warnings = _build_items(db, supplier, po_date, data["items"])
        po.items = items                                          # replace-all (orphan dihapus)
    else:                                                         # supplier/tanggal berubah -> validasi ulang item lama
        _, warnings = _build_items(db, supplier, po_date, [
            {"material_id": i.material_id, "qty_ordered": i.qty_ordered, "unit_price": i.unit_price,
             "needed_by_date": i.needed_by_date} for i in po.items])
    po.supplier_id, po.po_date = supplier.id, po_date
    if "notes" in data:
        po.notes = data["notes"]
    po.total_amount = sum(i.line_total for i in po.items)
    db.commit()
    db.refresh(po)
    po.warnings = warnings
    return po


def submit(db: Session, po: PurchaseOrder) -> PurchaseOrder:
    _require_manual(po)
    if not po.items:
        raise AppError(422, "PO tanpa item tidak dapat disubmit")
    transition(db, po, POStatus.PENDING_APPROVAL)
    po.submitted_at = _now()
    po.decided_by = po.decided_at = po.rejection_reason = None    # submit ulang membersihkan keputusan lama
    db.commit()
    db.refresh(po)
    return po


def approve(db: Session, po: PurchaseOrder, approved_by: str) -> PurchaseOrder:
    _require_manual(po)
    transition(db, po, POStatus.APPROVED)
    po.decided_by, po.decided_at = approved_by.strip(), _now()
    db.commit()
    db.refresh(po)
    return po


def reject(db: Session, po: PurchaseOrder, rejected_by: str, reason: str) -> PurchaseOrder:
    _require_manual(po)
    transition(db, po, POStatus.REJECTED)
    po.decided_by, po.decided_at, po.rejection_reason = rejected_by.strip(), _now(), reason.strip()
    db.commit()
    db.refresh(po)
    return po


# ------------------------- Otomasi agent: hapus PO & revisi supplier -------------------------
NOT_DELETABLE = (POStatus.PARTIALLY_RECEIVED, POStatus.RECEIVED)
_REVISABLE_FIELDS = ("qty_ordered", "unit_price", "needed_by_date")


def _has_receipts(po: PurchaseOrder) -> bool:
    return any(i.qty_received > 0 for i in po.items)


def delete_po(db: Session, po: PurchaseOrder) -> None:
    """Hard delete (item ikut terhapus). Mengembalikan logika stok lewat derivasi:

    * `on_order` dihitung dari baris PO berstatus COUNTED -> otomatis turun saat PO dihapus;
      run DRAFT ditandai basi agar tidak dipakai untuk membuat PO ganda/kurang.
    * Run planning asal (PO_GENERATED) ditandai basi agar terlihat perlu dijalankan ulang.
    * Ditolak bila barang sudah diterima (stok fisik sudah bertambah; butuh proses retur).
    """
    if po.status in NOT_DELETABLE or _has_receipts(po):
        raise AppError(409, f"PO {po.po_number} sudah menerima barang ({po.status.value}); tidak dapat dihapus")
    if po.status in planning_service.COUNTED[po.source]:
        planning_service.mark_runs_stale(db)
    if po.planning_run_id is not None:
        run = db.get(PlanningRun, po.planning_run_id)
        if run is not None:
            run.is_stale = True
    db.delete(po)
    db.commit()


def apply_supplier_revision(db: Session, po: PurchaseOrder, changes: list[dict]) -> PurchaseOrder:
    """Revisi PO ISSUED (belum ada penerimaan) atas permintaan supplier yang disetujui manajer.

    `changes`: [{po_item_id, field: qty_ordered|unit_price|needed_by_date, new}] (sudah tervalidasi).
    """
    if po.status != POStatus.ISSUED or _has_receipts(po):
        raise AppError(409, f"PO {po.po_number} berstatus {po.status.value}; revisi hanya untuk PO ISSUED tanpa penerimaan")
    items = {i.id: i for i in po.items}
    qty_changed = False
    for c in changes:
        it = items.get(c["po_item_id"])
        if it is None or c["field"] not in _REVISABLE_FIELDS:
            raise AppError(422, f"Perubahan tidak valid: {c}")
        new = c["new"]
        if c["field"] == "qty_ordered":
            if new <= 0:
                raise AppError(422, f"{it.sku}: qty harus > 0")
            qty_changed |= new != it.qty_ordered
            it.qty_ordered = float(new)
        elif c["field"] == "unit_price":
            if new < 0:
                raise AppError(422, f"{it.sku}: harga tidak boleh negatif")
            it.unit_price = int(new)
        else:
            new = date.fromisoformat(new) if isinstance(new, str) else new
            if new < po.po_date:
                raise AppError(422, f"{it.sku}: tanggal kebutuhan tidak boleh sebelum tanggal PO")
            it.needed_by_date = new
        it.line_total = round(it.qty_ordered * it.unit_price)
    po.total_amount = sum(i.line_total for i in po.items)
    if qty_changed:                     # on_order berubah -> run DRAFT basi
        planning_service.mark_runs_stale(db)
    db.commit()
    db.refresh(po)
    return po
