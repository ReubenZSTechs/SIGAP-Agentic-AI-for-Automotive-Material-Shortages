"""Jadwal produksi: nomor batch, validasi, transisi status, dan dampak stok (Delta Plan A & B)."""
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (Inventory, Material, ProductionLine, Schedule, StockMovement)
from app.models.enums import ItemCategory, MovementType, ScheduleStatus
from app.models.schedule import NEXT_STATUS
from app.services import allocation_service, planning_service

_EPS = 1e-9


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)      # UTC naif, sama seperti created_at


def get_schedule(db: Session, schedule_id: int) -> Schedule:
    s = db.get(Schedule, schedule_id)
    if s is None:
        raise AppError(404, "Jadwal tidak ditemukan")
    return s


def next_batch_code(db: Session, d: date) -> str:
    """BATCH-YYYYMMDD-NNN. Tanggal = production_date SAAT DIBUAT; kode tidak berubah saat dipindah."""
    prefix = f"BATCH-{d:%Y%m%d}-"
    n = db.scalar(select(func.count()).select_from(Schedule)
                  .where(Schedule.batch_code.like(f"{prefix}%"))) or 0     # tidak ada DELETE -> count aman
    return f"{prefix}{n + 1:03d}"


def _finished_product(db: Session, product_id: int) -> Material:
    product = db.get(Material, product_id)
    if product is None:
        raise AppError(404, "Produk tidak ditemukan")
    if product.category != ItemCategory.FINISHED:
        raise AppError(422, "Hanya Produk Final yang dapat dijadwalkan produksi")
    return product


def _line(db: Session, line_id: int | None) -> ProductionLine:
    if line_id is None:   # default: line aktif pertama (aturan didokumentasikan di OpenAPI)
        line = db.scalar(select(ProductionLine).where(ProductionLine.is_active).order_by(ProductionLine.code))
        if line is None:
            raise AppError(422, "Belum ada production line aktif")
        return line
    line = db.get(ProductionLine, line_id)
    if line is None:
        raise AppError(404, "Production line tidak ditemukan")
    if not line.is_active:
        raise AppError(422, "Production line nonaktif")
    return line


def create_schedule(db: Session, product_id: int, production_date: date, target_qty: int,
                    line_id: int | None = None) -> Schedule:
    product = _finished_product(db, product_id)
    allocation_service.requirement(db, product.id, target_qty)       # validasi BOM (422) SEBELUM mutasi
    line = _line(db, line_id)
    for attempt in (1, 2):                                           # UNIQUE batch_code menangkap race
        s = Schedule(product_id=product.id, production_date=production_date, target_qty=target_qty,
                     production_line_id=line.id, batch_code=next_batch_code(db, production_date))
        db.add(s)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            if attempt == 2:
                raise
    allocation_service.recalc_allocated(db)
    planning_service.mark_runs_stale(db)
    db.commit()
    db.refresh(s)
    return s


def update_schedule(db: Session, s: Schedule, data: dict) -> Schedule:
    if s.status != ScheduleStatus.PLANNED:
        raise AppError(409, f"Jadwal berstatus {s.status.value} tidak dapat diubah")
    for k, v in data.items():
        if v is None:
            raise AppError(422, f"Field '{k}' tidak boleh null")
    if "product_id" in data:
        _finished_product(db, data["product_id"])
    if "production_line_id" in data:
        _line(db, data["production_line_id"])
    product_id = data.get("product_id", s.product_id)
    qty = data.get("target_qty", s.target_qty)
    allocation_service.requirement(db, product_id, qty)              # validasi BOM sebelum mutasi
    for k, v in data.items():
        setattr(s, k, v)
    db.flush()
    allocation_service.recalc_allocated(db)
    planning_service.mark_runs_stale(db)
    db.commit()
    db.refresh(s)
    return s


def materials_view(db: Session, s: Schedule) -> dict:
    """Alokasi material batch + status stok GLOBAL tiap material (bukan status per batch)."""
    need = allocation_service.requirement(db, s.product_id, s.target_qty)
    mats = {m.id: m for m in db.scalars(select(Material).where(Material.id.in_(need)))}
    invs = {i.material_id: i for i in db.scalars(select(Inventory).where(Inventory.material_id.in_(need)))}
    planned = s.status == ScheduleStatus.PLANNED
    lines = []
    for mid, q in need.items():
        inv = invs.get(mid)
        on_hand = inv.on_hand if inv else 0.0
        allocated = inv.allocated if inv else 0.0
        safety = inv.safety_stock if inv else 0.0
        available = round(on_hand - allocated, 6)
        lines.append({
            "material_id": mid, "sku": mats[mid].sku, "name": mats[mid].name, "uom": mats[mid].uom,
            "required_qty": q, "on_hand": on_hand, "allocated": allocated, "available": available,
            "safety_stock": safety,
            "on_hand_after": round(on_hand - q, 6) if planned else None,
            "enough": on_hand + _EPS >= q,
            "status": planning_service.classify(available, safety),
        })
    lines.sort(key=lambda l: l["sku"])
    return {"schedule_id": s.id, "batch_code": s.batch_code, "basis": "CURRENT_BOM",
            "scope": "GLOBAL_STOCK_STATUS",
            "can_start": planned and all(l["enough"] for l in lines), "lines": lines}


def _issue_materials(db: Session, s: Schedule) -> None:
    """Validasi SEMUA material dulu; baru mutasi on_hand + catat PRODUCTION_ISSUE (atomik)."""
    need = allocation_service.requirement(db, s.product_id, s.target_qty)
    mats = {m.id: m for m in db.scalars(select(Material).where(Material.id.in_(need)))}
    invs = {i.material_id: i for i in db.scalars(select(Inventory).where(Inventory.material_id.in_(need)))}
    on_hand = lambda m: invs[m].on_hand if m in invs else 0.0       # tanpa baris inventory = stok 0
    short = [{"material_id": m, "sku": mats[m].sku, "name": mats[m].name, "uom": mats[m].uom,
              "required": q, "on_hand": on_hand(m), "short_by": round(q - on_hand(m), 6)}
             for m, q in need.items() if on_hand(m) + _EPS < q]
    if short:
        raise AppError(409, "Stok fisik tidak cukup untuk memulai produksi", extra={"shortages": short})
    for m, q in need.items():                                        # semua cukup -> baru mutasi
        invs[m].on_hand -= q
        db.add(StockMovement(material_id=m, type=MovementType.PRODUCTION_ISSUE, qty=-q,
                             ref_type="SCHEDULE", ref_id=s.id, note=s.batch_code))


def change_status(db: Session, s: Schedule, new: ScheduleStatus) -> Schedule:
    if new not in NEXT_STATUS.get(s.status, []):
        raise AppError(409, f"Transisi {s.status.value} → {new.value} tidak valid")
    if new == ScheduleStatus.IN_PROGRESS:
        _issue_materials(db, s)
        s.started_at = _now()
    elif new == ScheduleStatus.COMPLETED:
        s.completed_at = _now()                                      # tanpa efek stok
    s.status = new
    db.flush()
    if new in (ScheduleStatus.IN_PROGRESS, ScheduleStatus.CANCELLED):
        allocation_service.recalc_allocated(db)                      # s keluar dari himpunan PLANNED
    if new == ScheduleStatus.CANCELLED:
        planning_service.mark_runs_stale(db)                         # start netral: available & on_order tetap
    db.commit()
    db.refresh(s)
    return s
