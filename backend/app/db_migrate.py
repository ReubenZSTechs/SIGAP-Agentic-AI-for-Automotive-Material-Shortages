"""Migrasi kolom idempoten (tanpa Alembic), dijalankan setelah `create_all` saat startup.

`create_all` hanya membuat tabel yang belum ada; kolom baru pada tabel yang sudah ada (mis. database Supabase
produksi) ditambahkan di sini dengan `ADD COLUMN IF NOT EXISTS`, jadi aman dijalankan berulang kali.
"""
import logging

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

STATEMENTS = [
    "ALTER TABLE po_change_requests ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'REVISION'",
    "ALTER TABLE hub_missions ADD COLUMN IF NOT EXISTS automation_action_id VARCHAR(36)",
    "ALTER TABLE hub_mission_targets ADD COLUMN IF NOT EXISTS conversation_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_hub_mission_targets_conversation_id ON hub_mission_targets (conversation_id)",
    "ALTER TABLE hub_audit_log ADD COLUMN IF NOT EXISTS actor_type VARCHAR(8)",
    "ALTER TABLE hub_audit_log ADD COLUMN IF NOT EXISTS summary VARCHAR(300)",
    "ALTER TABLE hub_audit_log ADD COLUMN IF NOT EXISTS supplier_id INTEGER",
    "ALTER TABLE hub_audit_log ADD COLUMN IF NOT EXISTS po_number VARCHAR(24)",
    "ALTER TABLE hub_audit_log ADD COLUMN IF NOT EXISTS trace_id VARCHAR(36)",
    "CREATE INDEX IF NOT EXISTS ix_hub_audit_log_actor_type ON hub_audit_log (actor_type)",
    "CREATE INDEX IF NOT EXISTS ix_hub_audit_log_supplier_id ON hub_audit_log (supplier_id)",
    "CREATE INDEX IF NOT EXISTS ix_hub_audit_log_po_number ON hub_audit_log (po_number)",
    # baris audit lama: jenis aktor diturunkan dari nama (sama dengan app.hub.audit_log.actor_type_of)
    "UPDATE hub_audit_log SET actor_type = CASE WHEN lower(actor) LIKE 'agent%' THEN 'AGENT' "
    "WHEN lower(actor) IN ('system', 'sistem', 'worker') THEN 'SYSTEM' ELSE 'MANAGER' END WHERE actor_type IS NULL",
]


# Kolom Rupiah yang dulu INTEGER (maks. 2.147.483.647): pesanan > 2,1 miliar gagal dengan DataError.
MONEY_COLUMNS = [("material_suppliers", "unit_price"), ("materials", "selling_price"), ("planning_lines", "unit_price"),
                 ("po_items", "unit_price"), ("po_items", "line_total"), ("purchase_orders", "total_amount")]
_LOCK_KEY = 7_301_001          # pg_advisory_xact_lock: dua instance tidak pernah memigrasi bersamaan


def widen_money_columns(conn) -> list[str]:
    """INTEGER -> BIGINT for the Rupiah columns that are still INTEGER (no-op once done). Returns what changed.

    Lossless (every value is kept). View chatbot memakai kolom ini dan Postgres menolak ALTER TYPE pada kolom yang
    dipakai view, jadi view di-drop lalu dibuat ulang dengan definisi yang sama, dalam transaksi yang sama.
    """
    narrow = [(t, c) for t, c in MONEY_COLUMNS if conn.execute(text(
        "SELECT data_type FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = :t AND column_name = :c"), {"t": t, "c": c}).scalar() == "integer"]
    if not narrow:
        return []
    from app.chatbot import semantic_views
    savepoint = conn.begin_nested()
    try:
        # ALTER menunggu transaksi lain (mis. worker) yang sedang membaca tabel: jangan menggantung startup;
        # bila terkunci, coba lagi pada startup berikutnya.
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        semantic_views.drop_views(conn)
        for table, column in narrow:
            conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE BIGINT"))
        semantic_views.create_views(conn)
        savepoint.commit()
    except OperationalError:
        savepoint.rollback()
        log.warning("db_migrate: tables busy, BIGINT widening postponed to the next startup")
        return []
    return [f"{t}.{c}" for t, c in narrow]


def apply(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
        for sql in STATEMENTS:
            conn.execute(text(sql))
        widened = widen_money_columns(conn)
    log.info("db_migrate: %d statements applied", len(STATEMENTS))
    if widened:
        log.warning("db_migrate: widened to BIGINT: %s", ", ".join(widened))
