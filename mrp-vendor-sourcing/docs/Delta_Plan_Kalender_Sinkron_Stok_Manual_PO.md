# Delta Plan v1.1 — Kalender Produksi · Sinkronisasi Stok–Jadwal · Manual PO

> **Status:** keputusan pada §6 sudah **final** dan rancangan ini **telah diimplementasikan** (lihat §9). Jenis dokumen: rancangan (delta) terhadap `Backend_Implementation_Plan` (**BP**), `Frontend_Implementation_Plan` (**FP**), dan kode yang sudah dibangun. Belum ada kode fitur yang diimplementasikan.
> **Konvensi:** "BP §2.2" = bagian 2.2 BP; nama file/fungsi mengacu ke kode yang sudah ada (`planning_service.run_planning`, `po_service.ALLOWED_TRANSITIONS`, dst.).
> **Fakta terukur (bukan perkiraan)** hanya ada pada §4.2 (ukuran bundle FullCalendar, diukur dengan `vite build`) dan satu uji render jsdom untuk konfigurasi kalender. Seluruh bagian lain adalah rancangan.

---

## 1. Ringkasan Perubahan dan Analisis Kesenjangan

### 1.1 Keputusan inti

1. **Satu sumber data.** Kalender hanyalah tampilan lain dari tabel `schedules` (toggle di `/mps`). Tidak ada sinkronisasi.
2. **`inventory.allocated` menjadi nilai turunan**: total kebutuhan semua jadwal `PLANNED`, dihitung ulang dari nol oleh `recalc_allocated(db)`. `POST /planning/runs` berhenti menimpanya.
3. **Titik potong stok = "Mulai Produksi".** `on_hand` dan `allocated` turun bersamaan → `available` tidak berubah → rumus MRP tetap konsisten.
4. **Manual PO** memakai tabel PO yang sama (`source = MANUAL`), dengan mesin transisi status per `source`; approval satu tingkat tanpa auth (nama approver sebagai teks).
5. **Dua temuan yang mengubah desain** (di luar brief, §1.4): (a) karena `allocated` menjadi global, status *stale* harus mencakup **semua run DRAFT**, bukan hanya run yang rentangnya memuat tanggal lama/baru; (b) **edit BOM** juga harus memicu `recalc_allocated`.

### 1.2 Analisis kesenjangan

| # | Kebutuhan | Kondisi saat ini | Perubahan |
|:-:|:--|:--|:--|
| A1 | Kalender = tampilan `schedules` | Hanya tabel di `/mps` (FP §3.3) | Toggle `[Tabel \| Kalender]` pada `/mps` (`?view=calendar`); sumber data `GET /schedules` yang sama |
| A2 | Batch, line, status 4 tahap | `schedules`: `product_id, production_date, target_qty, status` (PLANNED/CANCELLED/DONE) | +`batch_code`, `production_line_id`, `started_at`, `completed_at`; tabel `production_lines`; status `PLANNED/IN_PROGRESS/COMPLETED/CANCELLED` (DONE→COMPLETED) |
| A3 | Drag-and-drop, indikator stale | `PATCH /schedules/{id}` boleh mengubah `status`; tidak ada konsep run basi | DnD hanya reschedule tanggal (PLANNED); `planning_runs.is_stale`; PO dari run basi → 409 |
| A3 | Alokasi material per batch | Tidak ada | `GET /schedules/{id}/materials` (memakai `bom_service.explode`) |
| B1 | `allocated` mengikuti jadwal | Ditimpa tiap `POST /planning/runs` (BP §2.2 langkah 3) → hanya cerminan run terakhir | Turunan jadwal PLANNED (`recalc_allocated`); run hanya membaca |
| B2 | Dampak status ke stok | `on_hand` hanya berubah lewat Goods Receipt & `ADJUSTMENT` | +`PRODUCTION_ISSUE` saat Mulai Produksi; 409 bila `on_hand` kurang |
| C1 | PO tanpa planning run | Semua PO lahir dari run (`planning_run_id` nullable tapi selalu terisi) | `purchase_orders.source`; `POST /purchase-orders` |
| C2 | Header & item Manual PO | Tidak ada TOP, tanggal PO, catatan, tanggal kebutuhan | +`suppliers.payment_term_days`; +`po_date`, `notes`; +`po_items.needed_by_date` |
| C3 | Approval | Hanya `DRAFT → ISSUED → …` | +`PENDING_APPROVAL`, `APPROVED`, `REJECTED`; mesin transisi per `source` |
| C3 | `on_order` | Semua PO `DRAFT/ISSUED/PARTIALLY_RECEIVED` (`OPEN_PO`) | Per `source` (manual DRAFT tidak dihitung) |

### 1.3 Bagian plan/kode lama yang diganti atau direvisi

| Dokumen / kode | Isi lama | Pengganti |
|:--|:--|:--|
| **BP §2.2 langkah 3** (`planning_service.run_planning`) | Reset `allocated = 0` lalu set `allocated = gross` | **Dihapus.** Run membaca `inv.allocated` (turunan jadwal PLANNED) |
| BP §2.2 langkah 5 (`OPEN_PO`, `_on_order_map`) | Satu daftar status untuk semua PO | `COUNTED[source]` (§3.4-e) |
| BP §1.1 (enum) | `ScheduleStatus` {PLANNED, CANCELLED, DONE}; `POStatus` 6 nilai; `MovementType` {GOODS_RECEIPT, ADJUSTMENT} | Enum diperluas; `POSource` baru |
| BP §1.2 (tabel) | `schedules`, `suppliers`, `planning_runs`, `purchase_orders`, `po_items` | Kolom baru + tabel `production_lines` (§3.1) |
| BP §2.4 / `po_service.ALLOWED_TRANSITIONS` | `{DRAFT: {ISSUED, CANCELLED}, ISSUED: {CANCELLED}}` | `TRANSITIONS[(source, status)]` (§3.4-e) |
| **BP §3.3** `PATCH /schedules/{id}` | Body memuat `status?` | `status` **dihapus** dari body; pindah ke `PATCH /schedules/{id}/status`; `DELETE` menjadi alias pembatalan |
| BP §3.3 `POST /schedules` | 422 bila produk bukan MAKE | Juga 422 bila BOM tidak lengkap/siklus |
| BP §3.4–3.5 `GET /purchase-orders` | Filter `status`, `supplier_id`, `planning_run_id` | +`source`; +endpoint Manual PO (§3.5) |
| BP §3.8 `core/exceptions.py` | `AppError(status, detail)` | +`extra` agar 409 memuat daftar material kurang |
| FP §3.3 (`/mps`) | Tabel jadwal saja | Toggle tabel/kalender, banner stale, side-panel |
| FP §3.5 (`PoGeneratePanel`) | Selalu bisa konfirmasi | Diblok bila `run.is_stale` |
| FP §3.6 (`PoHeader`) | Tombol Terbitkan/Batalkan | Workflow bar approval |
| FP §2.3 (`api.js`) | Interceptor membuang body error selain `detail` | Meneruskan `data` (untuk `shortages`) |

### 1.4 Temuan tambahan (tidak ada di brief)

| ID | Temuan | Dampak pada desain |
|:-:|:--|:--|
| T1 | `allocated` global ⇒ perubahan jadwal **di luar** rentang run tetap mengubah `available` run tersebut | Stale = **semua run DRAFT** pada setiap mutasi jadwal (superset dari aturan di brief) |
| T2 | `allocated` juga bergantung pada BOM. UI BOM membuat sub-part kosong dulu baru mengisi komponennya | Hook `recalc_allocated(strict=False)` pada mutasi BOM; **tidak boleh memblokir** (kalau strict, "Buat sub-part" gagal di langkah antara) |
| T3 | Risiko **pesan ganda**: run DRAFT dibuat → Manual PO di-submit → PO planning digenerate dari run lama | `mark_runs_stale` juga dipicu saat set "PO terhitung" berubah (submit/reject/cancel) dan saat `PUT /inventory`; PO dari run basi ditolak 409 |
| T4 | `@fullcalendar/react@latest` = **7.x** dan butuh core 7, sedangkan plugin `latest` masih **6.1.21** | Pin semua paket FullCalendar ke **6.1.21** (terverifikasi dapat dibuild & dirender) |
| T5 | `schedules` hanya punya **tanggal** (tanpa jam) | `timeGrid` tidak berguna; cukup `dayGrid` untuk Harian/Mingguan/Bulanan (hemat ±9 KB gzip, terukur) |
| T6 | Tes lama membuat `Schedule` lewat ORM lalu mengandalkan `run_planning` mengisi `allocated` (`test_planning_service`, `test_sourcing_service`, `seed --demo-schedules`) | Fixture/seed wajib memanggil `recalc_allocated` (atau membuat jadwal lewat service) |
| T7 | `MovementType.PRODUCTION_ISSUE` = 16 karakter = batas `Enum(length=16)` pada `stock_movements.type`; `PENDING_APPROVAL` = 16 ≤ 20 | Muat tanpa ubah panjang; enum non-native tanpa CHECK ⇒ nilai baru **tanpa DDL** |
| T8 | SQLite tidak mendukung `ADD COLUMN … NOT NULL` tanpa default maupun `UNIQUE` | Skrip migrasi dengan pola sama seperti `migrate_item_categories` (§3.3) |

---

## 2. User Stories dan Acceptance Criteria

### A. Kalender Produksi

| ID | Cerita & kriteria |
|:-:|:--|
| **A-1** | *Sebagai perencana, saya ingin melihat jadwal di kalender Harian/Mingguan/Bulanan.* **Given** jadwal ada di tabel `schedules`, **When** saya membuka `/mps?view=calendar`, **Then** setiap jadwal tampil di tanggalnya dengan kode batch, produk, qty, line, dan warna status; jadwal `CANCELLED` tersembunyi kecuali toggle "Tampilkan dibatalkan" aktif (tampil redup). |
| **A-2** | *Jadwal baru dari tabel otomatis muncul.* **Given** saya menambah jadwal di modal, **When** modal tersimpan, **Then** tabel **dan** kalender menampilkannya tanpa langkah sinkronisasi; `batch_code` terisi otomatis `BATCH-YYYYMMDD-NNN`. |
| **A-3** | *Reschedule dengan drag.* **Given** event berstatus PLANNED, **When** saya menyeretnya ke tanggal lain, **Then** `PATCH /schedules/{id} {production_date}` terkirim dan event pindah; **Given** event IN_PROGRESS/COMPLETED/CANCELLED, **Then** tidak bisa diseret; **Given** backend menolak, **Then** event kembali ke posisi semula dan toast menampilkan pesan. |
| **A-4** | *Indikator run basi.* **Given** ada planning run DRAFT, **When** jadwal dibuat/diubah/dipindah/dibatalkan, **Then** semua run DRAFT ditandai `is_stale`; kalender menampilkan banner dengan tombol **Jalankan Ulang**, dan event pada rentang run basi diberi tanda ⚠; pembuatan PO dari run basi ditolak 409. Planning **tidak** dihitung ulang otomatis. |
| **A-5** | *Side-panel batch.* **Given** saya mengklik event, **Then** panel menampilkan info batch, aksi status yang valid saja, tombol Edit (hanya PLANNED), dan tabel alokasi material (SKU, nama, kebutuhan batch, satuan, stok fisik, stok tersedia, badge CRITICAL/WARNING/SAFE) dengan keterangan bahwa status stok **global per material**. |
| **A-6** | *Transisi status.* **Given** PLANNED, **Then** tersedia "Mulai Produksi" dan "Batalkan"; **Given** IN_PROGRESS, **Then** hanya "Selesaikan"; transisi lain ditolak 409. Kalender tidak mengubah status lewat drag. |

### B. Sinkronisasi Stok Inventory ↔ Status Jadwal

| ID | Cerita & kriteria |
|:-:|:--|
| **B-1** | **Given** stok seed, **When** saya membuat jadwal 30 lalu 20 unit, **Then** *Terkunci* Ban = 100, Pedal = 100, Besi = 75 kg, Rangka Jok = 50 (otomatis, tanpa menjalankan planning). |
| **B-2** | **Given** batch PLANNED dan `on_hand` ≥ kebutuhan semua material, **When** "Mulai Produksi" dikonfirmasi, **Then** dalam satu transaksi: status → IN_PROGRESS, `started_at` terisi, `on_hand` turun sebesar kebutuhan, `allocated` turun sebesar kebutuhan (maka `available` tetap), dan tercatat satu `PRODUCTION_ISSUE` per material (`ref_type=SCHEDULE`). |
| **B-3** | **Given** `on_hand` salah satu material < kebutuhan, **When** "Mulai Produksi", **Then** 409 berisi daftar `{sku, required, on_hand, short_by}` dan **tidak ada** perubahan data (status, stok, movement). |
| **B-4** | **Given** batch PLANNED, **When** dibatalkan, **Then** *Terkunci* turun sebesar kebutuhan batch, `on_hand` tidak berubah, tanpa movement. |
| **B-5** | **When** jadwal dibuat/diubah dengan produk yang BOM-nya tidak lengkap atau berisi siklus, **Then** 422 dan tidak ada yang tersimpan. |
| **B-6** | **Given** semua jadwal PLANNED = Senin 30 + Selasa 20, **When** planning run Senin–Selasa dijalankan, **Then** hasil identik dengan Phase 2 dokumen alur: Ban −20, Rangka 0, Besi 25, Pedal 20; run tidak mengubah `allocated`. |
| **B-7** | **When** BOM produk yang punya jadwal PLANNED diubah, **Then** *Terkunci* dihitung ulang; perubahan BOM tidak ditolak walau sementara tidak lengkap. |
| **B-8** | **When** `PUT /inventory/{id}` dipanggil, **Then** `allocated` tidak berubah. |

### C. Manual PO

| ID | Cerita & kriteria |
|:-:|:--|
| **C-1** | *Pembelian membuat PO langsung.* **When** saya mengisi supplier, tanggal PO, catatan, dan ≥1 item dari master material, **Then** PO berstatus DRAFT, `source=MANUAL`, `planning_run_id=NULL`, berlabel "Manual PO" di daftar dan detail. |
| **C-2** | *Validasi.* Qty > 0; harga ≥ 0; tanggal kebutuhan ≥ tanggal PO; material tidak boleh duplikat; supplier tak terhubung ke material → **peringatan** (bukan blokir); material harus dari master (BUY, aktif) dan supplier aktif. |
| **C-3** | *Approval.* **Given** DRAFT/REJECTED, **When** Submit, **Then** PENDING_APPROVAL; **When** Approve (nama approver) → APPROVED (`decided_by/at` terisi); **When** Reject (alasan wajib) → REJECTED dan PO dapat diedit lalu disubmit ulang. |
| **C-4** | *Terbit & terima.* **Given** APPROVED, **When** Terbitkan → ISSUED; Goods Receipt hanya untuk ISSUED/PARTIALLY_RECEIVED; stok bertambah dan `on_order` turun. |
| **C-5** | *`on_order`.* Manual PO dihitung pada PENDING_APPROVAL/APPROVED/ISSUED/PARTIALLY_RECEIVED — tidak pada DRAFT, REJECTED, CANCELLED. |
| **C-6** | *Tidak ada regresi.* PO hasil planning tetap `DRAFT → ISSUED` tanpa approval dan dihitung seperti sebelumnya. |

---

## 3. Delta Backend

### 3.1 Perubahan skema

| Tabel | Perubahan | Tipe / constraint |
|:--|:--|:--|
| **`production_lines`** *(baru)* | `id`, `code`, `name`, `is_active` | `code` UNIQUE; seed `LINE-01`, `LINE-02` |
| **`schedules`** | `batch_code` | `String(24)` UNIQUE NOT NULL — `BATCH-YYYYMMDD-NNN`, **immutable** |
| | `production_line_id` | FK → `production_lines`, NOT NULL |
| | `started_at`, `completed_at` | `DateTime` NULL (UTC naif, sama seperti `created_at`) |
| | `status` | Enum: `PLANNED, IN_PROGRESS, COMPLETED, CANCELLED` (migrasi `DONE → COMPLETED`) |
| **`planning_runs`** | `is_stale` | `Boolean` NOT NULL default `false` |
| **`suppliers`** | `payment_term_days` | `Integer` NOT NULL default 0, CHECK ≥ 0 |
| **`purchase_orders`** | `source` | Enum `MANUAL \| PLANNING`, NOT NULL, default `PLANNING` |
| | `po_date` | `Date` NOT NULL (backfill = `date(created_at)`) |
| | `notes` | `String(500)` NULL |
| | `submitted_at`, `decided_at` | `DateTime` NULL |
| | `decided_by` | `String(80)` NULL — setara `approved_by`; dinamai `decided_*` karena juga mencatat penolakan |
| | `rejection_reason` | `String(300)` NULL |
| | `status` | Enum + `PENDING_APPROVAL`, `APPROVED`, `REJECTED` |
| **`po_items`** | `needed_by_date` | `Date` NULL |
| **`stock_movements`** | `type` | Enum + `PRODUCTION_ISSUE` |
| `inventory` | *(tanpa perubahan skema)* | Semantik `allocated` berubah: **turunan**, bukan input |

Total: **+1 tabel**, **+14 kolom** (schedules 4, planning_runs 1, suppliers 1, purchase_orders 7, po_items 1), **3 enum diperluas** (`ScheduleStatus`, `POStatus`, `MovementType`), 1 enum baru (`POSource`).

### 3.2 Model SQLAlchemy (potongan)

```python
# app/models/enums.py
class ScheduleStatus(str, enum.Enum):
    PLANNED = "PLANNED"; IN_PROGRESS = "IN_PROGRESS"; COMPLETED = "COMPLETED"; CANCELLED = "CANCELLED"

class POStatus(str, enum.Enum):
    DRAFT = "DRAFT"; PENDING_APPROVAL = "PENDING_APPROVAL"; APPROVED = "APPROVED"; REJECTED = "REJECTED"
    ISSUED = "ISSUED"; PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"; RECEIVED = "RECEIVED"; CANCELLED = "CANCELLED"

class POSource(str, enum.Enum):
    MANUAL = "MANUAL"; PLANNING = "PLANNING"

class MovementType(str, enum.Enum):
    GOODS_RECEIPT = "GOODS_RECEIPT"; ADJUSTMENT = "ADJUSTMENT"; PRODUCTION_ISSUE = "PRODUCTION_ISSUE"
```

```python
# app/models/production_line.py  (baru)
class ProductionLine(Base):
    __tablename__ = "production_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

# app/models/schedule.py  (tambahan)
_NEXT = {ScheduleStatus.PLANNED: [ScheduleStatus.IN_PROGRESS, ScheduleStatus.CANCELLED],
         ScheduleStatus.IN_PROGRESS: [ScheduleStatus.COMPLETED]}

class Schedule(Base):
    ...
    batch_code: Mapped[str] = mapped_column(String(24), unique=True)
    production_line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    line: Mapped["ProductionLine"] = relationship()

    @property
    def allowed_transitions(self) -> list[ScheduleStatus]:   # dipakai UI agar aturan tidak diduplikasi
        return _NEXT.get(self.status, [])
    @property
    def editable(self) -> bool:
        return self.status == ScheduleStatus.PLANNED
    @property
    def line_code(self): return self.line.code
    @property
    def line_name(self): return self.line.name

# app/models/purchase_order.py  (tambahan)
class PurchaseOrder(Base):
    ...
    source: Mapped[POSource] = mapped_column(Enum(POSource, native_enum=False, length=10), default=POSource.PLANNING)
    po_date: Mapped[date] = mapped_column(Date, default=date.today)
    notes: Mapped[str | None] = mapped_column(String(500), default=None)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    decided_by: Mapped[str | None] = mapped_column(String(80), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    rejection_reason: Mapped[str | None] = mapped_column(String(300), default=None)
    @property
    def payment_term_days(self) -> int: return self.supplier.payment_term_days
# po_items: needed_by_date: Mapped[date | None] = mapped_column(Date, default=None)
```

### 3.3 Migrasi database lama (`scripts/migrate_mps_manual_po.py`)

`create_all` tidak mengubah tabel yang sudah ada (T8), maka skrip SQLite berpola sama dengan `migrate_item_categories` — backup `.bak`, satu transaksi, idempoten:

1. `Base.metadata.create_all(engine)` → membuat `production_lines`; seed `LINE-01`, `LINE-02`.
2. `ALTER TABLE ADD COLUMN` semua kolom §3.1 (kolom NOT NULL ditambah **nullable** di DB lama; ORM tetap `nullable=False` untuk DB baru — aman).
3. Backfill: `schedules.production_line_id = LINE-01`; `batch_code` untuk jadwal lama, diurutkan `id`, per tanggal produksi (`BATCH-YYYYMMDD-NNN`); `status 'DONE' → 'COMPLETED'`; `purchase_orders.source='PLANNING'`, `po_date = date(created_at)`; `planning_runs.is_stale = 0`; `suppliers.payment_term_days = 0`.
4. `CREATE UNIQUE INDEX uq_schedules_batch_code ON schedules(batch_code)` (setelah backfill).
5. Panggil `recalc_allocated(db)` **sekali** agar `inventory.allocated` konsisten dengan jadwal PLANNED yang ada.

> Karena skema kini berubah dua kali berturut-turut, BP §7 ("tambah Alembic sebelum data produksi") menjadi relevan; skrip di atas tetap cukup selama datanya masih data uji.

### 3.4 Perubahan service

#### (a) `app/core/exceptions.py` & handler — `extra`

```python
class AppError(Exception):
    def __init__(self, status_code: int, detail: str, extra: dict | None = None):
        super().__init__(detail)
        self.status_code, self.detail, self.extra = status_code, detail, extra or {}

# main.py
return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, **exc.extra})
```

#### (b) `allocation_service.py` *(baru)* — `recalc_allocated`

```python
def requirement(db, product_id: int, qty: float, graph=None) -> dict[int, float]:
    """Kebutuhan material BUY untuk `qty` unit. BOM tak lengkap ATAU siklus -> 422 (keputusan B1)."""
    try:
        per_unit = bom_service.explode(db, product_id, 1, graph)
    except AppError as e:
        raise AppError(422, e.detail) if e.status_code == 409 else e
    return {m: round(q * qty, 6) for m, q in per_unit.items()}


def recalc_allocated(db, strict: bool = True) -> bool:
    """allocated := Σ kebutuhan SEMUA jadwal PLANNED. Selalu dari nol (tanpa delta). Tidak commit.
    strict=False dipakai jalur edit BOM (T2): produk dengan BOM sementara tak lengkap dihitung 0.
    Return True bila ada nilai allocated yang berubah."""
    graph = bom_service._load_graph(db)
    per_unit, total = {}, defaultdict(float)
    for s in db.scalars(select(Schedule).where(Schedule.status == ScheduleStatus.PLANNED)):
        if s.product_id not in per_unit:                       # cache eksplosi 1 unit per produk
            try:
                per_unit[s.product_id] = bom_service.explode(db, s.product_id, 1, graph)
            except AppError:
                if strict:
                    raise
                per_unit[s.product_id] = {}
        for mid, q in per_unit[s.product_id].items():
            total[mid] += q * s.target_qty

    invs = {i.material_id: i for i in db.scalars(
        select(Inventory).execution_options(populate_existing=True))}
    before = {m: i.allocated for m, i in invs.items()}
    for i in invs.values():                                    # dari nol, bukan delta
        i.allocated = 0.0
    for mid, g in total.items():
        inv = invs.get(mid) or inventory_service.get_or_create_inventory(db, mid)
        inv.allocated = round(g, 6)
    db.flush()
    return any(abs(before.get(m, 0.0) - round(total.get(m, 0.0), 6)) > 1e-9 for m in {*before, *total})
```

Hook mutasi BOM (T2) — dipanggil di akhir `add_item/update_item/delete_item/replace_items/add_sub_part`, sebelum `commit`:

```python
def _after_change(db):                       # bom_service.py — import lokal menghindari siklus impor
    from app.services import allocation_service, planning_service
    if allocation_service.recalc_allocated(db, strict=False):
        planning_service.mark_runs_stale(db)
```

#### (c) `schedule_service.py` *(baru)* — jadwal, nomor batch, transisi

```python
_NEXT = {PLANNED: {IN_PROGRESS, CANCELLED}, IN_PROGRESS: {COMPLETED}}   # sumber tunggal (sama dgn model)

def next_batch_code(db, d: date) -> str:
    """BATCH-YYYYMMDD-NNN; tanggal = production_date SAAT DIBUAT, tidak berubah saat drag (kode = identitas)."""
    prefix = f"BATCH-{d:%Y%m%d}-"
    n = db.scalar(select(func.count()).select_from(Schedule)
                  .where(Schedule.batch_code.like(f"{prefix}%"))) or 0     # tidak ada DELETE -> count aman
    return f"{prefix}{n + 1:03d}"                                          # UNIQUE menangkap race; retry 1x


def create_schedule(db, product_id, production_date, target_qty, line_id=None) -> Schedule:
    product = _finished_product(db, product_id)                  # 404 / 422 bukan FINISHED
    allocation_service.requirement(db, product_id, target_qty)   # validasi BOM -> 422, SEBELUM ada mutasi
    line = _line(db, line_id)                                    # default: line aktif pertama; 422 bila nonaktif
    s = Schedule(product_id=product.id, production_date=production_date, target_qty=target_qty,
                 production_line_id=line.id, batch_code=next_batch_code(db, production_date))
    db.add(s); db.flush()
    allocation_service.recalc_allocated(db)                      # semua dalam SATU transaksi
    planning_service.mark_runs_stale(db)
    db.commit(); db.refresh(s)
    return s


def update_schedule(db, s: Schedule, data: dict) -> Schedule:             # production_date, target_qty, product_id, production_line_id
    if s.status != ScheduleStatus.PLANNED:
        raise AppError(409, f"Jadwal berstatus {s.status.value} tidak dapat diubah")
    ...                                                           # validasi produk/BOM/line bila berubah (422)
    db.flush(); allocation_service.recalc_allocated(db); planning_service.mark_runs_stale(db)
    db.commit(); db.refresh(s)
    return s


def change_status(db, s: Schedule, new: ScheduleStatus) -> Schedule:
    if new not in _NEXT.get(s.status, set()):
        raise AppError(409, f"Transisi {s.status.value} → {new.value} tidak valid")
    if new == ScheduleStatus.IN_PROGRESS:
        _issue_materials(db, s)                                   # validasi SEMUA material dulu, baru mutasi
        s.started_at = _now()
    elif new == ScheduleStatus.COMPLETED:
        s.completed_at = _now()                                   # tanpa efek stok
    s.status = new
    db.flush()
    if new in (ScheduleStatus.IN_PROGRESS, ScheduleStatus.CANCELLED):
        allocation_service.recalc_allocated(db)                   # s keluar dari himpunan PLANNED
    if new == ScheduleStatus.CANCELLED:
        planning_service.mark_runs_stale(db)                      # start TIDAK stale: available & on_order tetap
    db.commit(); db.refresh(s)
    return s


def _issue_materials(db, s) -> None:
    need = allocation_service.requirement(db, s.product_id, s.target_qty)
    mats = {m.id: m for m in db.scalars(select(Material).where(Material.id.in_(need)))}
    invs = {i.material_id: i for i in db.scalars(select(Inventory).where(Inventory.material_id.in_(need)))}
    on_hand = lambda m: invs[m].on_hand if m in invs else 0.0          # tanpa baris inventory = stok 0
    short = [{"material_id": m, "sku": mats[m].sku, "name": mats[m].name, "uom": mats[m].uom,
              "required": q, "on_hand": on_hand(m), "short_by": round(q - on_hand(m), 6)}
             for m, q in need.items() if on_hand(m) + 1e-9 < q]
    if short:
        raise AppError(409, "Stok fisik tidak cukup untuk memulai produksi", extra={"shortages": short})
    for m, q in need.items():                                         # semua cukup -> baru mutasi
        invs[m].on_hand -= q
        db.add(StockMovement(material_id=m, type=MovementType.PRODUCTION_ISSUE, qty=-q,
                             ref_type="SCHEDULE", ref_id=s.id, note=s.batch_code))
```

**Mengapa `available` tetap saat Mulai Produksi:** sebelum `available = on_hand − allocated`; sesudah `(on_hand − q) − (allocated − q)` = nilai yang sama. Stok yang tadinya "dicadangkan" untuk batch ini berpindah menjadi "keluar gudang". Jadwal PLANNED lain tetap mencadangkan bagiannya, sehingga bila `on_hand` sisa tak cukup untuk mereka, `available` negatif muncul sebagai CRITICAL — itu perilaku MRP yang benar.

#### (d) `planning_service.py` — selisih terhadap BP §2.2

```diff
- db.execute(update(Inventory).values(allocated=0))          # BP §2.2 langkah 3 — DIHAPUS
  invs = {i.material_id: i for i in db.scalars(select(Inventory)...)}
  ...
  for mid, g in gross.items():
      inv = invs.get(mid) ...
-     inv.allocated = g                                       # DIHAPUS
-     available = round(inv.on_hand - inv.allocated, 6)
+     available = round(inv.on_hand - inv.allocated, 6)       # allocated = turunan jadwal PLANNED (global)
      run.lines.append(PlanningLine(
-         ..., allocated=g, ...
+         ..., allocated=inv.allocated, ...                   # snapshot nilai global
          on_order=incoming, shortfall=max(0, safety − (available + incoming)), ...))

+ def mark_runs_stale(db):
+     db.execute(update(PlanningRun).where(PlanningRun.status == PlanningRunStatus.DRAFT).values(is_stale=True))
```

`gross_requirement` tetap per-rentang tanggal run (hanya jadwal PLANNED dalam rentang); rumus `available` dan `shortfall` **tidak berubah**.

**Konsekuensi `allocated` global:**
1. Kolom *Kebutuhan* (rentang run) bisa lebih kecil dari *Terkunci* (semua jadwal PLANNED, termasuk di luar rentang). UI diberi tooltip "Terkunci = semua jadwal PLANNED".
2. Material yang hanya dibutuhkan jadwal di luar rentang **tidak muncul** pada run itu (baris run tetap berasal dari `gross` rentang), walau `available`-nya sudah negatif.
3. **Angka contoh Phase 2 tidak berubah**, karena seluruh jadwal PLANNED = Senin 30 + Selasa 20 = rentang run: Ban 100/−20, Rangka 50/0, Besi 75/25, Pedal 100/20.

#### (e) `po_service.py` — mesin transisi dan `on_order`

```python
S, SRC = POStatus, POSource
TRANSITIONS: dict[tuple[POSource, POStatus], set[POStatus]] = {
    (SRC.MANUAL,   S.DRAFT):             {S.PENDING_APPROVAL, S.CANCELLED},
    (SRC.MANUAL,   S.PENDING_APPROVAL):  {S.APPROVED, S.REJECTED, S.CANCELLED},
    (SRC.MANUAL,   S.APPROVED):          {S.ISSUED, S.CANCELLED},
    (SRC.MANUAL,   S.REJECTED):          {S.PENDING_APPROVAL, S.CANCELLED},      # edit lalu submit ulang
    (SRC.MANUAL,   S.ISSUED):            {S.CANCELLED},
    (SRC.PLANNING, S.DRAFT):             {S.ISSUED, S.CANCELLED},                # alur lama, tanpa approval
    (SRC.PLANNING, S.ISSUED):            {S.CANCELLED},
}   # ISSUED → PARTIALLY_RECEIVED → RECEIVED hanya lewat Goods Receipt (kedua source)

COUNTED = {   # status yang dihitung sebagai on_order
    SRC.PLANNING: (S.DRAFT, S.ISSUED, S.PARTIALLY_RECEIVED),
    SRC.MANUAL:   (S.PENDING_APPROVAL, S.APPROVED, S.ISSUED, S.PARTIALLY_RECEIVED),
}

def transition(db, po, new):
    if new not in TRANSITIONS.get((po.source, po.status), set()):
        raise AppError(409, f"Transisi {po.status.value} → {new.value} tidak valid untuk PO {po.source.value}")
    before = po.status in COUNTED[po.source]
    po.status = new
    if (po.status in COUNTED[po.source]) != before:       # on_order berubah -> run DRAFT basi (T3)
        planning_service.mark_runs_stale(db)

# planning_service._on_order_map — menggantikan OPEN_PO
cond = or_(*[and_(PurchaseOrder.source == src, PurchaseOrder.status.in_(sts)) for src, sts in COUNTED.items()])
rows = db.execute(select(POItem.material_id, POItem.qty_ordered - POItem.qty_received)
                  .select_from(POItem).join(PurchaseOrder, POItem.po_id == PurchaseOrder.id).where(cond))
```

Fungsi turunan: `create_manual`, `update_manual` (replace-all item), `submit`, `approve`, `reject` — masing-masing memanggil `transition(...)` lalu mengisi kolom approval dan `commit` sekali. `PATCH /status` tetap menangani `ISSUED` & `CANCELLED` (jadi `APPROVED → ISSUED` tanpa endpoint baru). Validasi `create/update_manual`: supplier ada & aktif (404/422); setiap material ada, kategori `PURCHASED`, aktif (404/422); tidak ada duplikat; `needed_by_date ≥ po_date`; peringatan (bukan error) bila tidak ada relasi aktif material–supplier → dikembalikan sebagai `warnings[]`.

**Dampak `on_order` agar tidak terjadi pemesanan ganda**
- Manual PO **DRAFT tidak dihitung**: masih coretan, menghitungnya dapat menyembunyikan defisit nyata. **PENDING_APPROVAL dihitung**: pembeli sudah berkomitmen, mencegah planning memesan hal yang sama.
- **REJECTED/CANCELLED** keluar dari hitungan → defisit muncul kembali; karena set terhitung berubah, run DRAFT ditandai basi dan harus dijalankan ulang.
- Risiko tersisa: PO planning dan Manual PO untuk kebutuhan yang sama dibuat berdekatan. Mitigasi: kolom `on_order` pada `GET /inventory`, hint "Tersedia · Dipesan · Safety" pada form Manual PO, dan PO dari run basi diblok 409. Qty di atas defisit **tidak** diblok (pembelian untuk stok pengaman/antisipasi sah).
- Penerimaan barang **netral** terhadap shortfall (`on_hand ↑ q`, `on_order ↓ q`), demikian pula Mulai Produksi — keduanya tidak menandai stale.

#### (f) `inventory_service.py`

- `to_out` ditambah `on_order` (dari `_on_order_map`, dihitung sekali per request).
- `update_inventory`: `allocated` **tidak** dapat diubah (skema `InventoryUpdate` sudah tidak memuatnya; ditegaskan dengan tes B-8) dan memanggil `mark_runs_stale` bila `on_hand`/`safety_stock` berubah (T3).

### 3.5 Endpoint baru / berubah (prefix `/api/v1`)

#### Jadwal produksi

| Method | Path | Body | Response | Error |
|:--|:--|:--|:--|:--|
| POST | `/schedules` | `{product_id, production_date, target_qty, production_line_id?}` | `201` `ScheduleOut` | `404` produk · `422` bukan FINISHED / **BOM tidak lengkap atau siklus** / line nonaktif / validasi |
| GET | `/schedules` | query: `date_from`, `date_to`, `status`, `production_line_id` | `200` `ScheduleOut[]` | – |
| PATCH | `/schedules/{id}` | `{production_date?, target_qty?, product_id?, production_line_id?}` *(tanpa `status`)* | `200` `ScheduleOut` | `404` · `409` bukan PLANNED · `422` |
| PATCH | `/schedules/{id}/status` | `{status: "IN_PROGRESS" \| "COMPLETED" \| "CANCELLED"}` | `200` `ScheduleOut` | `404` · **`409` transisi tidak valid** · **`409` stok kurang** (`{detail, shortages[]}`) · `422` status tak dikenal / BOM tak lengkap |
| DELETE | `/schedules/{id}` | – | `204` — alias `→ CANCELLED` (*deprecated*) | `404` · `409` bukan PLANNED |
| GET | `/schedules/{id}/materials` | – | `200` `ScheduleMaterialsOut` | `404` · `422` BOM tak lengkap |
| GET | `/production-lines` | query: `is_active` | `200` `[{id, code, name, is_active}]` | – |

`ScheduleOut`: `id, batch_code, product_id, product_sku, product_name, production_line_id, line_code, line_name, production_date, target_qty, status, started_at, completed_at, editable, allowed_transitions[]`.

> **`GET /schedules` diperluas, bukan `/schedules/calendar`.** Field yang dibutuhkan kalender sudah tercakup, filter `date_from/date_to` sudah ada, dan datanya kecil. Kalender memuat semua jadwal sekali (sama dengan tabel); bila volume melewati ±500 baris, panggil dengan rentang dari `datesSet` FullCalendar. FullCalendar memberi `end` eksklusif → kirim `end − 1 hari`.

`ScheduleMaterialsOut` — `basis: "CURRENT_BOM"`, `scope: "GLOBAL_STOCK_STATUS"`, `can_start: bool`, dan `lines[]`:

```json
{ "material_id": 7, "sku": "RM-RUB-01", "name": "Ban Luar Karet", "uom": "Buah",
  "required_qty": 60, "on_hand": 80, "allocated": 100, "available": -20, "safety_stock": 40,
  "on_hand_after": 20,           // on_hand − required; null bila status bukan PLANNED
  "enough": true,                // on_hand >= required
  "status": "CRITICAL" }         // status GLOBAL material (available vs safety) — BUKAN status per batch
```

Dihitung langsung dengan `allocation_service.requirement(...)`, sehingga untuk batch yang sudah berjalan angka mengikuti BOM saat ini (batasan diterima; realisasi aktual tersimpan pada `stock_movements` `PRODUCTION_ISSUE`). Endpoint yang sama dipakai dialog "Mulai Produksi" untuk pratinjau dampak stok (tanpa endpoint preview tambahan).

#### Planning, inventory

| Method | Path | Perubahan |
|:--|:--|:--|
| POST | `/planning/runs` | Tidak lagi menulis `allocated`; `run.is_stale = false` |
| GET | `/planning/runs`, `/planning/runs/{id}` | +`is_stale` |
| POST | `/planning/runs/{id}/purchase-orders` | **`409`** bila `is_stale` ("Run basi — jalankan ulang planning") |
| GET | `/inventory` | +`on_order` |
| GET | `/stock-movements` | sudah ada; tipe baru `PRODUCTION_ISSUE` |

#### Manual PO

| Method | Path | Body | Response | Error |
|:--|:--|:--|:--|:--|
| POST | `/purchase-orders` | `{supplier_id, po_date?, notes?, items:[{material_id, qty_ordered, unit_price, needed_by_date?}]}` | `201` `PurchaseOrderOut` (`source=MANUAL`, DRAFT, `warnings[]`) | `404` supplier/material · `422` qty ≤ 0, harga < 0, duplikat, tanggal kebutuhan < tanggal PO, material bukan PURCHASED, supplier nonaktif, item kosong |
| PATCH | `/purchase-orders/{id}` | field POST (semua opsional; `items` = replace-all) | `200` | `404` · `409` bukan MANUAL / bukan DRAFT-REJECTED · `422` |
| POST | `/purchase-orders/{id}/submit` | – | `200` → `PENDING_APPROVAL` | `409` bukan MANUAL / status salah · `422` item kosong |
| POST | `/purchase-orders/{id}/approve` | `{approved_by: str(2–80)}` | `200` → `APPROVED` | `409` bukan PENDING_APPROVAL · `422` |
| POST | `/purchase-orders/{id}/reject` | `{rejected_by: str(2–80), reason: str(3–300)}` | `200` → `REJECTED` | `409` · `422` |
| PATCH | `/purchase-orders/{id}/status` | `{status: "ISSUED" \| "CANCELLED"}` *(sudah ada)* | `200` | `409` transisi per `(source,status)` |
| POST | `/purchase-orders/{id}/receipts` | *(tidak berubah)* | `200` | `409` bukan ISSUED/PARTIALLY_RECEIVED |
| GET | `/purchase-orders` | query: `source`, `status`, `supplier_id`, `planning_run_id` | `200` | – |

`PurchaseOrderOut` +`source, po_date, notes, payment_term_days, submitted_at, decided_by, decided_at, rejection_reason, warnings[]`; `POItemOut` +`needed_by_date`.
`SupplierCreate/Update/Out` +`payment_term_days` (int ≥ 0).

**Tabel transisi PO**

| Dari | Ke | Pemicu | Source | `on_order` berubah? |
|:--|:--|:--|:-:|:-:|
| DRAFT | PENDING_APPROVAL | `POST /submit` | MANUAL | ya (+) → stale |
| DRAFT | ISSUED | `PATCH /status` | PLANNING | – |
| DRAFT | CANCELLED | `PATCH /status` | keduanya | – (MANUAL) / ya (PLANNING) |
| PENDING_APPROVAL | APPROVED | `POST /approve` | MANUAL | – |
| PENDING_APPROVAL | REJECTED | `POST /reject` | MANUAL | ya (−) → stale |
| PENDING_APPROVAL | CANCELLED | `PATCH /status` | MANUAL | ya (−) → stale |
| APPROVED | ISSUED | `PATCH /status` | MANUAL | – |
| APPROVED | CANCELLED | `PATCH /status` | MANUAL | ya (−) → stale |
| REJECTED | PENDING_APPROVAL | `POST /submit` (setelah edit) | MANUAL | ya (+) → stale |
| REJECTED | CANCELLED | `PATCH /status` | MANUAL | – |
| ISSUED | CANCELLED | `PATCH /status` | keduanya | ya (−) → stale |
| ISSUED / PARTIALLY_RECEIVED | PARTIALLY_RECEIVED / RECEIVED | Goods Receipt | keduanya | netral |

**Usul: pertahankan APPROVED dan ISSUED terpisah.** Biayanya hanya satu status dan satu klik (transisi `ISSUED` sudah ada), dan memberi visibilitas "sudah disetujui, belum dikirim ke supplier" serta menjaga langkah "Terbitkan" identik untuk kedua source. Bila ingin lebih ramping: gabungkan sehingga *Approve* langsung menghasilkan `ISSUED` — menghemat 1 status, 1 tombol, 1 baris tabel; konsekuensinya tidak ada jeda antara persetujuan dan pengiriman.

**Approval tanpa auth (MVP).** `decided_by` = teks bebas dari dialog (nama terakhir diingat di `localStorage`); tidak ada pemisahan tugas pembuat vs approver — berbasis kepercayaan. **Jalur upgrade RBAC:** aktifkan skeleton `auth.py/users.py/security.py` yang sudah ada → tabel `users(role)` → dependency `require_role("APPROVER")` pada `/approve` & `/reject` → `decided_by` menjadi FK `decided_by_user_id` (+ larangan `created_by == approver`). Path dan body endpoint tidak berubah, kecuali header token.

**Approval hanya untuk MANUAL.** PO planning sudah melewati dua langkah sadar (pemilihan supplier + dialog "Konfirmasi & Buat PO"), jadi approval tambahan hanya menambah gesekan. Bila nanti dibutuhkan kontrol nilai, tambahkan ambang (`approval_threshold`) yang berlaku untuk kedua source, bukan approval wajib semua PO.

### 3.6 Dampak ke tes yang ada (T6)

| Tes / artefak | Perubahan |
|:--|:--|
| `test_planning_service.py` (`planned` fixture), `test_sourcing_service.py` (`run` fixture) | Setelah `db.add_all([Schedule…])` → buat via `schedule_service.create_schedule` atau panggil `recalc_allocated(db)` |
| `scripts/seed.py --demo-schedules` | Memakai `schedule_service.create_schedule` (batch code + line + recalc) |
| `test_inventory_po_master.py::test_schedule_validation_and_soft_delete`, `test_flow_e2e.py` | `PATCH {status}` → `PATCH /status`; `DONE` → `COMPLETED`; `DELETE` tetap lulus (alias) |
| `test_replanning_after_po_has_zero_shortfall` | Tetap lulus (`on_order` PLANNING tidak berubah) |
| Baru (±25 tes) | Golden Phase 2 pasca-refactor · transisi & dampak stok · atomik 409 · `recalc` idempoten & dari-nol · hook BOM tolerant · stale (`schedule`/`PO`/`inventory`) · 409 PO dari run basi · mesin transisi PO per source · `on_order` per status · validasi Manual PO · migrasi DB lama |

---

## 4. Delta Frontend

### 4.1 Struktur file (hanya yang baru/berubah)

```
frontend/
├─ package.json                         (ubah: +@fullcalendar/{core,react,daygrid,interaction} — PIN 6.1.21, T4)
└─ src/
   ├─ services/
   │  ├─ productionLineService.js       (baru)  list()
   │  ├─ scheduleService.js             (ubah)  +setStatus(id,status) +materials(id); update() tanpa status
   │  ├─ purchaseOrderService.js        (ubah)  +createManual +update +submit +approve +reject
   │  └─ api.js                         (ubah)  interceptor meneruskan `data` (lihat §4.6)
   ├─ store/masterStore.js              (ubah)  +lines (production lines)
   ├─ utils/constants.js                (ubah)  SCHEDULE_STATUS, PO_STATUS, +PO_SOURCE, +MOVEMENT_TYPE
   ├─ styles/index.css                  (ubah)  kelas event kalender .ev-*
   ├─ pages/
   │  ├─ MpsPage.jsx                    (ubah)  toggle Tabel|Kalender, banner stale, drawer
   │  ├─ PlanningRunPage.jsx            (ubah)  banner stale; tab PO diblok
   │  ├─ InventoryPage.jsx              (ubah)  kolom Dipesan + tombol Riwayat
   │  ├─ PurchaseOrdersPage.jsx         (ubah)  tombol "+ Buat PO Manual", filter Sumber
   │  ├─ PurchaseOrderDetailPage.jsx    (ubah)  workflow approval
   │  └─ ManualPoPage.jsx               (baru)  /purchase-orders/new  &  /purchase-orders/:id/edit
   └─ features/
      ├─ mps/
      │  ├─ ScheduleCalendar.jsx        (baru, di-import lazy)
      │  ├─ ScheduleDrawer.jsx          (baru)  side-panel batch
      │  ├─ StartProductionDialog.jsx   (baru)  pratinjau dampak stok + daftar kurang (409)
      │  ├─ StaleRunBanner.jsx          (baru)
      │  ├─ ScheduleTable.jsx           (ubah)  +Batch, +Line, status baru, aksi dari `allowed_transitions`
      │  ├─ ScheduleFormModal.jsx       (ubah)  +dropdown Line
      │  └─ PlanningRunList.jsx         (ubah)  badge "Basi"
      ├─ material/
      │  ├─ InventoryTable.jsx          (ubah)  +Dipesan, +Riwayat
      │  ├─ MovementHistoryModal.jsx    (baru)  daftar GET /stock-movements?material_id=
      │  └─ SupplierFormModal.jsx / SupplierTable.jsx (ubah) +payment_term_days
      └─ procurement/
         ├─ ManualPoForm.jsx            (baru)
         ├─ ApprovalDialog.jsx          (baru)  Approve (nama) / Reject (nama + alasan)
         ├─ PoHeader.jsx                (ubah)  workflow bar per status & source
         ├─ PoTable.jsx                 (ubah)  kolom Sumber (badge "Manual PO")
         └─ PoGeneratePanel.jsx         (ubah)  blok konfirmasi bila run basi
```

**Store:** tidak ada store baru. Data jadwal, run, dan drawer cukup berupa state lokal `MpsPage` + `useFetch` (pola FP §2.2); kalender memakai `info.revert()` bawaan FullCalendar untuk rollback optimistis. Hanya `masterStore` yang diperluas (`lines`).

### 4.2 Keputusan: library kalender dan penempatan halaman

**Evaluasi FullCalendar vs bangun sendiri**

| Kriteria | FullCalendar (dayGrid + interaction) | Bangun sendiri |
|:--|:--|:--|
| Tampilan Harian/Mingguan/Bulanan | Bawaan (`dayGridDay/Week/Month`) | Grid bulan mudah; mingguan/harian + navigasi + locale tambahan kerja |
| Drag-and-drop reschedule | Bawaan (`startEditable` per event, `revert()`) | HTML5 DnD manual; sentuhan/mobile dan aksesibilitas harus ditangani |
| Estimasi kerja | < 1 hari integrasi + styling | ±2–3 hari + risiko bug tepi (zona waktu, minggu mulai Senin) |
| Ukuran bundle (**terukur**, gzip) | **+68 KB** (116,2 vs 48,0 KB baseline react+router); +timeGrid hanya +9 KB lagi | ≈ 0 KB |
| Lisensi | Inti & plugin ini **MIT**; plugin resource/timeline berbayar → tidak dipakai | – |

**Rekomendasi: FullCalendar, tetapi `dayGrid` + `interaction` saja (tanpa `timeGrid`)** — jadwal hanya punya tanggal tanpa jam (T5), jadi kolom jam tidak bermakna. Aturan pemakaian:
- Pin **semua** paket ke `6.1.21` (T4); jangan `@latest`.
- Muat lewat `React.lazy` agar +68 KB hanya diunduh saat tab Kalender dibuka.
- Tampilan per-line (resource view) berbayar → line cukup ditampilkan sebagai teks/filter.
- Uji jsdom yang sudah dijalankan: event PLANNED memiliki kelas `fc-event-draggable`, event COMPLETED tidak; tiga tombol tampilan & locale `id` bekerja.

**Penempatan: toggle `[Tabel | Kalender]` pada `/mps` (`?view=calendar`), bukan route baru `/mps/calendar`.**
Alasan: (1) data sama (`GET /schedules`), sehingga tidak ada fetch/state ganda; (2) modal Tambah/Edit, drawer, dan banner stale dipakai bersama; (3) sidebar dan routing tidak berubah; (4) tautan tetap dapat dibagikan lewat query (pola yang sudah dipakai halaman BOM). Default tampilan = **Kalender** (`/mps` membuka kalender; tabel lewat `?view=table`) — lihat keputusan #7, §6.

### 4.3 Wireframe

**`/mps?view=calendar` + side-panel**

```
MPS & Stock Planning                         [ Tabel | ▣ Kalender ]        [ + Tambah Jadwal ]
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ ⚠ Planning Run #3 (12–13 Okt) basi — jadwal berubah setelah run dibuat.  [ Jalankan Ulang ]│
└──────────────────────────────────────────────────────────────────────────────────────────┘
Line: [ Semua ▾ ]   [ ] Tampilkan dibatalkan                [ Harian | Mingguan | ▣ Bulanan ]
 ◀  ▶  Hari ini                          Oktober 2026
┌────────┬────────┬────────┬────────┬────────┬────────┬────────┐   ┌ BATCH-20261012-001 ───── ✕ ┐
│ Sen 12 │ Sel 13 │ Rab 14 │ Kam 15 │ Jum 16 │ Sab 17 │ Min 18 │   │ ● In Progress              │
│▍B…-001 │▍B…-001 │        │        │        │        │        │   │ Sepeda Gunung (FG-BIKE-01) │
│ Sepeda │ ⚠ Sepe │        │        │        │        │        │   │ Qty 30 · LINE-01           │
│ ×30 L1 │ da ×20 │        │        │        │        │        │   │ Tanggal 12 Okt 2026        │
└────────┴────────┴────────┴────────┴────────┴────────┴────────┘   │ Mulai 12 Okt 08:10         │
 ▍ biru=Planned  kuning=In Progress  hijau=Completed  abu/redup=Cancelled │ [ Selesaikan ]             │
 ⚠ = tanggal berada di rentang run yang basi                      │ ─ Alokasi Material ─────── │
                                                                   │ SKU       Butuh Fisik Tersedia Status│
                                                                   │ RM-RUB-01 60    20    -20   ●Critical│
                                                                   │ RM-PDL-01 60    60     20   ●Warning │
                                                                   │ Status stok = kondisi GLOBAL      │
                                                                   │ material, bukan khusus batch ini. │
                                                                   └────────────────────────────┘
```

Tombol side-panel mengikuti `schedule.allowed_transitions` dari server — PLANNED: `[Mulai Produksi] [Batalkan] [Edit]`; IN_PROGRESS: `[Selesaikan]`; COMPLETED/CANCELLED: tanpa tombol.

**Dialog "Mulai Produksi" (pratinjau dampak stok)** — data dari `GET /schedules/{id}/materials`:

```
┌ Mulai Produksi · BATCH-20261012-001 ───────────────────────────────┐
│ Material memakai stok fisik sekarang dan tidak dapat dibatalkan.    │
│ Material        Butuh    Stok fisik: sebelum → sesudah              │
│ Ban Luar Karet  60 Buah  80  →  20                                  │
│ Pedal Sepeda    60 Buah  120 →  60                                  │
│ Besi Tubing     45 kg    100 →  55          … (scroll, 15 material) │
│ ✓ Stok tersedia (available) tidak berubah; Terkunci turun sebesar   │
│   kebutuhan batch.                                                   │
│                                          [ Batal ] [ Mulai Produksi ]│
└─────────────────────────────────────────────────────────────────────┘
Bila server membalas 409 (stok berubah sejak pratinjau), dialog yang SAMA berganti isi:
│ ✕ Stok fisik tidak cukup:                                           │
│   RM-RUB-01 Ban Luar Karet — butuh 60, fisik 50, kurang 10         │
│                                                    [ Tutup ]        │
```

**Form Manual PO — `/purchase-orders/new`**

```
Buat PO Manual                                           [ Simpan Draft ] [ Simpan & Submit ]
┌ Header ────────────────────────────────────────────────────────────────────────────────┐
│ Supplier* [ PT Karet Nusantara — Net 30 ▾ ]   Tanggal PO* [ 2026-10-13 ]                │
│ Catatan   [ Order mendesak untuk batch Senin ............................ ]            │
└────────────────────────────────────────────────────────────────────────────────────────┘
┌ Item ──────────────────────────────────────────────────────────────────────────────────┐
│ Material*          Qty*   Sat.    Harga Satuan*    Tgl Kebutuhan   Subtotal      [🗑]    │
│ [RM-RUB-01 Ban… ▾] [100]  Buah    [35.000]         [2026-10-18]    Rp 3.500.000        │
│   Lead time 2 hari (supplier ini) · Tersedia -20 · Dipesan 0 · Safety 40               │
│ [RM-PDL-01 Ped… ▾] [ 50]  Buah    [48.000]         [          ]    Rp 2.400.000        │
│   ⚠ Supplier belum terdaftar untuk material ini — tetap bisa dipesan                    │
│ [ + Tambah item ]                                          Total  Rp 5.900.000          │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

*Tampilan lead time:* lead time melekat pada **pasangan material–supplier** (`material_suppliers.lead_time_days`), bukan pada supplier. Karena itu ditampilkan sebagai teks kecil read-only **per baris**, bergantung pada supplier header yang dipilih; bila pasangan tidak ada, yang muncul adalah peringatan (bukan angka). Nilainya tidak disimpan pada PO. Satuan otomatis dari `materials.uom` (read-only). Harga default dari relasi material–supplier dan tetap bisa diubah.

**Detail PO — workflow approval (`PoHeader`)**

```
PO-202610-0007 · PT Karet Nusantara  [Manual PO] [Menunggu Approval]      Total Rp 3.500.000
Termin: Net 30 · Tgl PO 13 Okt 2026 · Dikirim untuk approval 13 Okt 09:12
Aksi:  DRAFT → [Edit] [Submit untuk approval] [Batalkan]
       PENDING_APPROVAL → [Approve] [Reject…] [Batalkan]
       APPROVED → [Terbitkan] [Batalkan]       (info: Disetujui oleh Budi, 13 Okt 10:05)
       REJECTED → ⛔ "Alasan: harga di atas kontrak"  [Edit] [Submit ulang] [Batalkan]
       ISSUED/PARTIALLY_RECEIVED → panel "Penerimaan Barang" (tidak berubah)
Dialog Approve:  Nama approver* [ Budi ]            [ Batal ][ Approve ]
Dialog Reject :  Nama* [ Budi ]  Alasan* [ ........ ]  [ Batal ][ Reject ]
```

### 4.4 Service dan konstanta

```js
// services/scheduleService.js (tambahan)
setStatus: (id, status) => api.patch(`/schedules/${id}/status`, { status }),
materials: (id) => api.get(`/schedules/${id}/materials`),
update: (id, body) => api.patch(`/schedules/${id}`, body),          // production_date | target_qty | product_id | production_line_id

// services/purchaseOrderService.js (tambahan)
createManual: (body) => api.post('/purchase-orders', body),
update:  (id, body) => api.patch(`/purchase-orders/${id}`, body),
submit:  (id) => api.post(`/purchase-orders/${id}/submit`),
approve: (id, approved_by) => api.post(`/purchase-orders/${id}/approve`, { approved_by }),
reject:  (id, rejected_by, reason) => api.post(`/purchase-orders/${id}/reject`, { rejected_by, reason }),
```

Palet status (konsisten dengan `Badge` yang ada; `CANCELLED` jadwal diubah dari merah ke abu agar "redup"):

| Status | Badge `tone` | Event kalender (Tailwind) |
|:--|:--|:--|
| Jadwal PLANNED | `indigo` | `indigo-600`, latar `indigo-50` |
| IN_PROGRESS | `amber` | `amber-500`, latar `amber-50` |
| COMPLETED | `green` | `green-600`, latar `green-50` |
| CANCELLED | `slate` | `slate-400`, opacity .45, garis coret |
| PO PENDING_APPROVAL / APPROVED / REJECTED | `amber` / `violet` / `red` | – |
| Badge sumber PO "Manual PO" | `violet` | – |

```css
/* styles/index.css — warna event memakai variabel tema Tailwind v4 */
.fc .ev-PLANNED     { --c: var(--color-indigo-600); }
.fc .ev-IN_PROGRESS { --c: var(--color-amber-500); }
.fc .ev-COMPLETED   { --c: var(--color-green-600); }
.fc .ev-CANCELLED   { --c: var(--color-slate-400); opacity: .45; text-decoration: line-through; }
.fc .fc-event       { border: 0; border-left: 3px solid var(--c); background: color-mix(in srgb, var(--c) 12%, white);
                      color: var(--c); font-size: .75rem; }
.fc .ev-stale       { background-image: repeating-linear-gradient(135deg, transparent 0 6px, rgb(0 0 0 / .05) 6px 12px); }
```

### 4.5 Kode komponen kunci

**`features/mps/ScheduleCalendar.jsx`** — konfigurasi, drag-and-drop hanya untuk reschedule PLANNED:

```jsx
import { useMemo } from 'react';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import interactionPlugin from '@fullcalendar/interaction';
import { scheduleService } from '../../services/scheduleService';
import { toast } from '../../store/toastStore';

const inStale = (d, ranges) => ranges.some((r) => d >= r.date_from && d <= r.date_to);

export default function ScheduleCalendar({ schedules, staleRuns, showCancelled, lineId, onSelect, onChanged }) {
  const events = useMemo(() => schedules
    .filter((s) => (showCancelled || s.status !== 'CANCELLED') && (!lineId || s.production_line_id === lineId))
    .map((s) => ({
      id: String(s.id),
      title: `${s.batch_code} · ${s.product_name} ×${s.target_qty} · ${s.line_code}`,
      start: s.production_date, allDay: true,                // tanggal saja → tidak ada isu zona waktu
      startEditable: s.editable,                             // hanya PLANNED yang bisa diseret
      classNames: [`ev-${s.status}`, inStale(s.production_date, staleRuns) && 'ev-stale'].filter(Boolean),
    })), [schedules, staleRuns, showCancelled, lineId]);

  const onDrop = async (info) => {                           // update optimistis: event sudah pindah di layar
    try {
      await scheduleService.update(Number(info.event.id), { production_date: info.event.startStr.slice(0, 10) });
      toast.info('Jadwal dipindah. Planning run perlu dijalankan ulang.');
      onChanged();                                           // reload jadwal + run → banner basi muncul
    } catch (e) {
      info.revert();                                         // rollback bila backend menolak (mis. 409)
      toast.error(e.message);
    }
  };

  return (
    <FullCalendar
      plugins={[dayGridPlugin, interactionPlugin]}           // tanpa timeGrid (T5)
      initialView="dayGridMonth"
      headerToolbar={{ left: 'prev,next today', center: 'title', right: 'dayGridDay,dayGridWeek,dayGridMonth' }}
      buttonText={{ today: 'Hari ini', day: 'Harian', week: 'Mingguan', month: 'Bulanan' }}
      locale="id" firstDay={1} height="auto" dayMaxEvents={4}
      events={events}
      eventDurationEditable={false}                          // kalender hanya memindah tanggal, bukan durasi/status
      eventDrop={onDrop}
      eventClick={(info) => onSelect(Number(info.event.id))}
    />
  );
}
// MpsPage: const ScheduleCalendar = lazy(() => import('../features/mps/ScheduleCalendar'));  + <Suspense fallback={<Spinner/>}>
```

**`features/mps/ScheduleDrawer.jsx`** — aksi status sesuai transisi valid, tabel alokasi material:

```jsx
const ACTIONS = {
  IN_PROGRESS: { label: 'Mulai Produksi', variant: 'primary' },   // → StartProductionDialog
  COMPLETED:   { label: 'Selesaikan',     variant: 'primary' },
  CANCELLED:   { label: 'Batalkan',       variant: 'danger'  },   // → ConfirmDialog
};

export default function ScheduleDrawer({ schedule: s, onClose, onChanged, onEdit }) {
  const mats = useFetch(() => scheduleService.materials(s.id), [s.id, s.status, s.production_date, s.target_qty]);
  const [dialog, setDialog] = useState(null);                   // 'IN_PROGRESS' | 'CANCELLED' | null
  const [busy, setBusy] = useState(false);

  const apply = async (status) => {
    setBusy(true);
    try {
      await scheduleService.setStatus(s.id, status);
      toast.success('Status diperbarui');
      setDialog(null); onChanged();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <aside className="fixed inset-y-0 right-0 z-40 w-[420px] overflow-y-auto border-l bg-white p-4 shadow-xl">
      <header className="flex items-start justify-between">
        <div><h2 className="font-mono text-sm font-semibold">{s.batch_code}</h2><StatusChip status={s.status} /></div>
        <button onClick={onClose} aria-label="Tutup">✕</button>
      </header>
      <dl className="my-3 text-sm">{/* produk (SKU), qty, line, tanggal, mulai/selesai */}</dl>

      <div className="flex flex-wrap gap-2">
        {s.allowed_transitions.map((t) => (                     // aturan transisi berasal dari server, tidak diduplikasi di klien
          <Button key={t} variant={ACTIONS[t].variant} loading={busy && !dialog}
                  onClick={() => (t === 'COMPLETED' ? apply(t) : setDialog(t))}>{ACTIONS[t].label}</Button>
        ))}
        {s.editable && <Button variant="secondary" onClick={() => onEdit(s)}>Edit</Button>}
      </div>

      <h3 className="mt-5 text-sm font-semibold">Alokasi Material</h3>
      <MaterialAllocationTable data={mats.data} loading={mats.loading} />   {/* SKU, butuh, satuan, fisik, tersedia, StatusBadge */}
      <p className="mt-2 text-xs text-slate-500">Status stok adalah kondisi global material (semua jadwal PLANNED), bukan khusus batch ini.</p>

      <StartProductionDialog open={dialog === 'IN_PROGRESS'} schedule={s} materials={mats.data}
                             onClose={() => setDialog(null)} onDone={() => { setDialog(null); onChanged(); }} />
      <ConfirmDialog open={dialog === 'CANCELLED'} loading={busy} confirmLabel="Ya, batalkan"
                     message={`Batalkan ${s.batch_code}? Stok terkunci dilepas.`} onConfirm={() => apply('CANCELLED')} onCancel={() => setDialog(null)} />
    </aside>
  );
}
```

`StartProductionDialog`: tombol utama memanggil `setStatus(id,'IN_PROGRESS')`; pada error `e.status === 409 && e.data?.shortages` ia mengganti isi dialog menjadi daftar kekurangan (tanpa menutup). Baris pratinjau yang `enough === false` diberi teks merah sejak awal, tetapi keputusan akhir tetap milik server.

**`features/procurement/ManualPoForm.jsx`** — header, item, harga default, peringatan:

```jsx
export default function ManualPoForm({ initial, onSubmit, saving }) {
  const { materials, suppliers } = useMasterStore();
  const stock = useFetch(() => inventoryService.list(), []);               // available / on_order / safety per material
  const [h, setH] = useState({ supplier_id: initial?.supplier_id ?? '', po_date: initial?.po_date ?? todayISO(),
                               notes: initial?.notes ?? '' });
  const [rows, setRows] = useState(initial?.items?.map(toRow) ?? [newRow()]);
  const [links, setLinks] = useState({});                                    // material_id → relasi supplier (cache)

  const buyable = byCategory(materials, 'PURCHASED');                        // hanya master material beli
  const supplier = suppliers.find((s) => s.id === Number(h.supplier_id));
  const linkOf = (r) => links[r.material_id]?.find((l) => l.supplier_id === Number(h.supplier_id) && l.is_active);

  const pickMaterial = async (i, id) => {
    patchRow(i, { material_id: id, price_touched: false });
    if (id && !links[id]) {                                                  // relasi material–supplier dimuat sekali per material
      const ls = await materialService.listSuppliers(id);
      setLinks((p) => ({ ...p, [id]: ls }));
    }
  };

  useEffect(() => {                                                          // harga default dari relasi, selama belum diubah user
    setRows((rs) => rs.map((r) => (!r.price_touched && linkOf(r) ? { ...r, unit_price: String(linkOf(r).unit_price) } : r)));
  }, [links, h.supplier_id]);

  const errors = validate(h, rows);   // qty > 0 · harga ≥ 0 · needed_by ≥ po_date · material tidak duplikat · ≥ 1 item

  return (
    <>
      <Select value={h.supplier_id} onChange={(e) => setH({ ...h, supplier_id: e.target.value })}>
        <option value="">Pilih supplier…</option>
        {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name} — Net {s.payment_term_days}</option>)}
      </Select>
      {/* ... tanggal PO, catatan ... */}
      {rows.map((r, i) => {
        const m = materials.find((x) => x.id === Number(r.material_id));
        const l = linkOf(r), st = stock.data?.find((x) => x.material_id === Number(r.material_id));
        return (
          <tr key={i}>
            <td><Select value={r.material_id} onChange={(e) => pickMaterial(i, e.target.value)}>
              {buyable.filter((b) => b.id === Number(r.material_id) || !rows.some((x) => Number(x.material_id) === b.id))
                      .map((b) => <option key={b.id} value={b.id}>{b.sku} · {b.name}</option>)}   {/* tanpa duplikat */}
            </Select></td>
            {/* qty, satuan = m?.uom (read-only), harga (price_touched=true saat diketik), needed_by, subtotal */}
            <td colSpan={6}>
              {l && <p className="text-xs text-slate-500">Lead time {l.lead_time_days} hari (supplier ini)</p>}
              {r.material_id && supplier && !l &&
                <p className="text-xs text-amber-700">⚠ Supplier belum terdaftar untuk material ini — tetap bisa dipesan.</p>}
              {st && <p className="text-xs text-slate-500">Tersedia {st.available} · Dipesan {st.on_order} · Safety {st.safety_stock}</p>}
            </td>
          </tr>
        );
      })}
      <Button disabled={errors.length > 0} loading={saving} onClick={() => onSubmit(toPayload(h, rows))}>Simpan Draft</Button>
    </>
  );
}
```

### 4.6 Perubahan kecil lain

- **`api.js`** — meneruskan body error agar dialog dapat membaca `shortages`:
  `return Promise.reject({ status: err.response?.status, message, data: err.response?.data });`
- **`StaleRunBanner`** — memakai `GET /planning/runs`; tampil bila **run terbaru** `is_stale` (run basi yang lebih lama hanya diberi badge "Basi" di `PlanningRunList`). Tombol **Jalankan Ulang** mengisi `RunPlanningPanel` dengan rentang run tersebut; setelah `POST /planning/runs` baru, banner hilang.
- **`PlanningRunPage` / `PoGeneratePanel`** — bila `run.is_stale`: banner "Hasil planning sudah tidak berlaku", tombol "Konfirmasi & Buat PO" dinonaktifkan (server tetap 409 sebagai pengaman).
- **`InventoryTable`** — kolom *Dipesan* (`on_order`) dan tombol *Riwayat* → `MovementHistoryModal` (tabel waktu · tipe · qty bertanda · referensi: nomor PO atau `batch_code` dari `note`). Kolom *Terkunci* tidak perlu diubah — angkanya kini otomatis mengikuti jadwal.
- **`ScheduleFormModal`** — dropdown *Line* (default line aktif pertama, `masterStore.lines`); Edit hanya tersedia bagi PLANNED; produk kini dapat diubah selama PLANNED.
- **`SupplierFormModal`** — field *Termin pembayaran (hari)*.

---

## 5. Skenario Uji End-to-End

Basis: data seed (`on_hand/safety`: Ban 80/40 · Rangka Jok 50/15 · Besi 100/50 · Pedal 120/30), produk `FG-BIKE-01`, Senin = 12 Okt 2026, Selasa = 13 Okt 2026. Kebutuhan per unit: Ban 2, Rangka Jok 1, Besi 1,5 kg, Pedal 2.

### 5.1 Stok & status

| # | Langkah | Hasil yang diharapkan |
|:-:|:--|:--|
| 1 | `POST /schedules` Senin ×30 | `201`, `batch_code = BATCH-20261012-001`, `LINE-01`, PLANNED. *Terkunci*: Ban 60, Pedal 60, Besi 45, Rangka 30 |
| 2 | `POST /schedules` Selasa ×20 | **Terkunci Ban 100, Pedal 100**, Besi 75, Rangka 50 (tanpa menjalankan planning) |
| 3 | `POST /planning/runs` Sen–Sel | **Golden Phase 2**: Ban tersedia −20 / defisit 60 (CRITICAL) · Rangka 0 / 15 (CRITICAL) · Besi 25 / 25 (WARNING) · Pedal 20 / 10 (WARNING); `allocated` tidak berubah oleh run |
| 4 | `PATCH /schedules/{Senin}/status` `IN_PROGRESS` | `on_hand`: Ban **20**, Pedal 60, Besi 55, Rangka 20. *Terkunci*: Ban 40, Pedal 40, Besi 30, Rangka 20. **Tersedia tetap**: −20 / 20 / 25 / 0. 15 movement `PRODUCTION_ISSUE` (qty negatif, `ref_type=SCHEDULE`, `note=batch_code`; Ban −60). `started_at` terisi |
| 5 | `PATCH /schedules/{Selasa}/status` `IN_PROGRESS` | **`409`** `shortages=[{sku:RM-RUB-01, required:40, on_hand:20, short_by:20}]` (Pedal 40≤60, Besi 30≤55, Rangka 20≤20 cukup). **Tidak ada perubahan**: status tetap PLANNED, `on_hand` & movement sama seperti langkah 4 |
| 6 | `PATCH /schedules/{Selasa}/status` `CANCELLED` | *Terkunci* semua material → 0; `on_hand` tetap; tidak ada movement. Tersedia: Ban 20 (WARNING, < safety 40) · Pedal 60 · Besi 55 · Rangka 20 (SAFE) |
| 7 | `PATCH …/{Senin}/status` `COMPLETED` | `completed_at` terisi; stok & movement **tidak berubah** |
| 8 | Negatif | `COMPLETED → PLANNED/IN_PROGRESS`, `CANCELLED → *`, `PLANNED → COMPLETED` → `409`; `PATCH /schedules/{Senin}` (IN_PROGRESS/COMPLETED) → `409`; `PUT /inventory/{id}` tidak mengubah `allocated` |
| 9 | Regresi | Pada DB baru: ulangi langkah 1–3 → angka **identik** dengan Phase 2 dokumen alur (run kini hanya *membaca* `allocated`, hasilnya sama dengan saat run menimpanya) |
| 10 | BOM | Jadwal PLANNED ada → ubah qty BOM → *Terkunci* ikut berubah (tanpa penolakan); sub-part kosong sementara tidak memblokir pembuatan sub-part; membuat jadwal untuk produk ber-BOM tidak lengkap → `422` |

### 5.2 Kalender

| # | Langkah | Hasil yang diharapkan |
|:-:|:--|:--|
| 1 | Buat jadwal Sen ×30 dan Sel ×20 di modal | Muncul di tabel **dan** kalender (satu sumber `GET /schedules`); kode batch terlihat |
| 2 | Jalankan planning Sen–Sel → run #1 (DRAFT, `is_stale=false`) | Tidak ada banner |
| 3 | Seret event Selasa → Rabu (`PATCH {production_date}`) | Event pindah; `batch_code` **tetap**; run #1 `is_stale=true`; banner "Planning Run #1 basi" + ⚠ pada event di rentang 12–13 Okt; *Terkunci* tidak berubah (global) |
| 4 | `POST /planning/runs/1/purchase-orders` | `409` "Run basi — jalankan ulang planning" |
| 5 | Klik **Jalankan Ulang** (rentang 12–14 Okt) | Run #2 `is_stale=false`; banner hilang; angka Ban −20 / Rangka 0 / Besi 25 / Pedal 20; run #1 hanya diberi badge "Basi" |
| 6 | Buat jadwal Jumat ×10 (di luar rentang run #2) | Run #2 menjadi basi (T1: allocated global); *Terkunci* Ban 120 |
| 7 | Seret event IN_PROGRESS / COMPLETED | Tidak dapat diseret (`fc-event-draggable` tidak ada); `PATCH` langsung → `409`; bila PATCH gagal pada event PLANNED, event kembali dan toast tampil |
| 8 | Tampilan Harian / Mingguan / Bulanan; toggle "Tampilkan dibatalkan" | Cancelled tersembunyi secara default, redup bila ditampilkan |

### 5.3 Manual PO

Kondisi awal: setelah langkah 5.1-#3 (belum ada jadwal dimulai); supplier PT Karet Nusantara `payment_term_days=30`.

| # | Langkah | Hasil yang diharapkan |
|:-:|:--|:--|
| 1 | `POST /purchase-orders` {Karet, Ban ×100 @ 35.000, `needed_by_date` = PO+5 hari} | `201`, **DRAFT**, `source=MANUAL`, `planning_run_id=NULL`, total **Rp 3.500.000**, `warnings=[]`; daftar menampilkan label **Manual PO**; `GET /inventory` `on_order` Ban = **0** (DRAFT tidak dihitung) |
| 2 | `POST …/submit` | **PENDING_APPROVAL**; run DRAFT menjadi basi; `on_order` Ban = **100**; planning baru: Ban tersedia −20, `on_order` 100 → defisit **0** (mencegah pemesanan ganda) |
| 3 | `POST …/approve` {`approved_by:"Budi"`} | **APPROVED**, `decided_by/at` terisi; `on_order` tetap 100 |
| 4 | `PATCH …/status` `ISSUED` | **ISSUED** |
| 5 | `POST …/receipts` Ban ×100 | **RECEIVED**; `on_hand` Ban **80 → 180**, `on_order` 100 → 0, tersedia **80** (SAFE) — sama dengan baris Ban pada Phase 5 dokumen alur; movement `GOODS_RECEIPT`; run **tidak** ditandai basi (penerimaan netral) |
| 6 | Jalur tolak: PO kedua → submit → `reject` {nama, alasan "harga di atas kontrak"} | **REJECTED**, `on_order` kembali ke 0, run DRAFT basi; `PATCH` qty → 120 (`200`); submit ulang → PENDING → approve |
| 7 | Validasi | Material duplikat · qty 0 · harga −1 · `needed_by_date` < `po_date` · material bukan PURCHASED · item kosong → `422`; supplier tak terhubung ke material → `201` + `warnings` |
| 8 | Status/aksi tidak valid | Approve pada DRAFT, edit pada PENDING_APPROVAL/ISSUED, `ISSUED` langsung dari DRAFT manual, `submit` pada PO PLANNING, `PATCH` pada PO PLANNING, receipt pada APPROVED → `409` |
| 9 | Regresi PO planning | PO hasil run: `source=PLANNING`, `DRAFT → ISSUED` tanpa approval, `on_order` DRAFT tetap dihitung; total Rp 3.400.000 / 3.500.000 / 2.400.000 pada skenario Phase 4 tetap sama |

---

## 6. Keputusan Final dan Asumsi

Semua default hasil rekomendasi telah dikonfirmasi sebagai **keputusan final**. Satu keputusan berubah dari rancangan awal: **#7** (tampilan default `/mps`: Tabel → **Kalender**). Kolom kanan memuat alternatif yang ditolak beserta alasannya.

| # | Topik | Keputusan final | Alternatif yang ditolak / dampak |
|:-:|:--|:--|:--|
| 1 | **Titik potong stok** | **Mulai Produksi** — material secara fisik keluar gudang saat batch dimulai | *Selesai* (backflush): stok baru berkurang di akhir; `allocated` harus tetap menahan selama IN_PROGRESS → logika lebih rumit |
| 2 | Kapasitas line | Tidak ada; dua batch pada line dan hari yang sama diizinkan, tanpa deteksi bentrok | Finite capacity scheduling = di luar scope |
| 3 | `production_line_id` | Wajib di DB; opsional pada request (default = line aktif pertama; aturan ini dicantumkan di deskripsi OpenAPI, UI selalu mengirim line eksplisit) | *Wajib di request*: lebih eksplisit tetapi memaksa ±10 tes/seed berubah tanpa manfaat nyata, karena line belum punya kapasitas. *Nullable*: menambah kasus "belum ditentukan" di semua tampilan |
| 4 | Master line | Hanya `GET /production-lines`; line baru lewat seed/SQL (2 line cukup untuk MVP) | CRUD + halaman master (±1 hari): ditunda sampai line bertambah |
| 5 | Cakupan stale | **Semua run DRAFT** setiap mutasi jadwal (T1) + perubahan set PO terhitung + `PUT /inventory` (T3) | Hanya run yang rentangnya memuat tanggal lama/baru (sesuai brief): lebih tenang tetapi dapat menyisakan run yang diam-diam salah |
| 6 | Run basi vs pembuatan PO | `POST …/purchase-orders` ditolak 409 | Hanya peringatan di UI (risiko pesan ganda) |
| 7 | Tampilan default `/mps` | **Kalender** (`?view=table` untuk tabel). Kalender adalah inti fitur: menampilkan batch, line, status, dan reschedule dalam satu layar; tabel hanya satu klik. Belum ada pengguna yang bergantung pada tampilan lama, dan kalender dimuat lazy sehingga tidak membebani halaman lain | Tabel sebagai default: aman terhadap perilaku lama, tetapi fitur utama tersembunyi di balik satu klik |
| 8 | `batch_code` | Immutable; tanggal pada kode = tanggal produksi **saat dibuat**, tidak ikut berubah saat drag | Kode mengikuti tanggal terkini → identitas batch berubah (tidak disarankan) |
| 9 | Tanggal lampau | Boleh (entri susulan batch yang sudah berjalan; data demo dan seed berbasis "Senin terdekat" bisa jatuh di masa lalu) | Tolak tanggal < hari ini: akan menggagalkan entri susulan dan seed demo; dapat ditambahkan nanti lewat `eventAllow` + validasi 422 |
| 10 | APPROVED vs ISSUED | **Dipisah** (lihat §3.5): biaya 1 status + 1 klik, tetapi langkah "Terbitkan" identik untuk kedua source dan ada visibilitas "sudah disetujui, belum dikirim" | Digabung: Approve langsung ISSUED |
| 11 | Identitas approver & nama kolom | Teks bebas, tanpa pemisahan tugas. Kolom bernama **`decided_by` / `decided_at`** (bukan `approved_by/approved_at`) karena satu pasangan kolom mencatat persetujuan *dan* penolakan | RBAC (jalur upgrade pada §3.5); nama `approved_by` akan menyesatkan untuk PO yang ditolak |
| 12 | Approval PO planning | Tidak ada | Ambang nilai untuk kedua source |
| 13 | `payment_term_days` | Dibaca dari master supplier (tidak di-snapshot ke PO): prinsip lean; dampaknya hanya tampilan historis bila termin diubah | Snapshot pada PO (+1 kolom, ±0,1 hari): ditunda sampai ada kebutuhan dokumen PO historis/cetak |
| 14 | Item Manual PO di luar master | **Tidak didukung**: Goods Receipt harus memperbarui `inventory`, yang berkunci pada `material_id`; item bebas memutus rantai stok & BOM | Material "non-stok" dengan flag khusus (fase berikutnya) |
| 15 | Alokasi material per batch | Dihitung dari **BOM saat ini**; realisasi aktual ada di `stock_movements` | Snapshot per jadwal = tabel baru (dilarang di brief) |
| 16 | Salah menekan "Mulai Produksi" | Tanpa Undo; koreksi lewat `ADJUSTMENT` yang sudah ada; mitigasi: dialog konfirmasi dengan pratinjau | Undo status (di luar scope) |
| 17 | Zona waktu | `started_at/completed_at/submitted_at/decided_at` disimpan UTC naif seperti `created_at`; tanggal produksi/PO berupa `Date` murni | – |
| 18 | `DELETE /schedules/{id}` | Dipertahankan sebagai alias pembatalan (deprecated) | Hapus endpoint + ubah tes |
| 19 | Pembatalan PO PENDING_APPROVAL | `PENDING → CANCELLED` (tanpa "tarik kembali ke DRAFT") | Tambah transisi `PENDING → DRAFT` |
| 20 | `unit_price` Manual PO | Integer Rupiah (konsisten BP §1.2); `line_total = round(qty × harga)` | `Numeric` bila butuh sen |

---

## 7. Estimasi Pengerjaan Tambahan

Asumsi: satu developer yang sudah mengenal basis kode; sudah termasuk tes; di luar UAT, Alembic, dan hardening. Rentang ±25%.

| Area | Pekerjaan | Hari kerja |
|:--|:--|:-:|
| **Backend** | Skema + enum + skrip migrasi + seed (lines, term, demo) | 1,0 |
| | `allocation_service`, `schedule_service` (kode batch, transisi, `PRODUCTION_ISSUE`), perubahan `planning_service`, stale, hook BOM/inventory | 2,5 |
| | Endpoint & skema jadwal, `…/materials`, `production-lines`, `AppError.extra` | 1,0 |
| | Manual PO: model, mesin transisi, validasi, `on_order` per source, 6 endpoint | 2,0 |
| | Tes: perbaikan fixture lama + ±25 tes baru | 1,5 |
| | **Subtotal backend** | **8,0** |
| **Frontend** | Kalender (FullCalendar, CSS, toggle, lazy, filter, banner stale) | 2,0 |
| | Drawer + tabel alokasi + `StartProductionDialog` (409) | 2,0 |
| | `ScheduleTable/Form`, Inventory (Dipesan, Riwayat), Supplier (TOP) | 1,0 |
| | Manual PO: form, halaman, rute | 2,5 |
| | Workflow approval (`PoHeader`, `ApprovalDialog`), daftar/filter PO, blok run basi | 1,5 |
| | Pengujian alur UI (perluasan uji jsdom) + polesan | 0,5 |
| | **Subtotal frontend** | **9,5** |
| **Total** | | **17,5 hari-orang** |

Dengan dua developer paralel ≈ **10 hari kalender**. Jalur kritis: API jadwal & transisi (±3,5 hari backend) → drawer/dialog frontend. Urutan yang disarankan: (1) skema + migrasi + `recalc_allocated` + refactor `run_planning` + perbaikan tes; (2) status jadwal + `PRODUCTION_ISSUE`; (3) kalender + drawer; (4) Manual PO backend → frontend.

---

## 8. Di Luar Scope

| Item | Alasan | Jalur upgrade |
|:--|:--|:--|
| Perencanaan kapasitas (finite capacity), deteksi bentrok line | Brief | Model kapasitas per line/hari |
| Notifikasi email/push | Brief | Antrian notifikasi pada event status |
| Approval multi-level / delegasi / ambang nilai | Brief | Tabel aturan approval |
| Gantt chart / tampilan resource-timeline (berbayar) | Brief; lisensi | Evaluasi ulang setelah volume jadwal tumbuh |
| Undo status | Brief | Transaksi pembalik + movement koreksi |
| Tabel snapshot alokasi per jadwal | Brief | Tabel `schedule_allocations` |
| Stok barang jadi (FG) | Brief; Inventory hanya material BUY | `Inventory` untuk FINISHED + `PRODUCTION_RECEIPT` saat COMPLETED |
| Backflush / konsumsi material aktual & selisih | Brief | Input realisasi pada "Selesaikan" |
| Item Manual PO di luar master material | Rantai Goods Receipt → `inventory` (keputusan #14) | Flag material non-stok |
| CRUD master production line, RBAC/auth, Alembic | Disederhanakan untuk MVP | Lihat keputusan #4, #11 dan BP §7 |
| Cetak/ekspor PO (PDF), multi-currency, pajak | Tidak ada di alur | Fase berikutnya |


---

## 9. Catatan Implementasi (rancangan → kode)

Seluruh isi §3–§5 diimplementasikan. Verifikasi: **60 tes backend** (termasuk golden Phase 2 pasca-refactor, 14 tes sinkron stok–jadwal, 9 tes Manual PO) dan **24 tes UI** (jsdom + backend sungguhan; drag-and-drop diuji dengan mock FullCalendar karena jsdom tidak punya layout). Migrasi diuji pada DB berformat lama (DONE→COMPLETED, kode batch, `allocated` dihitung ulang, PO lama → `PLANNING`).

Penyimpangan kecil dari rancangan (semuanya menyederhanakan):

| Rancangan | Implementasi | Alasan |
|:--|:--|:--|
| Tabel jadwal memiliki aksi status per baris | Tabel hanya *Detail* dan *Edit*; seluruh aksi status lewat side-panel | Satu tempat untuk dialog konfirmasi/pratinjau stok; panel juga dapat dibuka dari tabel |
| `PlanningRunPage` banner → isi panel | Banner di halaman run mengarahkan ke `/mps` (panel run ada di sana) | Panel planning hanya ada di MPS |
| Ikon tutup modal berlabel "Tutup" | Diubah menjadi "Tutup dialog" | Menghindari dua tombol bernama sama (aksesibilitas) |
| `GET /stock-movements` tanpa parameter tambahan | Modal riwayat memakai `limit=200` | Batas tampilan |
| `ScheduleOut` diisi dari model | `editable` dan `allowed_transitions` dihitung dari satu tabel transisi (`models/schedule.NEXT_STATUS`) yang juga dipakai service | Aturan transisi tidak terduplikasi |
| Sesi `autoflush=False` | `bom_service._after_change` dan service jadwal memanggil `flush()` sebelum `recalc_allocated` | Perubahan belum-di-flush tidak terlihat oleh query hitung ulang (ditemukan saat implementasi) |

Temuan saat implementasi: tes lama yang menyisipkan `Schedule` lewat ORM kini gagal (kolom `batch_code` NOT NULL, `allocated` tidak lagi diisi planning) — fixture dipindah ke `schedule_service.create_schedule` (sesuai T6).
