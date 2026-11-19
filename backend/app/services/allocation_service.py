"""`inventory.allocated` = turunan jadwal PLANNED (Delta Plan B1). Selalu dihitung dari nol, tanpa delta."""
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import Inventory, Schedule
from app.models.enums import ScheduleStatus
from app.services import bom_service, inventory_service


def requirement(db: Session, product_id: int, qty: float, graph=None) -> dict[int, float]:
    """Kebutuhan material BUY untuk `qty` unit produk.

    BOM tidak lengkap ATAU siklus -> 422 (keputusan disengaja untuk operasi jadwal).
    """
    try:
        per_unit = bom_service.explode(db, product_id, 1, graph)
    except AppError as e:
        raise AppError(422, e.detail) if e.status_code == 409 else e
    return {m: round(q * qty, 6) for m, q in per_unit.items()}


def recalc_allocated(db: Session, strict: bool = True) -> bool:
    """allocated := Σ kebutuhan SEMUA jadwal PLANNED. Tidak commit (satu transaksi dengan pemanggil).

    strict=False dipakai jalur edit BOM: produk dengan BOM sementara tak lengkap dihitung 0
    (agar mengedit BOM tidak terblokir). Return True bila ada nilai allocated yang berubah.
    """
    graph = bom_service._load_graph(db)
    per_unit: dict[int, dict[int, float]] = {}
    total: dict[int, float] = defaultdict(float)
    for s in db.scalars(select(Schedule).where(Schedule.status == ScheduleStatus.PLANNED)):
        if s.product_id not in per_unit:                       # eksplosi 1 unit, di-cache per produk
            try:
                per_unit[s.product_id] = bom_service.explode(db, s.product_id, 1, graph)
            except AppError:
                if strict:
                    raise
                per_unit[s.product_id] = {}
        for mid, q in per_unit[s.product_id].items():
            total[mid] += q * s.target_qty

    invs = {i.material_id: i for i in db.scalars(
        select(Inventory).execution_options(populate_existing=True))}
    before = {m: i.allocated for m, i in invs.items()}
    for i in invs.values():                                    # dari nol, bukan delta
        i.allocated = 0.0
    for mid, g in total.items():
        inv = invs.get(mid) or inventory_service.get_or_create_inventory(db, mid)
        inv.allocated = round(g, 6)
    db.flush()
    return any(abs(before.get(m, 0.0) - round(total.get(m, 0.0), 6)) > 1e-9
               for m in {*before, *total})
