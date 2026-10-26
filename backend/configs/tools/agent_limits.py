"""Batas keputusan otomatis agent PO (diatur manajer di Hub Supplier -> Pengaturan -> Aturan otonomi).

Di dalam batas, agent menerima sendiri perubahan dari supplier; di luar batas, keputusan diteruskan ke
manajer. Semua angka berasal dari `hub_settings.policies.thresholds`, bukan dari LLM:

    delivery_early_days   tanggal kirim boleh sekian hari SEBELUM tenggat (needed-by paling awal di PO)
    delivery_late_days    tanggal kirim boleh sekian hari SESUDAH tenggat
    price_increase_pct    harga satuan boleh naik maksimal sekian persen (turun selalu boleh)
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models import HubSettings, PurchaseOrder

KEYS = ("delivery_early_days", "delivery_late_days", "price_increase_pct")


def limits(db: Session) -> dict:
    """Batas yang berlaku (default dari kebijakan Hub bila baris pengaturan belum ada / kunci lama)."""
    from app.hub.common import DEFAULT_POLICIES          # impor lambat: app.hub.common mengimpor po_actions
    stored = ((db.get(HubSettings, 1) or HubSettings(policies={})).policies or {}).get("thresholds") or {}
    return {k: stored.get(k, DEFAULT_POLICIES["thresholds"][k]) for k in KEYS}


def deadline(po: PurchaseOrder) -> date | None:
    """Tenggat PO = needed-by paling awal dari baris yang belum diterima penuh (None = tanpa tenggat)."""
    days = [i.needed_by_date for i in po.items if i.needed_by_date and i.qty_received < i.qty_ordered]
    return min(days) if days else None


@dataclass
class DateCheck:
    ok: bool
    new_date: date
    deadline: date | None
    delta_days: int | None          # new_date - deadline (negatif = lebih awal)
    early_days: int
    late_days: int

    def describe(self) -> str:
        if self.deadline is None:
            return f"{self.new_date.isoformat()} (PO tanpa tanggal kebutuhan)"
        if self.delta_days == 0:
            when = "tepat di tenggat"
        elif self.delta_days < 0:
            when = f"{-self.delta_days} hari lebih awal dari tenggat"
        else:
            when = f"{self.delta_days} hari setelah tenggat"
        return (f"{self.new_date.isoformat()} ({when} {self.deadline.isoformat()}; batas agent: "
                f"{self.early_days} hari lebih awal s/d {self.late_days} hari terlambat)")


def check_date(db: Session, po: PurchaseOrder, new_date: date) -> DateCheck:
    lim = limits(db)
    early, late = int(lim["delivery_early_days"]), int(lim["delivery_late_days"])
    dl = deadline(po)
    if dl is None:
        return DateCheck(True, new_date, None, None, early, late)
    delta = (new_date - dl).days
    return DateCheck(-early <= delta <= late, new_date, dl, delta, early, late)


def price_increase_pct(old: int, new: int) -> float:
    if not old:
        return 0.0 if not new else 100.0
    return (new - old) / old * 100


def price_ok(db: Session, old: int, new: int) -> bool:
    """Turun atau sama selalu boleh; naik boleh sampai `price_increase_pct`."""
    return new <= old or price_increase_pct(old, new) <= float(limits(db)["price_increase_pct"]) + 1e-9
