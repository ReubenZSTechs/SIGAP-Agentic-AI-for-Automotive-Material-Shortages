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
