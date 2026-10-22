import enum


class ProcurementType(str, enum.Enum):
    MAKE = "MAKE"
    BUY = "BUY"


class StockStatus(str, enum.Enum):
    CRITICAL = "CRITICAL"   # 🔴
    WARNING = "WARNING"     # 🟡
    SAFE = "SAFE"           # 🟢


class ScheduleStatus(str, enum.Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PlanningRunStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PO_GENERATED = "PO_GENERATED"


class POStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ISSUED = "ISSUED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class POSource(str, enum.Enum):
    MANUAL = "MANUAL"        # dibuat langsung oleh bagian pembelian (butuh approval)
    PLANNING = "PLANNING"    # hasil planning run (DRAFT -> ISSUED)


class MovementType(str, enum.Enum):
    GOODS_RECEIPT = "GOODS_RECEIPT"
    ADJUSTMENT = "ADJUSTMENT"
    PRODUCTION_ISSUE = "PRODUCTION_ISSUE"   # material keluar gudang saat produksi dimulai


class SourcingStrategy(str, enum.Enum):
    CHEAPEST = "CHEAPEST"
    FASTEST = "FASTEST"
    BALANCED = "BALANCED"


class ItemCategory(str, enum.Enum):
    """Kategori item pada master (menggantikan input MAKE/BUY manual)."""
    PURCHASED = "PURCHASED"   # Material beli dari supplier  -> procurement BUY
    SUB_PART = "SUB_PART"     # Sub-part / produk internal ("Made") -> procurement MAKE
    FINISHED = "FINISHED"     # Produk final (barang jual)   -> procurement MAKE


# ------------------------- Supplier Telegram & otomasi PO -------------------------
class ConversationPurpose(str, enum.Enum):
    CONFIRM_ORDER = "CONFIRM_ORDER"          # minta supplier mengonfirmasi PO yang diterbitkan
    CANCEL_ORDER = "CANCEL_ORDER"            # minta supplier menyetujui pembatalan PO
    REVISION_CONFIRM = "REVISION_CONFIRM"    # revisi yang disetujui manajer dikirim ulang untuk konfirmasi


class ConversationStatus(str, enum.Enum):
    QUEUED = "QUEUED"                        # menunggu giliran (satu percakapan aktif per supplier)
    AWAITING_SUPPLIER = "AWAITING_SUPPLIER"
    REVISION_REQUESTED = "REVISION_REQUESTED"  # supplier minta revisi, menunggu keputusan manajer
    CONFIRMED = "CONFIRMED"
    CANCEL_CONFIRMED = "CANCEL_CONFIRMED"
    DECLINED = "DECLINED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class MessageDirection(str, enum.Enum):
    OUT = "OUT"                  # agent -> supplier
    IN = "IN"                    # supplier -> agent
    MANAGER_OUT = "MANAGER_OUT"  # agent -> manajer
    MANAGER_IN = "MANAGER_IN"    # manajer -> agent


class SupplierConfirmationStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    CANCEL_PENDING = "CANCEL_PENDING"
    REVISION_PENDING = "REVISION_PENDING"


class PORevisionStatus(str, enum.Enum):
    CURRENT = "CURRENT"          # versi yang sedang dibahas dengan supplier
    SUPERSEDED = "SUPERSEDED"    # digantikan revisi yang disetujui manajer
    FINAL = "FINAL"              # dikonfirmasi supplier tanpa perubahan lagi (PDF final dikirim)


class ChangeRequestStatus(str, enum.Enum):
    PENDING_MANAGER = "PENDING_MANAGER"
    AWAITING_MANAGER_CONFIRM = "AWAITING_MANAGER_CONFIRM"   # pilihan teks bebas menunggu tombol konfirmasi
    CHANGE_APPROVED = "CHANGE_APPROVED"
    ABORTED = "ABORTED"
    RESOURCED = "RESOURCED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class AutomationOperation(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    PRODUCE = "PRODUCE"      # jadwal produksi baru + PO multi-supplier untuk material yang kurang


class AutomationStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    EXECUTED = "EXECUTED"
    AWAITING_SUPPLIER = "AWAITING_SUPPLIER"
    FAILED = "FAILED"
