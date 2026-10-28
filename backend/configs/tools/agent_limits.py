"""Batas keputusan otomatis agent PO (diatur manajer di Hub Supplier -> Pengaturan -> Aturan otonomi).

Di dalam batas, agent menerima sendiri perubahan dari supplier; di luar batas, keputusan diteruskan ke
manajer. Semua angka berasal dari `hub_settings.policies.thresholds`, bukan dari LLM:

    delivery_early_days   tanggal kirim boleh sekian hari SEBELUM tenggat (needed-by paling awal di PO)
    delivery_late_days    tanggal kirim boleh sekian hari SESUDAH tenggat
    price_tolerance_pct   harga satuan baru boleh berubah ±X% dari harga PO (naik ATAU turun) -> agent menyetujui
    price_cancel_pct      perubahan melebihi ±Y% (atau harga <= 0) tidak masuk akal -> PO dibatalkan otomatis

Contoh: harga 100.000, toleransi 10%, batal 100% -> 90.000–110.000 disetujui agent; 50.000 atau 150.000 ke manajer;
0 atau 250.000 membatalkan PO tanpa persetujuan manusia (lalu agent mencari supplier pengganti).
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models import HubSettings, PurchaseOrder

KEYS = ("delivery_early_days", "delivery_late_days", "price_tolerance_pct", "price_cancel_pct")
AUTO, MANAGER, CANCEL = "auto", "manager", "cancel"


def limits(db: Session) -> dict:
    """Batas yang berlaku (default dari kebijakan Hub bila baris pengaturan belum ada / kunci lama)."""
    from app.hub.common import DEFAULT_POLICIES          # impor lambat: app.hub.common mengimpor po_actions
    stored = dict(((db.get(HubSettings, 1) or HubSettings(policies={})).policies or {}).get("thresholds") or {})
    if "price_tolerance_pct" not in stored and "price_increase_pct" in stored:     # kunci lama
        stored["price_tolerance_pct"] = stored["price_increase_pct"]
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
        """English (sent to the manager on Telegram)."""
        if self.deadline is None:
            return f"{self.new_date.isoformat()} (PO has no needed-by date)"
        if self.delta_days == 0:
            when = "exactly on the deadline"
        elif self.delta_days < 0:
            when = f"{-self.delta_days} day(s) before the deadline"
        else:
            when = f"{self.delta_days} day(s) after the deadline"
        return (f"{self.new_date.isoformat()} ({when} {self.deadline.isoformat()}; agent limit: "
                f"{self.early_days} day(s) early to {self.late_days} day(s) late)")


def check_date(db: Session, po: PurchaseOrder, new_date: date) -> DateCheck:
    lim = limits(db)
    early, late = int(lim["delivery_early_days"]), int(lim["delivery_late_days"])
    dl = deadline(po)
    if dl is None:
        return DateCheck(True, new_date, None, None, early, late)
    delta = (new_date - dl).days
    return DateCheck(-early <= delta <= late, new_date, dl, delta, early, late)


def price_change_pct(old: int, new: int) -> float:
    """Signed change in percent (+ = more expensive)."""
    if not old:
        return 0.0 if not new else 100.0
    return (new - old) / old * 100


@dataclass
class PriceCheck:
    verdict: str            # auto | manager | cancel
    old: int
    new: int
    pct: float
    tolerance: float
    cancel_at: float

    def describe(self) -> str:
        return (f"Rp{_idr(self.old)} -> Rp{_idr(self.new)} ({self.pct:+.1f}%; agent band ±{self.tolerance:g}%, "
                f"auto-cancel beyond ±{self.cancel_at:g}%)")


def _idr(n) -> str:
    return f"{round(n or 0):,}"


def check_price(db: Session, old: int, new: int, lim: dict | None = None) -> PriceCheck:
    """Where a new unit price falls: inside the ±tolerance band (agent decides), outside it (manager), or so far off
    that it makes no sense (> ±cancel, or price <= 0): the PO is cancelled automatically."""
    lim = lim or limits(db)
    tol, cancel_at = float(lim["price_tolerance_pct"]), float(lim["price_cancel_pct"])
    pct = price_change_pct(old, new)
    if new <= 0 or abs(pct) > cancel_at + 1e-9:
        verdict = CANCEL
    elif abs(pct) <= tol + 1e-9:
        verdict = AUTO
    else:
        verdict = MANAGER
    return PriceCheck(verdict, old, new, pct, tol, cancel_at)


def price_verdict(db: Session, old: int, new: int) -> str:
    return check_price(db, old, new).verdict
