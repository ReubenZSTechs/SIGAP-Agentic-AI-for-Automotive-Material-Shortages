"""Seed data contoh dari spesifikasi MVP (Phase 0 - 5).

Pemakaian (dari root proyek):
    python -m scripts.seed                    # isi DB kosong
    python -m scripts.seed --demo-schedules   # + jadwal Senin 30 & Selasa 20 unit (Senin terdekat)
    python -m scripts.seed --reset            # drop semua tabel lalu isi ulang

Catatan asumsi (lihat Plan §0.2): Roda Set = 1 set per sepeda (1 set = sepasang
roda) agar kebutuhan Ban Luar = 2 x 50 = 100 sesuai spesifikasi.
"""
import argparse
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.database import Base, SessionLocal, engine
from app.models import (BOMItem, Inventory, Material, MaterialSupplier, ProductionLine, Supplier)
from app.models.enums import ItemCategory

FIN, SUB, BUY = ItemCategory.FINISHED, ItemCategory.SUB_PART, ItemCategory.PURCHASED

# code, name
SUPPLIERS = [
    ("SUP-MTR", "PT Mitra Komponen"),
    ("SUP-MKM", "CV Makmur Bersama"),
    ("SUP-IND", "PT Industri Lokal"),
    ("SUP-KRT", "PT Karet Nusantara"),
    ("SUP-RBR", "CV Rubber Indonesia"),
    ("SUP-CPT", "CV Cipta Logam"),
    ("SUP-BJU", "PT Baja Utama"),
    # supplier tambahan (data dummy) untuk material BUY lain agar seluruh BOM punya sumber
    ("SUP-ASN", "PT Aksesori Sepeda Nusantara"),
    ("SUP-CPR", "CV Cat Prima"),
    ("SUP-BVS", "PT Busa & Vinyl Sejahtera"),
]

# Production line (label; tanpa kapasitas)
LINES = [("LINE-01", "Lini Perakitan 1"), ("LINE-02", "Lini Perakitan 2")]

# Termin pembayaran (hari) per kode supplier; yang tidak tercantum = 0 (tunai)
TERMS = {"SUP-KRT": 30, "SUP-CPT": 14, "SUP-IND": 7, "SUP-MKM": 30, "SUP-MTR": 14, "SUP-BJU": 30}

# sku, nama, uom, kategori (FIN = produk final, SUB = sub-part "Made", BUY = material beli)
MATERIALS = [
    ("FG-BIKE-01", "Sepeda Gunung", "Unit", FIN),
    ("SA-FRAME-01", "Rangka Sepeda / Frame Set", "Set", SUB),
    ("SA-WHEEL-01", "Ban Sepeda / Roda Set", "Set", SUB),
    ("SA-SADDLE-01", "Jok Sepeda / Saddle Set", "Set", SUB),
    ("SA-DRIVE-01", "Sistem Kemudi & Penggerak", "Set", SUB),
    ("RM-STEEL-01", "Besi Tubing / Pipa Baja", "kg", BUY),
    ("RM-SCR-01", "Baut Bintang / Torx Screw M6", "Buah", BUY),
    ("RM-PRM-01", "Cat Dasar / Primer Paint", "ml", BUY),
    ("RM-PNT-01", "Cat Warna / Finishing Paint", "ml", BUY),
    ("RM-RUB-01", "Ban Luar Karet", "Buah", BUY),
    ("RM-TUB-01", "Ban Dalam Karet", "Buah", BUY),
    ("RM-RIM-01", "Velg Besi / Velg Aluminium", "Buah", BUY),
    ("RM-SPK-01", "Jari-Jari / Spoke Besi", "Buah", BUY),
    ("RM-FOM-01", "Busa / Foam Padding", "Buah", BUY),
    ("RM-VNL-01", "Kulit Sintetis / Vinyl Cover", "m²", BUY),
    ("RM-SBR-01", "Rangka Besi Dudukan Jok", "Buah", BUY),
    ("RM-STP-01", "Tiang Jok / Seatpost Besi", "Buah", BUY),
    ("RM-HDL-01", "Stang Besi / Handlebar", "Buah", BUY),
    ("RM-CHN-01", "Rantai Sepeda / Chain", "Buah", BUY),
    ("RM-PDL-01", "Pedal Sepeda", "Buah", BUY),
]

# parent, child, qty_per_parent
BOM = [
    ("FG-BIKE-01", "SA-FRAME-01", 1), ("FG-BIKE-01", "SA-WHEEL-01", 1),
    ("FG-BIKE-01", "SA-SADDLE-01", 1), ("FG-BIKE-01", "SA-DRIVE-01", 1),
    ("SA-FRAME-01", "RM-STEEL-01", 1.5), ("SA-FRAME-01", "RM-SCR-01", 20),
    ("SA-FRAME-01", "RM-PRM-01", 100), ("SA-FRAME-01", "RM-PNT-01", 150),
    ("SA-WHEEL-01", "RM-RUB-01", 2), ("SA-WHEEL-01", "RM-TUB-01", 2),
    ("SA-WHEEL-01", "RM-RIM-01", 2), ("SA-WHEEL-01", "RM-SPK-01", 72),
    ("SA-SADDLE-01", "RM-FOM-01", 1), ("SA-SADDLE-01", "RM-VNL-01", 0.2),
    ("SA-SADDLE-01", "RM-SBR-01", 1), ("SA-SADDLE-01", "RM-STP-01", 1),
    ("SA-DRIVE-01", "RM-HDL-01", 1), ("SA-DRIVE-01", "RM-CHN-01", 1),
    ("SA-DRIVE-01", "RM-PDL-01", 2),
]

# sku: (stok fisik, safety stock)
INVENTORY = {
    "RM-RUB-01": (80, 40), "RM-SBR-01": (50, 15), "RM-STEEL-01": (100, 50), "RM-PDL-01": (120, 30),
    # material lain diberi stok aman agar tidak mengganggu skenario
    "RM-SCR-01": (5000, 500), "RM-PRM-01": (20000, 2000), "RM-PNT-01": (30000, 3000),
    "RM-TUB-01": (500, 50), "RM-RIM-01": (400, 40), "RM-SPK-01": (10000, 1000),
    "RM-FOM-01": (300, 30), "RM-VNL-01": (100, 10), "RM-STP-01": (300, 30),
    "RM-HDL-01": (300, 30), "RM-CHN-01": (300, 30),
}

# sku: [(kode supplier, harga/unit Rp, lead time hari, moq)]
SOURCING = {
    "RM-PDL-01": [("SUP-MTR", 45000, 3, 1), ("SUP-MKM", 42500, 5, 1), ("SUP-IND", 48000, 2, 1)],
    "RM-RUB-01": [("SUP-KRT", 35000, 2, 1), ("SUP-RBR", 37000, 1, 1)],
    "RM-STEEL-01": [("SUP-CPT", 25000, 4, 1), ("SUP-BJU", 24000, 7, 1)],
    "RM-SBR-01": [("SUP-CPT", 18000, 4, 1)],
    "RM-SCR-01": [("SUP-ASN", 500, 3, 100)], "RM-PRM-01": [("SUP-CPR", 150, 3, 500)],
    "RM-PNT-01": [("SUP-CPR", 200, 3, 500)], "RM-TUB-01": [("SUP-KRT", 15000, 2, 1)],
    "RM-RIM-01": [("SUP-ASN", 60000, 4, 1)], "RM-SPK-01": [("SUP-ASN", 400, 4, 100)],
    "RM-FOM-01": [("SUP-BVS", 12000, 3, 1)], "RM-VNL-01": [("SUP-BVS", 40000, 3, 1)],
    "RM-STP-01": [("SUP-ASN", 20000, 4, 1)], "RM-HDL-01": [("SUP-ASN", 35000, 4, 1)],
    "RM-CHN-01": [("SUP-ASN", 30000, 4, 1)],
}


def seed(db: Session, with_schedules: bool = False) -> dict:
    """Isi DB dengan data spesifikasi. Mengembalikan id penting untuk test/demo."""
    if db.scalar(select(Material.id).limit(1)) is not None:
        raise RuntimeError("Database sudah berisi data. Gunakan --reset untuk mengisi ulang.")

    sup = {code: Supplier(code=code, name=name, payment_term_days=TERMS.get(code, 0)) for code, name in SUPPLIERS}
    lines = {code: ProductionLine(code=code, name=name) for code, name in LINES}
    db.add_all(lines.values())
    mat = {sku: Material(sku=sku, name=name, uom=uom, category=cat)
           for sku, name, uom, cat in MATERIALS}
    # Harga jual & spesifikasi produk final (data dummy)
    mat["FG-BIKE-01"].selling_price = 4_500_000
    mat["FG-BIKE-01"].specification = "Sepeda gunung 26 inci, rangka baja tubing, 21 speed"
    db.add_all([*sup.values(), *mat.values()])
    db.flush()

    db.add_all(BOMItem(parent_id=mat[p].id, child_id=mat[c].id, qty_per_parent=q) for p, c, q in BOM)
    db.add_all(Inventory(material_id=mat[sku].id, on_hand=oh, allocated=0, safety_stock=ss)
               for sku, (oh, ss) in INVENTORY.items())
    for sku, rows in SOURCING.items():
        for code, price, lead, moq in rows:
            db.add(MaterialSupplier(material_id=mat[sku].id, supplier_id=sup[code].id,
                                    unit_price=price, lead_time_days=lead, moq=moq))
    db.commit()
    if with_schedules:   # lewat service: kode batch + line + hitung allocated
        from app.services import schedule_service
        monday = date.today() + timedelta(days=(-date.today().weekday()) % 7)   # Senin terdekat (hari ini bila Senin)
        schedule_service.create_schedule(db, mat["FG-BIKE-01"].id, monday, 30, lines["LINE-01"].id)
        schedule_service.create_schedule(db, mat["FG-BIKE-01"].id, monday + timedelta(days=1), 20, lines["LINE-01"].id)
    return {
        "BIKE": mat["FG-BIKE-01"].id, "LINE1": lines["LINE-01"].id, "LINE2": lines["LINE-02"].id,
        "materials": {sku: m.id for sku, m in mat.items()},
        "suppliers": {code: s.id for code, s in sup.items()},
        "KARET": sup["SUP-KRT"].id, "CIPTA": sup["SUP-CPT"].id,
        "INDUSTRI": sup["SUP-IND"].id, "MAKMUR": sup["SUP-MKM"].id,
        "MITRA": sup["SUP-MTR"].id, "BAJA": sup["SUP-BJU"].id, "RUBBER": sup["SUP-RBR"].id,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed data MRP & Vendor Sourcing")
    ap.add_argument("--reset", action="store_true", help="drop & buat ulang semua tabel")
    ap.add_argument("--demo-schedules", action="store_true",
                    help="tambah jadwal Senin 30 & Selasa 20 unit (Senin terdekat dari hari ini)")
    args = ap.parse_args()
    if args.reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        ids = seed(db, with_schedules=args.demo_schedules)
    print(f"Seed selesai: {len(ids['materials'])} material, {len(ids['suppliers'])} supplier.")


if __name__ == "__main__":
    main()
