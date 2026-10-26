"""Bagian bersama Hub: kebijakan & batas otonomi agent, audit, status Telegram per supplier, akses layanan chat."""
import copy
import logging
import threading
from datetime import datetime, timedelta  # noqa: F401  (timedelta dipakai modul lain via C.)
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.chatbot.config_loader import load_registry
from app.chatbot.service import ChatUnavailable
from app.config import settings
from app.core.exceptions import AppError
from app.models import HubSettings, HubSupplierControl, Supplier, SupplierTelegramLink
from app.models.hub import ThreadMode
from app.supplier_chat.service import (SupplierChatService, get_supplier_chat_service, manager_chat_id)
from app.supplier_chat.transport import build_transport, sandbox_chat_id
from configs.tools import po_actions as A

log = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Jakarta")
COMPANY = "SIGAP"

DEFAULT_POLICIES = {
    "scenarios": [
        {"key": "PO_AGENT", "label": "Konfirmasi & revisi PO (agent PO)", "outbound": "AUTO", "data": "PO", "expiry_hours": None,
         "locked": True, "note": "Tanggal kirim & harga mengikuti Batas keputusan otomatis agent; di luar batas -> manajer"},
        {"key": "PRICE_QUOTE", "label": "Penawaran harga", "outbound": "AUTO", "data": "Harga material-supplier", "expiry_hours": 24},
        {"key": "STOCK_CHECK", "label": "Cek ketersediaan stok", "outbound": "AUTO", "data": "Hasil cek stok", "expiry_hours": 12},
        {"key": "DELIVERY_CONFIRM", "label": "Konfirmasi jadwal kirim", "outbound": "AUTO", "data": "Tanggal janji kirim PO", "expiry_hours": 8},
        {"key": "REMINDER", "label": "Pengingat misi", "outbound": "AUTO", "data": None, "expiry_hours": None},
        {"key": "FREE_TEXT", "label": "Pesan bebas admin", "outbound": "AUTO", "data": None, "expiry_hours": None, "locked": True,
         "note": "Dikirim langsung setelah Anda mengambil alih thread"},
        {"key": "ESCALATION", "label": "Eskalasi", "outbound": "REVIEW", "data": None, "expiry_hours": None, "locked": True},
    ],
    # Batas keputusan otomatis agent (di luar batas -> manajer memutuskan):
    #   delivery_early_days / delivery_late_days: tanggal kirim baru dari supplier boleh sekian hari lebih awal /
    #     lebih lambat dari tenggat (needed-by paling awal di PO) tanpa persetujuan manajer.
    #   price_increase_pct: kenaikan harga satuan (revisi supplier atau supplier pengganti) maksimal sekian persen.
    "thresholds": {"delivery_early_days": 7, "delivery_late_days": 0, "price_increase_pct": 5,
                   "reminder_after_hours": 4, "escalate_after_hours": 24},
    "working_hours": {"days": [1, 2, 3, 4, 5], "start": "08:00", "end": "17:00", "queue_outside": False},
}

def iso(v: datetime | None) -> str | None:
    """Waktu DB (UTC naif) -> ISO dengan akhiran Z agar peramban tidak menganggapnya waktu lokal."""
    return v.isoformat() + "Z" if v is not None else None


def parse_dt(value: str) -> datetime:
    """ISO dari peramban (boleh berakhiran Z/offset) -> UTC naif seperti kolom DB."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise AppError(422, f"Format waktu tidak valid: {value}") from e
    if dt.tzinfo is not None:
        dt = dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return dt


MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def short_local(dt: datetime) -> str:
    """Waktu DB (UTC naif) -> '20 Okt 14.02' WIB untuk teks bukti."""
    local = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
    return f"{local.day} {MONTHS[local.month - 1]} {local.strftime('%H.%M')}"


def greeting(now: datetime | None = None) -> str:
    h = (now or datetime.now(TZ)).astimezone(TZ).hour
    return "pagi" if h < 11 else "siang" if h < 15 else "sore" if h < 18 else "malam"


def contact_name(sup: Supplier) -> str:
    """Bagian pertama kolom kontak (mis. "Pak Hendra, 0812..." -> "Pak Hendra"), atau sapaan umum."""
    first = (sup.contact or "").split(",")[0].strip()
    return first or "Bapak/Ibu"


def fill(template: str, values: dict) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def require_actor(name: str | None) -> str:
    name = (name or "").strip()
    if len(name) < 2:
        raise AppError(422, "Nama approver minimal 2 karakter")
    return name[:80]


# ------------------------------------------ settings ------------------------------------------
def hub_settings(db: Session) -> HubSettings:
    """Baris tunggal id=1; dibuat dengan ON CONFLICT agar aman bila beberapa request pertama datang bersamaan."""
    row = db.get(HubSettings, 1)
    if row is None:
        db.execute(pg_insert(HubSettings).values(id=1, paused=False, policies=copy.deepcopy(DEFAULT_POLICIES))
                   .on_conflict_do_nothing(index_elements=["id"]))
        row = db.get(HubSettings, 1)
    return row


def _with_defaults(p: dict) -> dict:
    """Kebijakan tersimpan + kunci baru dari DEFAULT_POLICIES (baris lama di database tidak perlu dimigrasi)."""
    out = copy.deepcopy(DEFAULT_POLICIES)
    stored = {s["key"]: s for s in p.get("scenarios", [])}
    for s in out["scenarios"]:
        if s["key"] in stored and not s.get("locked"):
            s["outbound"] = stored[s["key"]].get("outbound", s["outbound"])
        if s["key"] in stored and s["expiry_hours"] is not None:
            s["expiry_hours"] = stored[s["key"]].get("expiry_hours") or s["expiry_hours"]
    out["thresholds"].update({k: v for k, v in (p.get("thresholds") or {}).items() if k in out["thresholds"]})
    out["working_hours"].update(p.get("working_hours") or {})
    return out


def policies(db: Session) -> dict:
    return _with_defaults(hub_settings(db).policies or {})


def outbound(db: Session, key: str) -> str:
    return next((s["outbound"] for s in policies(db)["scenarios"] if s["key"] == key), "REVIEW")


def threshold(db: Session, key: str) -> float:
    return policies(db)["thresholds"].get(key, DEFAULT_POLICIES["thresholds"][key])


def expiry_hours(db: Session, key: str, default: int = 24) -> int:
    return next((s.get("expiry_hours") for s in policies(db)["scenarios"] if s["key"] == key), None) or default


def is_paused(db: Session) -> bool:
    return hub_settings(db).paused


def within_working_hours(db: Session, now: datetime | None = None) -> bool:
    """Pengiriman Hub hanya di jam kerja bila `queue_outside` aktif."""
    wh = policies(db)["working_hours"]
    if not wh.get("queue_outside"):
        return True
    local = (now or datetime.now(TZ)).astimezone(TZ)
    day = local.isoweekday() % 7                      # Senin=1 … Sabtu=6, Minggu=0 (sama dengan frontend)
    return day in wh["days"] and wh["start"] <= local.strftime("%H:%M") < wh["end"]


def validate_policies(p: dict) -> dict:
    keys = {s["key"] for s in DEFAULT_POLICIES["scenarios"]}
    scenarios = {s.get("key"): s for s in p.get("scenarios", [])}
    if set(scenarios) != keys:
        raise AppError(422, "Daftar skenario tidak lengkap")
    out = copy.deepcopy(DEFAULT_POLICIES)
    for s in out["scenarios"]:
        given = scenarios[s["key"]]
        if not s.get("locked"):
            if given.get("outbound") not in ("AUTO", "REVIEW"):
                raise AppError(422, f"Otonomi {s['key']} harus AUTO atau REVIEW")
            s["outbound"] = given["outbound"]
        if s["expiry_hours"] is not None:
            h = given.get("expiry_hours")
            if not isinstance(h, (int, float)) or not 1 <= h <= 168:
                raise AppError(422, f"Batas keputusan {s['label']} harus 1–168 jam")
            s["expiry_hours"] = int(h)
    th = p.get("thresholds", {})
    for k in out["thresholds"]:
        v = th.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            raise AppError(422, f"Ambang {k} wajib angka ≥ 0")
        if k in ("delivery_early_days", "delivery_late_days") and (v > 365 or v != int(v)):
            raise AppError(422, f"Batas hari {k} harus bilangan bulat 0–365")
        if k == "price_increase_pct" and v > 100:
            raise AppError(422, "Batas kenaikan harga maksimal 100%")
        out["thresholds"][k] = v
    if out["thresholds"]["escalate_after_hours"] <= out["thresholds"]["reminder_after_hours"]:
        raise AppError(422, "Eskalasi harus lebih lama dari pengingat")
    wh = p.get("working_hours", {})
    days = sorted({int(d) for d in wh.get("days", []) if 0 <= int(d) <= 6})
    if not days:
        raise AppError(422, "Pilih minimal satu hari kerja")
    start, end = str(wh.get("start", "")), str(wh.get("end", ""))
    if len(start) != 5 or len(end) != 5 or start >= end:
        raise AppError(422, "Jam selesai harus setelah jam mulai (format HH:MM)")
    out["working_hours"] = {"days": days, "start": start, "end": end, "queue_outside": bool(wh.get("queue_outside"))}
    return out


from app.hub.audit_log import AGENT_ACTOR, actor_type_of, record as audit  # noqa: E402,F401  (C.audit tetap dipakai)


# --------------------------------------- supplier state ---------------------------------------
def control(db: Session, supplier_id: int) -> HubSupplierControl:
    row = db.scalar(select(HubSupplierControl).where(HubSupplierControl.supplier_id == supplier_id))
    if row is None:
        db.execute(pg_insert(HubSupplierControl).values(supplier_id=supplier_id, mode=ThreadMode.AGENT, last_seen_message_id=0)
                   .on_conflict_do_nothing(index_elements=["supplier_id"]))
        row = db.scalar(select(HubSupplierControl).where(HubSupplierControl.supplier_id == supplier_id))
    return row


def is_human(db: Session, supplier_id: int) -> bool:
    row = db.scalar(select(HubSupplierControl.mode).where(HubSupplierControl.supplier_id == supplier_id))
    return row == ThreadMode.HUMAN


def telegram_state(link: SupplierTelegramLink | None, ctl: HubSupplierControl | None) -> tuple[str, bool]:
    """(CONNECTED | PENDING | NOT_CONNECTED, sandbox?) sama dengan aturan `usable_chat_id`."""
    if link is not None and link.chat_id is not None:
        sandbox = link.chat_id == sandbox_chat_id(link.supplier_id)
        if not (sandbox and settings.TELEGRAM_MODE == "telegram"):
            return "CONNECTED", sandbox
    return ("PENDING" if ctl is not None and ctl.invited_at else "NOT_CONNECTED"), False


def has_open_po_conversation(db: Session, supplier_id: int, active_only: bool = False) -> bool:
    from app.models import SupplierConversation
    statuses = A.ACTIVE_CONVERSATION if active_only else A.OPEN_CONVERSATION
    return db.scalar(select(SupplierConversation.id).where(SupplierConversation.supplier_id == supplier_id,
                                                           SupplierConversation.status.in_(statuses)).limit(1)) is not None


# ---------------------------------------- chat service ----------------------------------------
_offline_lock = threading.Lock()
_offline: SupplierChatService | None = None


def chat_service() -> SupplierChatService:
    """Layanan agent (dengan LLM) bila AI Core terkonfigurasi; bila tidak, versi tanpa agent.

    Versi tanpa agent cukup untuk jalur deterministik: kirim pesan, tombol opsi revisi (pesan memakai
    template cadangan), dan dispatch. Jalur yang butuh LLM melempar `ChatUnavailable` -> 503.
    """
    global _offline
    try:
        return get_supplier_chat_service()
    except ChatUnavailable:
        if _offline is None:
            with _offline_lock:
                if _offline is None:
                    _offline = SupplierChatService({}, load_registry().supplier_chat, build_transport(settings),
                                                   manager_chat_id(), settings.TELEGRAM_BOT_USERNAME)
        return _offline


def require_agent(svc: SupplierChatService, name: str) -> None:
    if name not in svc.agents:
        raise AppError(503, "Agent belum dikonfigurasi: isi AICORE_* di backend/.env untuk memproses balasan supplier.")


def cr_ttl_hours() -> int:
    return load_registry().supplier_chat.get("change_request_ttl_hours", 48)


def after(dt: datetime, hours: float) -> datetime:
    return dt + timedelta(hours=hours)
