# MRP & Vendor Sourcing Management — Backend MVP

FastAPI · SQLAlchemy 2.0 (sync) · SQLite · Pydantic v2.
Mengimplementasikan Phase 0 → 5: Master Material & Supplier (many-to-many) → BOM → MPS & Stock Planning
→ Smart Sourcing → Purchase Order multi-vendor → Goods Receipt (loop penutup).

## Menjalankan

Prasyarat: Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                 # opsional; default sudah sqlite:///./mrp.db
python -m scripts.seed --demo-schedules   # isi data contoh dari spesifikasi
uvicorn app.main:app --reload
```

- Swagger UI: <http://127.0.0.1:8000/docs> · Health check: `GET /health`
- Tabel dibuat otomatis saat startup (`create_all`, tanpa Alembic).
- `--demo-schedules` menambah jadwal Senin 30 + Selasa 20 unit pada Senin terdekat dari hari ini. Tanpa flag ini, buat jadwal sendiri via `POST /api/v1/schedules` atau lewat UI.
- **CORS**: origin yang diizinkan diatur lewat `CORS_ORIGINS` di `.env` (default `http://localhost:5173,http://127.0.0.1:5173` = Vite dev server). Frontend juga bisa memakai proxy Vite sehingga CORS tidak terpakai saat development.
- `python -m scripts.seed --reset` menghapus & mengisi ulang database.

## Demo cepat (Phase 2 → 5)

```bash
B=http://127.0.0.1:8000/api/v1
curl -X POST $B/planning/runs -H 'content-type: application/json' \
     -d '{"date_from":"2026-10-12","date_to":"2026-10-13"}'   # sesuaikan dengan tanggal jadwal Anda               # status 🔴🟡🟢
curl "$B/planning/runs/1/sourcing?strategy=CHEAPEST"                       # rekomendasi supplier
curl -X POST $B/planning/runs/1/sourcing/auto-select -H 'content-type: application/json' -d '{"strategy":"FASTEST"}'
curl -X POST $B/planning/runs/1/purchase-orders                            # auto-grouping 1 PO / supplier
curl -X PATCH $B/purchase-orders/1/status -H 'content-type: application/json' -d '{"status":"ISSUED"}'
curl -X POST $B/purchase-orders/1/receipts -H 'content-type: application/json' \
     -d '{"items":[{"po_item_id":1,"qty_received":10}]}'                   # update stok
curl $B/inventory
```

Untuk meniru Phase 4 spesifikasi persis (qty PO ≠ defisit), pilih supplier per baris dengan override qty:
`PUT /planning/lines/{line_id}/selection {"supplier_id": …, "order_qty": 100}`.

## Tes

```bash
pytest -q
```

60 tes: unit (eksplosi 3 level, siklus BOM, MAKE tanpa BOM, strategi sourcing, MOQ, over-receipt, on_order)
dan E2E golden test yang mereproduksi angka spesifikasi (defisit 60/15/25/10; total PO Rp 3.400.000 /
3.500.000 / 2.400.000; stok akhir 180/100/200/170).

## Endpoint (`/api/v1`)

| Modul | Endpoint |
|:--|:--|
| Produk Final | `POST/GET /products` · `GET/PATCH/DELETE /products/{id}` (SKU, nama, satuan, `selling_price`, `specification`, `bom_item_count`) |
| Material Beli | `POST/GET /materials?category=` · `GET/PATCH/DELETE /materials/{id}` — `POST/PATCH/DELETE` hanya untuk kategori `PURCHASED` |
| Relasi Material–Supplier | `POST/GET /materials/{id}/suppliers` · `PATCH/DELETE /materials/{id}/suppliers/{supplier_id}` |
| Supplier | `POST/GET /suppliers` · `GET/PATCH/DELETE /suppliers/{id}` |
| Inventory | `GET /inventory?status=` · `PUT /inventory/{material_id}` · `GET /stock-movements` |
| BOM | `POST /bom/items` · `PUT /bom/{parent_id}/items` · `PATCH/DELETE /bom/items/{id}` · `POST /bom/sub-parts` · `PATCH /bom/sub-parts/{id}` · `GET /bom/{id}/tree` · `GET /bom/{id}/explosion?qty=` |
| MPS (hanya Produk Final) | `POST/GET /schedules` · `PATCH /schedules/{id}` (edit/reschedule, hanya PLANNED) · `PATCH /schedules/{id}/status` · `GET /schedules/{id}/materials` · `GET /production-lines` · `DELETE /schedules/{id}` (alias pembatalan, *deprecated*) |
| Planning | `POST/GET /planning/runs` · `GET /planning/runs/{id}` · `GET /planning/runs/{id}/lines?status=` |
| Smart Sourcing | `GET /planning/runs/{id}/sourcing?strategy=&respect_moq=&max_lead_days=` · `POST …/sourcing/auto-select` · `PUT/DELETE /planning/lines/{line_id}/selection` |
| PO | `POST /planning/runs/{id}/purchase-orders` · `GET /purchase-orders?status=&source=&supplier_id=&planning_run_id=` · **Manual PO:** `POST /purchase-orders` · `PATCH /purchase-orders/{id}` · `POST …/submit` · `POST …/approve` · `POST …/reject` · `GET /purchase-orders/{id}` · `PATCH /purchase-orders/{id}/status` |
| Goods Receipt | `POST /purchase-orders/{id}/receipts` |

Error seragam: `{"detail": "pesan"}` — 400 aturan bisnis, 404 tidak ditemukan, 409 konflik/duplikat/siklus/status, 422 validasi.

## Aturan bisnis ringkas

- **BOM explosion**: BUY = daun, MAKE = sub-assembly (rekursi, multiplier bertingkat); siklus & MAKE tanpa BOM ditolak.
- **Stok Tersedia** = Stok Fisik − Stok Terkunci. `allocated` = gross requirement planning run terakhir (di-overwrite → idempotent).
- **Defisit** = `max(0, safety_stock − (available + on_order))`.
- **Status**: `available ≤ 0` 🔴 CRITICAL · `available < safety` 🟡 WARNING · selain itu 🟢 SAFE.
- **Strategi sourcing**: `CHEAPEST`, `FASTEST`, `BALANCED`; opsi rank-1 = rekomendasi utama.
- **PO**: baris defisit dikelompokkan per supplier terpilih; transisi `DRAFT → ISSUED → PARTIALLY_RECEIVED → RECEIVED`, `DRAFT/ISSUED → CANCELLED`.
- **Goods receipt**: hanya PO `ISSUED/PARTIALLY_RECEIVED`, over-receipt ditolak, atomik, tercatat di `stock_movements`.

## Asumsi data (lihat Plan §0.2)

- Seed memakai **Roda Set = 1 per sepeda** (Ban Luar 2 per set) agar kebutuhan Ban Luar = 100 sesuai spesifikasi; BOM di spesifikasi (Roda Set = 2) akan menghasilkan 200.
- `RM-SBR-01` ditambahkan ke Master (CV Cipta Logam, Rp 18.000, 4 hari). Supplier & harga untuk material BUY lainnya adalah data dummy.
- Auth (`auth.py`, `users.py`, `core/security.py`) dibiarkan kosong/non-aktif — di luar scope MVP.
- Pindah ke PostgreSQL: ubah `DATABASE_URL` di `.env` dan `pip install psycopg2-binary`.

## Penyesuaian untuk frontend

Selain plan backend, ditambahkan (hanya menambah field/parameter, kontrak lama tidak berubah):

- `CORSMiddleware` (`CORS_ORIGINS`).
- `GET /bom/{id}/tree`: tiap node punya `bom_item_id` (`null` untuk root) → dipakai untuk `PATCH/DELETE /bom/items/{id}`.
- Item PO: field `name` (+ `sku`, `uom`) sehingga tabel PO/penerimaan tidak perlu join di klien.
- `GET /purchase-orders?planning_run_id=` → daftar PO milik satu planning run.
- Seed `--demo-schedules` memakai tanggal dinamis (Senin terdekat).

## Kategori item: Produk Final · Material Beli · Sub-part

Semua item tetap berada di satu tabel `materials` (sehingga BOM, jadwal, planning, dan PO tidak berubah), dibedakan oleh `category`:

| `category` | Dikelola di | Keterangan |
|:--|:--|:--|
| `FINISHED` | `/products` | Barang jual: SKU, nama, satuan, `selling_price`, `specification`. Satu-satunya yang bisa dijadwalkan produksi. Tidak boleh jadi komponen BOM. |
| `SUB_PART` | BOM (`POST /bom/sub-parts`) | Item internal ("Made"). Dibuat bersamaan dengan pemasangannya ke induk (atomik); bisa punya komponen sendiri dan dipakai ulang di banyak BOM. |
| `PURCHASED` | `/materials` | Dibeli dari supplier: punya relasi supplier, stok, dan masuk Smart Sourcing / PO. |

`procurement_type` (`BUY`/`MAKE`) kini **diturunkan** dari kategori (hanya `PURCHASED` = `BUY`), jadi tidak bisa tidak konsisten. `POST/PATCH /materials` menolak field `procurement_type`/`category` (422).

## Migrasi database lama

Database SQLite yang dibuat sebelum perubahan ini memakai kolom `procurement_type`. Pilih salah satu:

```bash
python -m scripts.migrate_item_categories      # pertahankan data (backup otomatis: mrp.db.bak)
# atau
python -m scripts.seed --reset --demo-schedules   # mulai dari data contoh
```

Aturan migrasi: `BUY` → `PURCHASED`; `MAKE` yang menjadi komponen BOM lain → `SUB_PART`; `MAKE` lainnya → `FINISHED` (harga jual 0 — isi di halaman Produk Final).

## Jadwal produksi, status, dan sinkronisasi stok

`schedules` kini = satu **batch** (`batch_code` `BATCH-YYYYMMDD-NNN`, tidak berubah saat dipindah) pada satu **production line**. Status: `PLANNED → IN_PROGRESS → COMPLETED`, `PLANNED → CANCELLED` (transisi lain `409`). Edit/reschedule hanya saat PLANNED.

| Aksi | `allocated` (Terkunci) | `on_hand` | Movement |
|:--|:--|:--|:--|
| Buat / edit jadwal | dihitung ulang | – | – |
| Mulai produksi (`IN_PROGRESS`) | − kebutuhan | − kebutuhan | `PRODUCTION_ISSUE` per material (`ref_type=SCHEDULE`) |
| Selesai (`COMPLETED`) | – | – | – |
| Batalkan (`CANCELLED`) | − kebutuhan | – | – |

- `inventory.allocated` adalah **nilai turunan**: Σ kebutuhan semua jadwal PLANNED, dihitung ulang **dari nol** (`allocation_service.recalc_allocated`) setiap jadwal/BOM berubah. `POST /planning/runs` hanya *membaca* nilainya; `PUT /inventory` tidak dapat mengubahnya. Rumus MRP tidak berubah.
- *Mulai produksi* ditolak `409` bila `on_hand` kurang; body memuat `shortages: [{sku, required, on_hand, short_by}]` dan **tidak ada** perubahan data (semua material divalidasi dulu). `available` tidak berubah saat mulai (fisik dan terkunci turun bersamaan).
- Membuat/mengubah jadwal untuk produk dengan **BOM tidak lengkap atau berisi siklus** → `422`. Sebaliknya, mengedit BOM tidak pernah diblokir (hitung ulang bersifat toleran).
- **Planning run basi (`is_stale`)**: setiap mutasi jadwal (buat/edit/pindah/batal), perubahan PO terhitung (submit/reject/cancel Manual PO), dan perubahan `PUT /inventory` menandai semua run DRAFT basi. `POST /planning/runs/{id}/purchase-orders` dari run basi → `409`. Penerimaan barang dan mulai produksi netral (tidak menandai basi).

## Manual PO

PO dibuat langsung oleh pembelian (`source=MANUAL`, `planning_run_id=NULL`); item wajib dari master material beli. Alur:
`DRAFT → PENDING_APPROVAL → APPROVED → ISSUED → PARTIALLY_RECEIVED → RECEIVED`; cabang `REJECTED` (dapat diedit lalu submit ulang) dan `CANCELLED`. PO hasil planning tetap `DRAFT → ISSUED` tanpa approval. Mesin transisi: `po_service.TRANSITIONS[(source, status)]`.

- Approval tanpa auth (MVP): `approved_by` / `rejected_by` berupa teks, disimpan di `decided_by`/`decided_at`. Jalur upgrade ke RBAC: tabel `users(role)` + dependency pada `/approve` & `/reject` (path tidak berubah).
- `on_order` per source (`planning_service.COUNTED`): planning = DRAFT/ISSUED/PARTIALLY_RECEIVED; manual = PENDING_APPROVAL/APPROVED/ISSUED/PARTIALLY_RECEIVED (**manual DRAFT, REJECTED, CANCELLED tidak dihitung**). `GET /inventory` menampilkan `on_order`.
- Validasi: qty > 0, harga ≥ 0 (Rupiah integer), tanggal kebutuhan ≥ tanggal PO, tanpa material duplikat, material PURCHASED aktif, supplier aktif. Supplier yang belum terhubung ke material → **peringatan** (`warnings[]`), bukan error. `suppliers.payment_term_days` = termin (Net N).

## Migrasi dari versi sebelumnya

Urutan untuk database SQLite lama (masing-masing idempoten, backup `.bak` otomatis):

```bash
python -m scripts.migrate_item_categories   # bila masih memakai kolom procurement_type
python -m scripts.migrate_mps_manual_po     # kalender/status jadwal, allocated turunan, Manual PO
```
