# MRP & Vendor Sourcing Management — Fullstack MVP

Alur bisnis end-to-end: **Master Material & Supplier → BOM → Jadwal & Stock Planning → Smart Sourcing → Purchase Order multi-vendor → Goods Receipt → Update Stok**.

| Sisi | Stack | Folder |
|:--|:--|:--|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, PostgreSQL (Supabase) | `backend/` |
| Chatbot | LangGraph, SAP AI Core (gpt-5.4 + claude-4.6-sonnet), sqlglot | `backend/app/chatbot/` (service), `backend/configs/` (agent, schema, tools, workflows) |
| Frontend | React 18, Vite, React Router v6, Zustand, Axios, Tailwind CSS v4 | `frontend/` |

```
.
├── backend/            API FastAPI (+ seed data & tes) + chatbot LangGraph
├── frontend/           SPA React (Vite)
├── docker/             skrip init Postgres lokal (role read-only chatbot, DB test)
├── docker-compose.yaml stack lokal: Postgres + backend + frontend
├── docs/               rancangan delta (kalender, sinkron stok, Manual PO)
└── README.md
```

## Menjalankan dengan Docker (paling cepat untuk user testing)

Prasyarat: Docker + Docker Compose v2.24+.

```bash
cp backend/.env.example backend/.env    # isi AICORE_* agar chatbot aktif (opsional)
docker compose up --build
```

| Layanan | URL | Keterangan |
|:--|:--|:--|
| Frontend | <http://localhost:8080> | nginx; `/api` di-proxy ke backend (SSE tanpa buffering) |
| Backend | <http://localhost:8000/docs> | otomatis di-seed (`--demo-schedules`) saat start pertama |
| Postgres | `localhost:5433` (user/pass `mrp`) | DB `mrp` (aplikasi) & `mrp_test` (pytest); role `mrp_chat_ro` hanya SELECT |
| Supplier worker | — | agent Telegram supplier (`python -m app.supplier_chat.worker`): dispatch percakapan, long polling, pengingat |
| Telegram Lab | <http://localhost:8501> | opsional, `docker compose --profile lab up`: uji agent Telegram (Streamlit) |

- `DATABASE_URL` di `backend/.env` **ditimpa** ke Postgres lokal; hanya kredensial `AICORE_*` yang dipakai dari file itu. Tanpa `AICORE_*`, aplikasi tetap jalan dan chatbot mengembalikan 503.
- Tes backend di dalam container: `docker compose exec backend pytest -q`.
- Reset data: `docker compose down -v` (menghapus volume DB) lalu `up` lagi.

## Otomasi PO & Agent Telegram Supplier

- **Otomasi PO** ([`docs/AUTOMATION.md`](docs/AUTOMATION.md)): dari chat Dashboard, mis. *"Buat PO 50 Ban Luar Karet"* atau *"Hapus PO 12"*. Agent mengklarifikasi sampai permintaan cocok dengan database, menampilkan **kartu konfirmasi**, lalu menjalankan CRUD PO lewat tool (`configs/tools/po_actions.py`) dan menghubungi supplier.
- **Agent Telegram supplier** ([`docs/SUPPLIER_TELEGRAM.md`](docs/SUPPLIER_TELEGRAM.md)): loop latar belakang yang meminta konfirmasi/pembatalan PO ke supplier sampai jelas, lalu memperbarui database. Bila supplier minta **revisi**, manajer menerima opsi via Telegram: batalkan PO, setujui perubahan, atau pesan ke supplier lain. Uji tanpa bot sungguhan dengan `TELEGRAM_MODE=sandbox` + Streamlit **Telegram Lab** (`streamlit run backend/streamlit_app/telegram_lab.py`).

## Chatbot MRP (Dashboard)

> Dokumentasi lengkap (arsitektur, alur, konfigurasi, API): [`docs/CHATBOT.md`](docs/CHATBOT.md).

Agent di halaman Dashboard (menjawab dari data **read-only**; satu-satunya perubahan yang bisa dilakukan adalah PO, selalu setelah konfirmasi) untuk pertanyaan seperti *"ringkas stok tiap item"*, *"item mana yang critical?"*, *"supplier apa saja untuk material Pedal Sepeda?"*. Jawaban di-stream (SSE) beserta langkah progres, skor verifikasi, dan sumber datanya (tool/SQL).

```
rewrite → route ─┬─ smalltalk / di luar topik / ubah data non-PO → respond_direct → finalize
                 ├─ po_automation → parse → resolve ─┬─ kurang jelas → clarify → finalize
                 │                                    └─ jelas → propose → [konfirmasi] → execute → supplier (Telegram)
                 └─ mrp_query → plan → execute_tools → synthesize → evaluate ─┬─ lolos → finalize
                       ▲               (query_database: generate→guard→execute→fix ≤3)       │
                       └──── konteks kurang (≤2x) ◄──┴── revisi dengan kritik (≤2x) ◄─────────┘
```

- **Tool terkurasi** memakai service yang sama dengan UI (stok, item critical, supplier per material, PO terbuka, planning terakhir, BOM, jadwal). **`query_database`** = agent text-to-SQL cadangan dengan retry, hanya boleh `SELECT` (divalidasi `sqlglot`), relasi allowlist, `LIMIT ≤ 200`, transaksi `READ ONLY` + `statement_timeout`.
- **Semantic layer**: view `chat_*_v` (dibuat otomatis setiap `create_all`) menerapkan rumus bisnis (Tersedia, Dipesan, Defisit, status CRITICAL/WARNING/SAFE) agar SQL buatan LLM tidak salah hitung.
- **Tabel jawaban dirender dari baris evidence asli**, bukan dari teks model.
- **Quality gate** (konfigurasi di `backend/configs/models.yaml` → `chatbot.evaluation`): evaluator memakai model berbeda (Claude) dari generator (GPT).

  | Metrik | Cara hitung | Bobot |
  |:--|:--|--:|
  | Faithfulness | judge per klaim: klaim didukung ÷ total klaim | 0.40 |
  | Answer relevance | judge | 0.25 |
  | Numeric grounding | deterministik: setiap angka di teks ada di evidence (nilai, jumlah baris, total kolom) | 0.20 |
  | Completeness | judge: semua bagian pertanyaan terjawab & didukung data | 0.15 |

  Lolos bila skor tertimbang **≥ 0.80** dan faithfulness ≥ 0.70. Bila gagal: ambil data tambahan (konteks kurang) atau revisi jawaban dengan kritik evaluator; setelah batas percobaan, draf terbaik ditampilkan dengan catatan "belum terverifikasi".
- **Kontrak output**: setiap agent punya `configs/agent/<agent>.yaml` (prompt & parameter) dan `configs/schema/<agent>.schema.json` (JSON Schema). Output divalidasi; bila tidak valid, model diminta memperbaiki satu kali.
- **Memori percakapan**: LangGraph `PostgresSaver` (tabel `checkpoint*`), satu `thread_id` per percakapan (tombol *Percakapan baru*).
- **Endpoint**: `POST /api/v1/chat/stream` (SSE: `progress`… lalu `final`/`error`), `POST /api/v1/chat`, `GET /api/v1/chat/{thread_id}/history`, `GET /api/v1/chat/health`.
- **Evaluasi offline** dengan LLM sungguhan: `cd backend && python -m scripts.seed --reset --demo-schedules && python -m scripts.eval_chatbot` (pertanyaan di `tests/chatbot_eval/golden.yaml`).

## Menjalankan tanpa Docker (butuh 2 terminal)

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
cd backend && pytest -q          # BOM, planning, sourcing, PO, goods receipt, kontrak frontend, chatbot (butuh TEST_DATABASE_URL)
cd frontend && npm run build     # build produksi
```

Alur UI di atas juga diuji otomatis (vitest + jsdom + Testing Library) terhadap backend sungguhan; hasilnya 24/24 lolos (termasuk drag-and-drop kalender dengan mock FullCalendar). Tes tersebut tidak disertakan agar frontend tetap minimal.

## Catatan asumsi

- **Roda Set = 1 per sepeda** pada data seed (Ban Luar 2 per set) agar kebutuhan Ban Luar = 100 seperti dokumen alur; BOM di dokumen (Roda Set = 2) akan menghasilkan 200.
- `RM-SBR-01` ditambahkan ke Master; supplier/harga untuk material BUY lain adalah data dummy.
- Tidak ada autentikasi (di luar scope MVP). Pindah ke PostgreSQL: ubah `DATABASE_URL` di `backend/.env` dan `pip install psycopg2-binary`.
- Detail endpoint & aturan bisnis: `backend/README.md`.
