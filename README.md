# MRP & Vendor Sourcing Management — Fullstack MVP

Alur bisnis end-to-end: **Master Material & Supplier → BOM → Jadwal & Stock Planning → Smart Sourcing → Purchase Order multi-vendor → Goods Receipt → Update Stok**.

| Sisi | Stack | Folder |
|:--|:--|:--|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, SQLite (PostgreSQL opsional) | `backend/` |
| Frontend | React 18, Vite, React Router v6, Zustand, Axios, Tailwind CSS v4 | `frontend/` |

```
.
├── backend/    API FastAPI (+ seed data & 60 tes)
├── frontend/   SPA React (Vite)
├── docs/       rancangan delta (kalender, sinkron stok, Manual PO)
└── README.md
```

## Menjalankan (butuh 2 terminal)

Prasyarat: **Python 3.11+** dan **Node.js 18+** (diuji dengan Node 22).

### Terminal 1 — Backend (http://localhost:8000)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m scripts.seed --demo-schedules    # data contoh + jadwal Senin 30 / Selasa 20 unit
uvicorn app.main:app --reload --port 8000
```

Swagger UI: <http://localhost:8000/docs>

### Terminal 2 — Frontend (http://localhost:5173)

```bash
cd frontend
npm install
npm run dev
```

Buka <http://localhost:5173>. Request `/api/*` otomatis di-*proxy* oleh Vite ke `localhost:8000`; backend juga mengaktifkan CORS untuk `http://localhost:5173` bila Anda memanggil API langsung (ubah `VITE_API_URL` di `frontend/.env`, mis. `http://localhost:8000/api/v1`).

> Port backend selain 8000? Ubah target proxy di `frontend/vite.config.js`.

## Demo cepat (mengikuti dokumen alur)

1. **Material** → baris `RM-PDL-01` → *Supplier*: 3 supplier, label Termurah (CV Makmur Bersama) dan Tercepat (PT Industri Lokal).
2. **Produk Final** → `FG-BIKE-01` (Rp 4.500.000, 4 komponen). **BOM** → Sepeda Gunung: 4 sub-part, 15 material beli; tab *Eksplosi* 50 unit → Ban Luar 100.
3. **MPS & Planning** → *Jalankan Planning* → hasil: Ban −20 🔴, Rangka Jok 0 🔴, Besi 25 🟡, Pedal 20 🟡 (defisit 60 / 15 / 25 / 10).
4. Tab **Sourcing** → pilih supplier dan ubah qty: Pedal → PT Industri Lokal **50**, Besi → CV Cipta Logam **100**, Rangka Jok → CV Cipta Logam **50**, Ban → PT Karet Nusantara **100**.
5. Tab **Purchase Order** → *Konfirmasi*: PO Cipta Logam **Rp 3.400.000**, Karet Nusantara **Rp 3.500.000**, Industri Lokal **Rp 2.400.000**.
6. Buka tiap PO → *Terbitkan* → *Terima Semua*: stok akhir Ban 180 / Rangka 100 / Besi 200 / Pedal 170, semua 🟢 Aman.
7. Jalankan planning lagi → defisit 0.

## Kalender produksi, status batch, dan stok

Menu **MPS & Planning** membuka **Kalender** (Harian/Mingguan/Bulanan); tombol **Tabel** menampilkan data yang sama. Setiap jadwal = satu **batch** (`BATCH-YYYYMMDD-NNN`) pada satu production line.

- **Seret** jadwal *Planned* ke tanggal lain untuk reschedule (jadwal yang sudah berjalan/selesai terkunci). Run planning yang ada otomatis ditandai **basi** → banner + tombol *Jalankan Ulang*.
- **Klik** event → panel batch: info, tombol aksi (**Mulai Produksi**, **Selesaikan**, **Batalkan**, Edit), dan tabel alokasi material (status stok bersifat **global per material**, bukan per batch).
- **Mulai Produksi** menampilkan pratinjau dampak stok (stok fisik sebelum → sesudah). Bila stok fisik kurang, dialog yang sama menampilkan material yang kurang dan tidak ada yang berubah.
- Kolom **Terkunci** di Inventory otomatis mengikuti jadwal PLANNED; tombol **Riwayat** menampilkan pergerakan stok (termasuk *Pemakaian produksi*).
- Contoh: jadwal 30 + 20 unit → Terkunci Ban 100, Pedal 100. Mulai batch Senin → stok fisik Ban 80 → 20, Terkunci 100 → 40, **Tersedia tetap −20**.

## Manual PO

**Purchase Order → + Buat PO Manual**: pilih supplier (termin ditampilkan), tanggal PO, catatan, lalu item dari master material (harga default dari master, lead time per supplier, hint Tersedia/Dipesan/Safety; supplier yang belum terhubung ke material hanya diberi peringatan). Alur: **Submit → Approve/Reject → Terbitkan → Terima barang**. Approver cukup mengisi nama (tanpa login pada MVP). PO hasil planning tetap tanpa approval.

## Membuat produk baru

1. **Produk Final** → *+ Tambah Produk* (SKU, nama, harga jual, spesifikasi).
2. **Material Beli** → tambahkan bahan yang dibeli + supplier-nya (menu *Supplier* pada barisnya); atur stok di **Inventory**.
3. **BOM** → pilih produk → *+ Komponen*: tab **Material Beli** (pilih material) atau **Sub-part (Made)** (buat baru / pakai yang ada). Sub-part punya tombol ＋ sendiri untuk menambah komponennya.
4. **MPS & Planning** → jadwalkan produk (hanya Produk Final) dan jalankan planning.

> **Upgrade dari versi sebelumnya?** Jalankan berurutan `cd backend && python -m scripts.migrate_item_categories` (bila perlu) lalu `python -m scripts.migrate_mps_manual_po` agar database lama dikonversi tanpa kehilangan data. Detail: `backend/README.md`.

Reset data demo: `cd backend && python -m scripts.seed --reset --demo-schedules` (hentikan server dulu bila memakai SQLite).

## Tes

```bash
cd backend && pytest -q          # 60 tes: BOM, planning, sourcing, PO, goods receipt, kontrak frontend, CORS
cd frontend && npm run build     # build produksi
```

Alur UI di atas juga diuji otomatis (vitest + jsdom + Testing Library) terhadap backend sungguhan; hasilnya 24/24 lolos (termasuk drag-and-drop kalender dengan mock FullCalendar). Tes tersebut tidak disertakan agar frontend tetap minimal.

## Catatan asumsi

- **Roda Set = 1 per sepeda** pada data seed (Ban Luar 2 per set) agar kebutuhan Ban Luar = 100 seperti dokumen alur; BOM di dokumen (Roda Set = 2) akan menghasilkan 200.
- `RM-SBR-01` ditambahkan ke Master; supplier/harga untuk material BUY lain adalah data dummy.
- Tidak ada autentikasi (di luar scope MVP). Pindah ke PostgreSQL: ubah `DATABASE_URL` di `backend/.env` dan `pip install psycopg2-binary`.
- Detail endpoint & aturan bisnis: `backend/README.md`.
