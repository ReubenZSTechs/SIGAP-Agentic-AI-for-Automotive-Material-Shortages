"""Migrasi database SQLite lama ke skema Kalender Produksi + Sinkron Stok + Manual PO.

    python -m scripts.migrate_mps_manual_po            # memakai DATABASE_URL dari .env
    python -m scripts.migrate_mps_manual_po --db ./mrp.db

Yang dilakukan (satu transaksi, backup otomatis <db>.bak, aman dijalankan ulang):
  * buat tabel production_lines (LINE-01, LINE-02)
  * schedules: + batch_code (backfill BATCH-YYYYMMDD-NNN), production_line_id (= LINE-01), started_at, completed_at;
    status DONE -> COMPLETED; indeks UNIQUE batch_code
  * planning_runs.is_stale; suppliers.payment_term_days
  * purchase_orders: source (=PLANNING), po_date (= tanggal created_at), notes, submitted_at,
    decided_by, decided_at, rejection_reason; po_items.needed_by_date
  * inventory.allocated dihitung ulang dari jadwal PLANNED (sumber kebenaran baru)
"""
import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

from app.config import settings


def _db_path(url: str) -> str:
    if not url.startswith("sqlite"):
        sys.exit("Skrip ini hanya untuk SQLite. Untuk DB lain, terapkan DDL setara secara manual.")
    return url.split("///", 1)[1]


def _cols(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def migrate(path: str) -> str:
    con = sqlite3.connect(path)
    try:
        if "schedules" not in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            return "Tabel belum ada — tidak ada yang dimigrasi (jalankan aplikasi / seed)."
        if "batch_code" in _cols(con, "schedules"):
            return "Sudah dimigrasi — tidak ada perubahan."

        shutil.copyfile(path, path + ".bak")
        with con:
            con.execute("""CREATE TABLE IF NOT EXISTS production_lines (
                id INTEGER PRIMARY KEY, code VARCHAR(16) NOT NULL UNIQUE,
                name VARCHAR(80) NOT NULL, is_active BOOLEAN NOT NULL DEFAULT 1)""")
            con.execute("INSERT OR IGNORE INTO production_lines (code, name) VALUES ('LINE-01', 'Lini Perakitan 1')")
            con.execute("INSERT OR IGNORE INTO production_lines (code, name) VALUES ('LINE-02', 'Lini Perakitan 2')")
            line1 = con.execute("SELECT id FROM production_lines WHERE code='LINE-01'").fetchone()[0]

            adds = {
                "schedules": ["batch_code VARCHAR(24)", f"production_line_id INTEGER REFERENCES production_lines(id)",
                              "started_at DATETIME", "completed_at DATETIME"],
                "planning_runs": ["is_stale BOOLEAN NOT NULL DEFAULT 0"],
                "suppliers": ["payment_term_days INTEGER NOT NULL DEFAULT 0"],
                "purchase_orders": ["source VARCHAR(10) NOT NULL DEFAULT 'PLANNING'", "po_date DATE", "notes VARCHAR(500)",
                                    "submitted_at DATETIME", "decided_by VARCHAR(80)", "decided_at DATETIME",
                                    "rejection_reason VARCHAR(300)"],
                "po_items": ["needed_by_date DATE"],
            }
            for table, cols in adds.items():
                for c in cols:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {c}")

            con.execute("UPDATE schedules SET status='COMPLETED' WHERE status='DONE'")
            con.execute("UPDATE schedules SET production_line_id=?", (line1,))
            con.execute("UPDATE purchase_orders SET po_date=date(created_at)")
            # backfill kode batch: urut id, nomor urut per tanggal produksi
            seq: dict[str, int] = {}
            for sid, d in con.execute("SELECT id, production_date FROM schedules ORDER BY id").fetchall():
                key = str(d).replace("-", "")[:8]
                seq[key] = seq.get(key, 0) + 1
                con.execute("UPDATE schedules SET batch_code=? WHERE id=?", (f"BATCH-{key}-{seq[key]:03d}", sid))
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_schedules_batch_code ON schedules (batch_code)")

        # allocated := turunan jadwal PLANNED (memakai kode aplikasi agar identik dengan runtime)
        import app.models  # noqa: F401
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from app.services import allocation_service
        eng = create_engine(f"sqlite:///{path}")
        with Session(eng) as db:
            allocation_service.recalc_allocated(db, strict=False)
            db.commit()
        n = con.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]
        return f"Migrasi selesai (backup: {path}.bak). {n} jadwal diberi kode batch; allocated dihitung ulang."
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="path file SQLite (default: dari DATABASE_URL)")
    args = ap.parse_args()
    path = args.db or _db_path(settings.DATABASE_URL)
    if not Path(path).exists():
        sys.exit(f"File database tidak ditemukan: {path}")
    print(migrate(path))
