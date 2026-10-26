"""Migrasi kolom idempoten (tanpa Alembic), dijalankan setelah `create_all` saat startup.

`create_all` hanya membuat tabel yang belum ada; kolom baru pada tabel yang sudah ada (mis. database Supabase
produksi) ditambahkan di sini dengan `ADD COLUMN IF NOT EXISTS`, jadi aman dijalankan berulang kali.
"""
import logging

from sqlalchemy import text
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


def apply(engine: Engine) -> None:
    with engine.begin() as conn:
        for sql in STATEMENTS:
            conn.execute(text(sql))
    log.info("db_migrate: %d statements applied", len(STATEMENTS))
