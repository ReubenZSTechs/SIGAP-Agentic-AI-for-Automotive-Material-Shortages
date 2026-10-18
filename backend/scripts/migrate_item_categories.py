"""Migrasi database SQLite lama (kolom `procurement_type`) ke skema kategori item.

    python -m scripts.migrate_item_categories            # memakai DATABASE_URL dari .env
    python -m scripts.migrate_item_categories --db ./mrp.db

Aturan konversi:
  BUY                                   -> PURCHASED (material beli)
  MAKE yang menjadi komponen BOM lain   -> SUB_PART  (sub-part / "Made")
  MAKE yang bukan komponen siapa pun    -> FINISHED  (produk final; harga jual diisi 0 -> isi lewat halaman Produk Final)

Aman dijalankan ulang (dilewati bila sudah dimigrasi). Backup otomatis: <db>.bak
"""
import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

from app.config import settings


def _db_path(url: str) -> str:
    if not url.startswith("sqlite"):
        sys.exit("Skrip ini hanya untuk SQLite. Untuk DB lain jalankan SQL yang setara secara manual "
                 "(tambah kolom category/selling_price/specification, isi sesuai aturan di atas, hapus procurement_type).")
    return url.split("///", 1)[1]


def migrate(path: str) -> str:
    con = sqlite3.connect(path)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(materials)")]
        if not cols:
            return "Tabel materials belum ada — tidak ada yang dimigrasi (jalankan aplikasi / seed)."
        if "category" in cols:
            return "Sudah dimigrasi — tidak ada perubahan."
        if "procurement_type" not in cols:
            sys.exit("Skema tidak dikenali (kolom procurement_type tidak ditemukan).")

        shutil.copyfile(path, path + ".bak")
        with con:  # satu transaksi
            con.execute("ALTER TABLE materials ADD COLUMN category VARCHAR(10) NOT NULL DEFAULT 'PURCHASED'")
            con.execute("ALTER TABLE materials ADD COLUMN selling_price INTEGER")
            con.execute("ALTER TABLE materials ADD COLUMN specification VARCHAR(500)")
            con.execute("UPDATE materials SET category='PURCHASED' WHERE procurement_type='BUY'")
            con.execute("""UPDATE materials SET category='SUB_PART'
                           WHERE procurement_type='MAKE' AND id IN (SELECT child_id FROM bom_items)""")
            con.execute("""UPDATE materials SET category='FINISHED', selling_price=0
                           WHERE procurement_type='MAKE' AND id NOT IN (SELECT child_id FROM bom_items)""")
            con.execute("ALTER TABLE materials DROP COLUMN procurement_type")   # SQLite >= 3.35
            con.execute("CREATE INDEX IF NOT EXISTS ix_materials_category ON materials (category)")
        n = dict(con.execute("SELECT category, COUNT(*) FROM materials GROUP BY category").fetchall())
        return f"Migrasi selesai (backup: {path}.bak). Hasil: {n}"
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
