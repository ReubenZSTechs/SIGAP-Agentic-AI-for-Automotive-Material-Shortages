"""Indonesian -> English for texts the backend shows to users (REST errors, chat cards, form messages).

The business code keeps writing Indonesian. When the user chose English (`Accept-Language: en` or the chat's
`language`), the text is translated here just before it leaves the backend:

    translate("Supplier tidak ditemukan", "en")            -> "Supplier not found"
    translate("SKU 'RM-X' sudah terdaftar", "en")          -> "SKU 'RM-X' is already registered"

1. an exact match in EXACT, else 2. the first matching regex in PATTERNS (values are copied with {0}, {1} …),
else 3. a few sentences joined with "; " are translated one by one, else 4. the original text (never fails).
"""
import re

EXACT = {
    # ---- REST errors (app/services, app/api)
    "Agent belum dikonfigurasi: isi AICORE_* di backend/.env untuk memproses balasan supplier.":
        "The agent is not configured: fill in AICORE_* in backend/.env to process supplier replies.",
    "Belum ada production line aktif": "There is no active production line yet",
    "Pelanggaran constraint database": "Database constraint violation",
    "Terjadi kesalahan di server": "An unexpected server error occurred",
    "Eksekusi tool tidak ditemukan": "Tool run not found",
    "Endpoint sandbox hanya aktif bila TELEGRAM_MODE=sandbox": "The sandbox endpoint only works when TELEGRAM_MODE=sandbox",
    "Hanya Manual PO yang melalui alur approval/edit; PO hasil planning tidak dapat diubah":
        "Only manual POs go through approval/editing; POs from planning cannot be changed",
    "Hanya Produk Final yang dapat dijadwalkan produksi": "Only finished products can be scheduled for production",
    "Hanya untuk TELEGRAM_MODE=sandbox": "Only for TELEGRAM_MODE=sandbox",
    "Inkonsistensi data material pada hasil eksplosi": "Inconsistent material data in the explosion result",
    "Item BOM tidak ditemukan": "BOM item not found",
    "Item ini bukan sub-part": "This item is not a sub-part",
    "Jadwal tidak ditemukan": "Schedule not found",
    "Material ini tidak memiliki defisit; tidak perlu dipesan": "This material has no shortfall; it does not need to be ordered",
    "Material masih dipakai (BOM/PO/jadwal/planning/stok); nonaktifkan dengan PATCH is_active=false":
        "The material is still used (BOM/PO/schedule/planning/stock); deactivate it with PATCH is_active=false",
    "Material tidak boleh duplikat dalam satu PO": "A material cannot appear twice in one PO",
    "PO tanpa item tidak dapat disubmit": "A PO without items cannot be submitted",
    "PO untuk planning run ini sudah dibuat": "POs for this planning run were already created",
    "Panggilan agent tidak ditemukan": "Agent call not found",
    "Parent BOM harus produk final atau sub-part (bukan material beli)": "A BOM parent must be a finished product or sub-part (not a purchased material)",
    "Penambahan item akan menyebabkan siklus BOM": "Adding this item would create a BOM cycle",
    "Percakapan tidak ditemukan": "Conversation not found",
    "Permintaan revisi tidak ditemukan": "Revision request not found",
    "Pilihan opsi hanya untuk revisi PO": "Choosing an option is only for PO revisions",
    "Planning line tidak ditemukan": "Planning line not found",
    "Planning run sudah PO_GENERATED": "The planning run is already PO_GENERATED",
    "Planning run sudah PO_GENERATED; pilihan supplier tidak dapat diubah": "The planning run is already PO_GENERATED; supplier choices cannot be changed",
    "Planning run tidak ditemukan": "Planning run not found",
    "Production line nonaktif": "Production line inactive",
    "Production line tidak ditemukan": "Production line not found",
    "Produk Final tidak dapat menjadi komponen BOM; gunakan material beli atau sub-part":
        "A finished product cannot be a BOM component; use a purchased material or sub-part",
    "Produk masih dipakai (BOM/jadwal/planning); nonaktifkan dengan PATCH is_active=false":
        "The product is still used (BOM/schedule/planning); deactivate it with PATCH is_active=false",
    "Produk tidak ditemukan": "Product not found",
    "Produk yang dijadwalkan harus bertipe MAKE": "A scheduled product must be of type MAKE",
    "Purchase Order tidak ditemukan (mungkin sudah dihapus)": "Purchase order not found (it may have been deleted)",
    "Purchase Order tidak ditemukan": "Purchase order not found",
    "Relasi BOM parent-child sudah ada": "This BOM parent-child link already exists",
    "Relasi material-supplier tidak ditemukan": "Material-supplier link not found",
    "Run basi — jadwal, PO, atau stok berubah sejak run dibuat. Jalankan ulang planning.":
        "Stale run — schedules, POs or stock changed since the run was created. Run planning again.",
    "Simulasi hanya aktif bila TELEGRAM_MODE=sandbox": "Simulation only works when TELEGRAM_MODE=sandbox",
    "Stok fisik tidak cukup untuk memulai produksi": "Not enough stock on hand to start production",
    "Supplier belum ditautkan ke chat sandbox": "The supplier is not linked to a sandbox chat yet",
    "Supplier masih dipakai (relasi material/PO/planning); nonaktifkan dengan PATCH is_active=false":
        "The supplier is still used (material links/PO/planning); deactivate it with PATCH is_active=false",
    "Supplier nonaktif": "Supplier inactive",
    "Supplier sudah terhubung dengan material ini": "The supplier is already linked to this material",
    "Supplier tidak ditemukan": "Supplier not found",
    "Supplier tidak terdaftar untuk material ini": "The supplier is not registered for this material",
    "Template tidak ditemukan": "Template not found",
    "Terdapat child duplikat pada daftar item BOM": "The BOM item list contains a duplicate child",
    "Tidak ada defisit; tidak ada PO yang perlu dibuat": "No shortfall; no POs need to be created",
    "Tidak ada jadwal produksi PLANNED pada rentang tanggal tersebut": "No PLANNED production schedules in that date range",
    "Versi PO tidak ditemukan": "PO version not found",
    "order_qty harus ≥ defisit dan ≥ MOQ supplier": "order_qty must be ≥ the shortfall and ≥ the supplier's MOQ",
    "stok, PO, atau harga berubah sejak usulan dibuat; kirim ulang permintaannya":
        "stock, POs or prices changed since the proposal was made; send the request again",
    # ---- master data: form, validation, card, result (configs/tools/master_actions.py)
    "Produk final baru": "New finished product", "Material beli baru": "New purchased material", "Supplier baru": "New supplier",
    "Tinjau & lanjutkan": "Review & continue", "Konfirmasi & simpan": "Confirm & save",
    "Wajib diisi": "Required", "Harus berupa bilangan bulat": "Must be a whole number", "Harus berupa angka": "Must be a number",
    "Material tidak ditemukan": "Material not found", "Komponen ini sudah ada di baris lain": "This component is already on another row",
    "Pilih material atau tambah material baru": "Select a material or add a new one",
    "Supplier ini sudah ada di baris lain": "This supplier is already on another row",
    "Pilih supplier atau tambah supplier baru": "Select a supplier or add a new one",
    "Material ini sudah ada di baris lain": "This material is already on another row",
    "Supplier tidak ditemukan atau tidak aktif": "Supplier not found or inactive",
    "Jenis data tidak dikenal": "Unknown data type",
    "Produk belum punya BOM, jadi belum bisa dijadwalkan produksi. Tambahkan komponen di halaman BOM.":
        "The product has no BOM yet, so it cannot be scheduled. Add components on the BOM page.",
    "Supplier belum terhubung ke material apa pun.": "The supplier is not linked to any material yet.",
    "Produk final": "Finished product", "Material beli baru ": "New purchased material", "Komponen BOM (per 1 unit produk)": "BOM components (per 1 product unit)",
    "Relasi material–supplier": "Material–supplier links",
    "SKU": "SKU", "Nama": "Name", "Satuan": "Unit", "Harga jual": "Selling price", "Spesifikasi": "Specification",
    "Stok awal": "Initial stock", "Safety stock": "Safety stock", "Kode": "Code", "Kontak": "Contact", "Termin": "Payment term",
    "Komponen": "Component", "Qty": "Qty", "Material": "Material", "Supplier": "Supplier", "Harga": "Price",
    "Lead time": "Lead time", "MOQ": "MOQ", "Preferred": "Preferred", "Ya": "Yes", "Subtotal": "Subtotal", "Dibutuhkan": "Needed by",
    "Kebutuhan": "Requirement", "Tersedia": "Available", "Masuk tepat waktu": "Arriving in time",
    "Kurang (ke batas aman)": "Short (to safety stock)", "Status tanpa PO baru": "Status without new PO",
    "Lihat di halaman Produk Final": "View on the Finished products page", "Lihat di halaman Material Beli": "View on the Purchased materials page",
    "Lihat di halaman Supplier": "View on the Suppliers page", "Lihat BOM": "View BOM", "Lihat material baru": "View new materials",
    "Lihat supplier baru": "View new suppliers",
    # ---- master data chat texts (configs/workflows/master_data_graph.py)
    "Data apa yang ingin Anda tambahkan?": "What data would you like to add?",
    "Masih ada isian yang perlu diperbaiki (ditandai merah). Periksa lalu kirim lagi.":
        "Some fields still need fixing (marked in red). Check them and submit again.",
    "Periksa data berikut. Belum ada yang disimpan sampai Anda menekan konfirmasi:":
        "Please check the data below. Nothing is saved until you press confirm:",
    "Baik, penambahan data dibatalkan. Tidak ada data yang disimpan.": "OK, adding the data was cancelled. Nothing was saved.",
    "Baik, data tidak disimpan.": "OK, the data was not saved.",
    "Usulan ini sudah kedaluwarsa. Silakan kirim ulang permintaannya.": "This proposal has expired. Please send the request again.",
    "produk final baru": "new finished product", "material beli baru": "new purchased material",
    "supplier baru": "new supplier",
    "tambahkan Rantai Sepeda 1 buah": "add 1 Rantai Sepeda", "dari SUP-ASN harga 25 ribu, lead time 3 hari": "from SUP-ASN at 25k, lead time 3 days",
    "dia juga memasok Ban Dalam Karet harga 15 ribu": "they also supply Ban Dalam Karet at 15k",
    "Produk final baru ": "New finished product", "Saya ingin membuat produk final baru": "I want to create a new finished product",
    "Saya ingin menambah material beli baru": "I want to add a new purchased material",
    "Saya ingin mendaftarkan supplier baru": "I want to register a new supplier",
    # ---- PO automation cards (configs/workflows/automation_graph.py)
    "Jadwal produksi & PO": "Production schedule & PO",
    "Jadwal pembayaran": "Payment schedule", "Jumlah": "Amount", "Perkiraan tiba": "Expected arrival",
    "Bayar paling lambat": "Pay by", "Total yang harus dibayar": "Total to pay", "Tunai": "Cash", "No. PO": "PO no.",
    "Total": "Total", "Konfirmasi jadwal & PO": "Confirm schedule & PO",
    "Buat & terbitkan PO": "Create & issue PO", "Konfirmasi & terbitkan": "Confirm & issue",
    "Konfirmasi perubahan": "Confirm change", "Konfirmasi hapus": "Confirm delete",
    "Langsung dihapus (belum dikirim ke supplier).": "Deleted right away (not sent to the supplier yet).",
    "Minta persetujuan pembatalan ke supplier via Telegram, lalu batalkan (tetap tersimpan).":
        "Ask the supplier on Telegram to agree to the cancellation, then cancel (kept on record).",
    # ---- Agent Hub (missions, approvals, threads, settings)
    "Item persetujuan tidak ditemukan": "Approval item not found",
    "Item sudah diputuskan": "This item has already been decided",
    "Item sudah kedaluwarsa. Buat misi baru untuk meminta data terbaru.": "This item has expired. Create a new mission to request fresh data.",
    "Alasan/catatan wajib diisi (min. 3 karakter)": "A reason/note is required (min. 3 characters)",
    "Data berubah sejak diajukan. Muat ulang kartu.": "The data changed since it was submitted. Reload the card.",
    "Pilih minimal satu baris untuk disetujui": "Select at least one row to approve",
    "PO sudah dihapus": "The PO has already been deleted",
    "Misi tidak ditemukan": "Mission not found",
    "Tenggat harus di masa depan": "The deadline must be in the future",
    "Otonomi harus AUTO atau REVIEW": "Autonomy must be AUTO or REVIEW",
    "Pilih minimal satu supplier": "Select at least one supplier",
    "Pilih minimal satu item PO": "Select at least one PO item",
    "Pilih minimal satu material": "Select at least one material",
    "Misi sudah ditutup": "The mission is already closed",
    "Misi PO dijalankan agent PO (pengingat & eskalasi otomatis). Buka percakapan supplier untuk mengambil alih.": "PO missions are run by the PO agent (automatic reminders & escalation). Open the supplier conversation to take over.",
    "Skenario misi tidak dikenal": "Unknown mission scenario",
    "Material beli tidak ditemukan": "Purchased material not found",
    "Agent sedang dijeda. Lanjutkan Agent untuk mengirim pengingat.": "The agent is paused. Resume the agent to send reminders.",
    "Supplier tidak ada di misi ini": "The supplier is not part of this mission",
    "File maksimal 10 MB": "Files can be at most 10 MB",
    "Lampiran tidak ditemukan": "Attachment not found",
    "File tidak tersimpan (terlalu besar atau gagal diunduh). Minta ulang ke supplier.": "The file was not stored (too large or the download failed). Ask the supplier to send it again.",
    "content_base64 tidak valid": "content_base64 is not valid",
    "Supplier belum terhubung ke Telegram": "The supplier is not connected to Telegram yet",
    "Ambil alih percakapan dulu sebelum mengirim pesan manual": "Take over the conversation before sending a manual message",
    "Draf tidak ditemukan": "Draft not found",
    "Draf sudah diproses": "The draft has already been processed",
    "Agent sedang dijeda. Lanjutkan Agent untuk mengirim pesan.": "The agent is paused. Resume the agent to send messages.",
    "Pesan terlalu pendek": "The message is too short",
    "Hanya pesan keluar yang gagal yang dapat dikirim ulang": "Only failed outgoing messages can be resent",
    "Nama approver minimal 2 karakter": "The approver name must be at least 2 characters",
    "Daftar skenario tidak lengkap": "The scenario list is incomplete",
    "Batas pembatalan otomatis harus lebih besar dari toleransi harga": "The automatic cancellation limit must be greater than the price tolerance",
    "Eskalasi harus lebih lama dari pengingat": "Escalation must come later than the reminder",
    "Pilih minimal satu hari kerja": "Select at least one working day",
    "Jam selesai harus setelah jam mulai (format HH:MM)": "The end time must be after the start time (format HH:MM)",
    "Batas toleransi harga maksimal 100%": "The price tolerance can be at most 100%",
    "Batas pembatalan otomatis maksimal 1000%": "The automatic cancellation limit can be at most 1000%",
    "Tombol tidak dikenal": "Unknown button",
    "Agent belum dikonfigurasi: isi AICORE_* di backend/.env untuk menafsirkan balasan manajer.": "The agent is not configured: fill in AICORE_* in backend/.env to interpret manager replies.",
    "Aktivitas tidak ditemukan": "Activity not found",
    "Revisi PO diputuskan dengan memilih opsi (POST /approvals/cr-{id}/choose)": "PO revisions are decided by choosing an option (POST /approvals/cr-{id}/choose)",
    "Supplier belum ditautkan ke chat sandbox (POST /links/{id}/sandbox)": "The supplier is not linked to the sandbox chat yet (POST /links/{id}/sandbox)",
    "Misi tidak ditemukan.": "Mission not found.",
    # ---- Agent Hub views (titles, summaries, chips, policies, audit)
    "Menunggu giliran pengiriman ke supplier.": "Waiting for its turn to be sent to the supplier.",
    "Agent dijeda": "Agent paused",
    "Menunggu percakapan PO selesai": "Waiting for the PO conversation to finish",
    "Telegram belum terhubung": "Telegram not connected yet",
    "Menunggu misi lain dengan supplier ini": "Waiting for another mission with this supplier",
    "Di luar jam kerja": "Outside working hours",
    "Menunggu percakapan PO lain dengan supplier ini selesai": "Waiting for another PO conversation with this supplier to finish",
    "Percakapan agent PO untuk PO ini masih berjalan (lihat misinya)": "The PO agent's conversation for this PO is still running (see its mission)",
    "Percakapan Telegram untuk PO supplier ini masih berjalan": "A Telegram PO conversation with this supplier is still running",
    "Misi diatur \"Draf dulu\"": "Mission set to \"Draft first\"",
    "Pengingat diatur \"Draf dulu\"": "Reminder set to \"Draft first\"",
    "Eskalasi selalu perlu review": "Escalations always need review",
    "Menolak": "Declined",
    "Dibalas": "Replied",
    "Konfirmasi": "Confirmed",
    "Minta revisi": "Revision requested",
    "Pertanyaan": "Question",
    "Belum jelas": "Unclear",
    "Menjawab": "Answered",
    "pembatalan disetujui": "cancellation approved",
    "Centang baris yang ingin diterapkan ke master harga material-supplier.": "Tick the rows to apply to the material-supplier price master.",
    "Menyetujui hanya mencatat hasil; PO dan master tidak berubah.": "Approving only records the result; the PO and master data do not change.",
    "Di luar batas hari agent; menyetujui memperbarui tanggal kirim dan merevisi PO.": "Outside the agent's day limits; approving updates the delivery date and revises the PO.",
    "Terima, ajukan harga nego, cari supplier lebih murah, atau batalkan PO.": "Accept, offer a counter price, find a cheaper supplier, or cancel the PO.",
    "Pengganti di luar batas agent (terlambat / lebih mahal) atau tidak ada; putuskan kelanjutan proyek.": "Replacements are outside the agent's limits (late / more expensive) or there are none; decide how the project continues.",
    "Disetujui otomatis oleh agent (di dalam batas).": "Approved automatically by the agent (within limits).",
    "Pilih salah satu opsi; keputusan berlaku sama seperti tombol di Telegram manajer.": "Choose one option; the decision works the same as the buttons in the manager's Telegram.",
    "PO hanya berubah bila Anda memilih opsi.": "The PO only changes if you choose an option.",
    "Opsi dihitung oleh sistem, bukan oleh AI.": "Options are calculated by the system, not by AI.",
    "PO yang sudah ada tidak diubah; harga baru dipakai untuk PO berikutnya.": "Existing POs are not changed; the new price is used for the next POs.",
    "PO final (PDF) terkirim.": "Final PO (PDF) sent.",
    "lihat Chat Manajer": "see Manager Chat",
    "PO dibatalkan oleh supplier.": "The PO was cancelled by the supplier.",
    "PO dibatalkan agent: harga dari supplier tidak wajar (di luar batas pembatalan).": "The agent cancelled the PO: the supplier's price was unreasonable (beyond the cancellation limit).",
    "PO dibatalkan manajer.": "The manager cancelled the PO.",
    "PO dialihkan ke supplier lain.": "The PO was moved to another supplier.",
    "PO berubah / tidak berlaku lagi.": "The PO changed / is no longer valid.",
    "PO dihapus sebelum dikirim.": "The PO was deleted before it was sent.",
    "Diganti permintaan pembatalan PO.": "Replaced by a PO cancellation request.",
    "(pesan disusun agent PO)": "(message written by the PO agent)",
    "Agent dijeda untuk supplier ini.": "The agent is paused for this supplier.",
    "File lebih dari 10 MB; tidak disimpan.": "The file is larger than 10 MB; it was not stored.",
    "Manajer via Telegram": "Manager via Telegram",
    "Tenggat (needed-by)": "Deadline (needed-by)",
    "harga": "price",
    "tanggal": "date",
    "tanggal kirim": "delivery date",
    "Janji kirim": "Promised delivery",
    "Siap": "Ready",
    "Keputusan": "Decision",
    "Ref. supplier": "Supplier ref.",
    "Pesan misi": "Mission messages",
    "Sesuai otonomi misi": "Per mission autonomy",
    "Pesan bebas": "Free-text messages",
    "Perubahan data": "Data changes",
    "Kirim langsung (setelah ambil alih)": "Sent directly (after takeover)",
    "Otomatis (konfirmasi & revisi)": "Automatic (confirmation & revision)",
    "Selalu perlu persetujuan": "Always needs approval",
    "Konfirmasi & revisi PO (agent PO)": "PO confirmation & revision (PO agent)",
    "Cek ketersediaan stok": "Stock availability check",
    "Pengingat misi": "Mission reminder",
    "Pesan bebas admin": "Admin free-text message",
    "Eskalasi": "Escalation",
    "Harga material-supplier": "Material-supplier price",
    "Hasil cek stok": "Stock check result",
    "Tanggal janji kirim PO": "PO promised delivery date",
    "Tanggal kirim & harga mengikuti Batas keputusan otomatis agent; di luar batas -> manajer": "Delivery dates & prices follow the agent's automatic decision limits; outside the limits -> manager",
    "Dikirim langsung setelah Anda mengambil alih thread": "Sent directly after you take over the thread",
    "konfirmasi": "confirmation",
    "persetujuan pembatalan": "cancellation approval",
    # ---- Activity log action labels (same English as frontend/src/i18n/en.js)
    "Memutuskan permintaan supplier": "Decided a supplier request",
    "Menyetujui ajuan": "Approved a request",
    "Menolak ajuan": "Rejected a request",
    "Minta revisi ajuan": "Asked to revise a request",
    "Menyetujui usulan chat": "Approved a chat proposal",
    "Menolak usulan chat": "Rejected a chat proposal",
    "Mengubah aturan otonomi": "Changed autonomy rules",
    "Menjeda agent": "Paused the agent",
    "Melanjutkan agent": "Resumed the agent",
    "Mengambil alih percakapan": "Took over a conversation",
    "Menyerahkan ke agent": "Handed back to the agent",
    "Mengirim draf": "Sent a draft",
    "Membuang draf": "Discarded a draft",
    "Mengirim pesan manual": "Sent a manual message",
    "Mengirim pengingat": "Sent a reminder",
    "Menandai eskalasi": "Marked an escalation",
    "Menutup misi": "Closed a mission",
    "Membatalkan misi": "Cancelled a mission",
    "Mengundang supplier": "Invited a supplier",
    "Menautkan sandbox": "Linked sandbox",
    "Memulai percakapan PO": "Started a PO conversation",
    "Menekan tombol manajer": "Pressed a manager button",
    "Membuat misi": "Created a mission",
    "Misi selesai": "Mission done",
    "Misi berhenti": "Mission stopped",
    "Menerima tanggal kirim (dalam batas)": "Accepted delivery date (within limits)",
    "Menerima harga (dalam batas)": "Accepted price (within limits)",
    "Membatalkan PO (harga tidak wajar)": "Cancelled PO (unreasonable price)",
    "Tanggal kirim ke manajer": "Delivery date to manager",
    "Perubahan PO ke manajer": "PO change to manager",
    "Pembatalan ke manajer": "Cancellation to manager",
    "PO dibatalkan supplier": "PO cancelled by supplier",
    "Pembatalan sebagian ke manajer": "Partial cancellation to manager",
    "Menerbitkan PO pengganti": "Issued a replacement PO",
    "PO dikonfirmasi supplier": "PO confirmed by supplier",
    "PO ditolak supplier": "PO declined by supplier",
    "Guardrail menolak pesan": "Guardrail rejected a message",
    "Guardrail memberi tahu manajer": "Guardrail alerted the manager",
}

PATTERNS = [(re.compile(p), en) for p, en in [
    # REST errors with values
    (r"^Field '(.+)' tidak boleh null$", "Field '{0}' cannot be null"),
    (r"^Item child id=(\d+) akan menyebabkan siklus BOM$", "Child item id={0} would create a BOM cycle"),
    (r"^Jadwal berstatus (\S+) tidak dapat diubah$", "A schedule with status {0} cannot be changed"),
    (r"^Kode supplier '(.+)' sudah terdaftar$", "Supplier code '{0}' is already registered"),
    (r"^SKU '(.+)' sudah terdaftar$", "SKU '{0}' is already registered"),
    (r"^(Material|Supplier|Parent|Child|Sub-part|Produk final) id=(\d+) tidak ditemukan$", "{0} id={1} not found"),
    (r"^PO berstatus (\S+) tidak dapat diedit$", "A PO with status {0} cannot be edited"),
    (r"^PO berstatus (\S+) tidak dapat menerima barang$", "A PO with status {0} cannot receive goods"),
    (r"^PO (\S+) berstatus (\S+); revisi hanya untuk PO ISSUED tanpa penerimaan$",
     "PO {0} has status {1}; revisions are only for ISSUED POs without receipts"),
    (r"^PO (\S+) berubah sejak usulan dibuat; ulangi permintaan$", "PO {0} changed since the proposal was made; repeat the request"),
    (r"^PO (\S+) sudah menerima barang \((\S+)\); tidak dapat dibatalkan$", "PO {0} already received goods ({1}); it cannot be cancelled"),
    (r"^PO (\S+) sudah menerima barang \((\S+)\); tidak dapat dihapus$", "PO {0} already received goods ({1}); it cannot be deleted"),
    (r"^PO (\S+) tidak lagi ISSUED$", "PO {0} is no longer ISSUED"),
    (r"^Perubahan tidak valid: (.+)$", "Invalid change: {0}"),
    (r"^Qty penerimaan tidak valid \(melebihi sisa\) untuk item (\S+)$", "Invalid received qty (exceeds the remainder) for item {0}"),
    (r"^Siklus BOM terdeteksi pada material id=(\d+)$", "BOM cycle detected at material id={0}"),
    (r"^Sub-assembly id=(\d+) \(MAKE\) belum memiliki BOM$", "Sub-assembly id={0} (MAKE) has no BOM yet"),
    (r"^Supplier belum dipilih untuk: (.+)$", "No supplier chosen yet for: {0}"),
    (r"^Transisi (\S+) → (\S+) tidak valid untuk PO (\S+)$", "Transition {0} → {1} is not valid for a {2} PO"),
    (r"^Transisi (\S+) → (\S+) tidak valid$", "Transition {0} → {1} is not valid"),
    (r"^po_item_id=(\S+) bukan bagian dari PO ini$", "po_item_id={0} is not part of this PO"),
    (r"^(.+): harga tidak boleh negatif$", "{0}: price cannot be negative"),
    (r"^(.+): qty harus > 0$", "{0}: qty must be > 0"),
    (r"^(.+): tanggal kebutuhan tidak boleh sebelum tanggal PO$", "{0}: needed-by date cannot be before the PO date"),
    (r"^(.+): hanya material beli yang aktif dari master yang dapat dipesan$", "{0}: only active purchased materials from the master can be ordered"),
    (r"^Data berubah sejak usulan dibuat: (.+)$", "Data changed since the proposal was made: {0!}"),
    # Agent Hub errors with values
    (r"^Permintaan revisi #(\d+) sudah diproses \((\S+)\)$", "Revision request #{0} was already processed ({1})"),
    (r"^Opsi '(.+)' tidak tersedia untuk permintaan revisi #(\d+)$", "Option '{0}' is not available for revision request #{1}"),
    (r"^Harga (.+) berubah sejak diajukan \(sekarang (.+)\)\. Tolak kartu ini lalu buat misi baru\.$", "The price of {0} changed since it was submitted (now {1}). Reject this card and create a new mission."),
    (r"^Harga baru (.+) tidak valid$", "The new price for {0} is not valid"),
    (r"^Skenario (.+) tidak berlaku untuk PO berstatus (\S+)$", "Scenario {0!} does not apply to a PO with status {1}"),
    (r"^(.+) harus dibuat dari PO$", "{0!} must be created from a PO"),
    (r"^Supplier (.+) tidak ditemukan$", "Supplier {0} not found"),
    (r"^(.+) hanya dikirim ke supplier PO \((.+)\)$", "{0!} is only sent to the PO's supplier ({1})"),
    (r"^Percakapan Telegram untuk PO (.+) masih berjalan\. Tunggu sampai selesai agar balasan supplier tidak tertukar\.$", "A Telegram PO conversation with {0} is still running. Wait until it finishes so the supplier's replies are not mixed up."),
    (r"^Qty (.+) harus lebih dari 0$", "Qty of {0} must be more than 0"),
    (r"^Percakapan sudah diambil alih oleh (.+)$", "The conversation has already been taken over by {0}"),
    (r"^Pengiriman ulang gagal: (.+)$", "Resending failed: {0}"),
    (r"^Format waktu tidak valid: (.+)$", "Invalid time format: {0}"),
    (r"^Ambang (\S+) wajib angka \u2265 0$", "Threshold {0} must be a number ≥ 0"),
    (r"^Batas hari (\S+) harus bilangan bulat 0\u2013365$", "Day limit {0} must be a whole number 0–365"),
    (r"^Otonomi (\S+) harus AUTO atau REVIEW$", "Autonomy for {0} must be AUTO or REVIEW"),
    (r"^Batas keputusan (\S+) harus 1\u2013168 jam$", "Decision limit {0} must be 1–168 hours"),
    (r"^Konfirmasi ini sudah tidak berlaku untuk revisi #(\d+)$", "This confirmation is no longer valid for revision #{0}"),
    (r"^Tidak ada pilihan yang menunggu konfirmasi untuk revisi #(\d+)$", "No choice is waiting for confirmation for revision #{0}"),
    (r"^Hanya PO ISSUED yang dapat dikonfirmasi/dibatalkan via supplier \(status (\S+)\)$", "Only ISSUED POs can be confirmed/cancelled via the supplier (status {0})"),
    (r"^Percakapan untuk (\S+) masih berjalan$", "The conversation for {0} is still running"),
    (r"^(Material|Supplier|Parent|Child|Sub-part|Produk final|Production line|Jadwal|Purchase Order|PO|Planning run) id=(\d+) tidak ditemukan$", "{0!} id={1} not found"),
    (r"^Penawaran harga$", "Price quote"),
    (r"^Cek stok$", "Stock check"),
    (r"^Konfirmasi jadwal kirim$", "Delivery confirmation"),
    (r"^Konfirmasi PO$", "PO confirmation"),
    (r"^Pembatalan PO$", "PO cancellation"),
    # master-data validation (FRIENDLY in master_actions)
    (r"^Wajib diisi \(minimal (\d+) karakter\)$", "Required (at least {0} characters)"),
    (r"^Maksimal (\S+) karakter$", "At most {0} characters"),
    (r"^Minimal (\S+)$", "At least {0}"),
    (r"^Harus lebih dari (\S+)$", "Must be more than {0}"),
    (r"^Maksimal (\S+)$", "At most {0}"),
    (r"^Maksimal (\d+) baris$", "At most {0} rows"),
    (r"^SKU '(.+)' dipakai lebih dari sekali di formulir ini$", "SKU '{0}' is used more than once in this form"),
    (r"^Kode '(.+)' dipakai lebih dari sekali di formulir ini$", "Code '{0}' is used more than once in this form"),
    (r"^(\S+) tidak aktif$", "{0} is inactive"),
    (r"^(\S+) bukan material beli$", "{0} is not a purchased material"),
    (r"^'(.+)' cocok dengan beberapa (material|supplier) \((.+)\)\. Pilih salah satu\.$", "'{0}' matches several {1}s ({2}). Choose one."),
    (r"^Material baru tanpa supplier \((.+)\) belum bisa dibuatkan PO\. Hubungkan supplier di halaman Material\.$",
     "New materials without a supplier ({0}) cannot be ordered yet. Link a supplier on the Materials page."),
    (r"^Silakan lengkapi formulir (.+) berikut\. Kolom bertanda \* wajib diisi\. Anda juga bisa mengetik perubahannya di chat \(mis\. \"(.+)\"\)\.$",
     "Please complete the {0!} form below. Fields marked * are required. You can also type changes in the chat (e.g. \"{1!}\")."),
    (r"^Data gagal disimpan: (.+)\. Tidak ada data yang berubah; ketik perbaikannya untuk membuka formulir lagi\.$",
     "Saving failed: {0!}. Nothing was changed; type a correction to open the form again."),
    (r"^Simpan (.+): (.+)$", "Save {0!}: {1}"),
    (r"^Akan dibuat dalam satu transaksi: (.+)\.$", "Will be created in one transaction: {0!}."),
    (r"^(\d+) material baru$", "{0} new materials"), (r"^(\d+) supplier baru$", "{0} new suppliers"),
    (r"^(\d+) komponen BOM$", "{0} BOM components"), (r"^(\d+) relasi supplier$", "{0} supplier links"),
    (r"^(\d+) relasi material–supplier$", "{0} material–supplier links"), (r"^(\d+) material baru lain$", "{0} other new materials"),
    (r"^data utama saja$", "main data only"),
    (r"^(Produk final baru|Material beli baru|Supplier baru) (.+) berhasil disimpan\.(?: Ikut dibuat: (.+)\.)?$",
     "{0!} {1} was saved.{2? Also created: !.}"),
    (r"^(.+) \(baru\)$", "{0} (new)"),
    (r"^Net (\d+)$", "Net {0}"), (r"^(\d+) hari$", "{0} days"),
    # PO automation cards
    (r"^Buat & terbitkan PO \((\d+) supplier\)$", "Create & issue PO ({0} suppliers)"),
    (r"^Ubah (\S+)$", "Change {0}"), (r"^Hapus (\S+)$", "Delete {0}"),
    (r"^Total (.+)\. Supplier dihubungi via Telegram setelah dikonfirmasi\.$", "Total {0}. The supplier is contacted on Telegram after confirmation."),
    (r"^Total (.+) → (.+)\.$", "Total {0} → {1}."),
    (r"^Jadwal baru: (.+) pada (\S+); (\d+) PO ke (\d+) supplier, total (.+)\. Supplier dihubungi via Telegram setelah dikonfirmasi\.$",
     "New schedule: {0} on {1}; {2} POs to {3} suppliers, total {4}. Suppliers are contacted on Telegram after confirmation."),
    (r"^Jadwal baru: (.+) pada (\S+); material cukup, tanpa PO baru\.$", "New schedule: {0} on {1}; enough material, no new PO."),
    (r"^(.+) · Net (\d+) · total (.+?)( · (\d+) material dalam 1 PO)?$", "{0} · Net {1} · total {2}{4? · ! materials in 1 PO}"),
    (r"^Cek material untuk (.+) · siap (\S+)$", "Material check for {0} · ready {1}"),
    (r"^(\S+) setelah perubahan · total (.+) → (.+)$", "{0} after the change · total {1} → {2}"),
    (r"^(.+): (.+) paling cepat tiba (\S+) \(setelah (\S+)\)$", "{0}: {1} arrives {2} at the earliest (after {3})"),
    (r"^(.+): qty (\S+) di bawah MOQ (\S+) (.+)$", "{0}: qty {1} is below the MOQ {2} of {3}"),
    (r"^Material digabung per supplier: \+(.+) dibanding pemasok termurah per material, hemat (\d+) PO\.$",
     "Materials grouped per supplier: +{0} compared with the cheapest supplier per material, saving {1} PO(s)."),
    (r"^Material digabung per supplier: hemat (\d+) PO\.$", "Materials grouped per supplier: saving {0} PO(s)."),
    # Agent Hub views (titles, summaries, chips, audit, thread SYSTEM lines)
    (r"^(.+) \((supplier|mission|po|proposal|change_request|hub|thread|outbox|message) #(\S+)\)$", "{0!} ({1} #{2})"),
    (r"^(Penawaran harga|Cek stok|Konfirmasi jadwal kirim) (.+)$", "{0!} {1}"),
    (r"^Konfirmasi PO (\S+)$", "PO confirmation {0}"),
    (r"^Pembatalan PO (\S+)$", "PO cancellation {0}"),
    (r"^Update harga (.+)$", "Price update {0}"),
    (r"^Konfirmasi stok (.+)$", "Stock confirmation {0}"),
    (r"^Jadwal kirim (\S+)$", "Delivery schedule {0}"),
    (r"^Janji kirim (\S+)$", "Promised delivery {0}"),
    (r"^Revisi (\S+)$", "Revision {0}"),
    (r"^Harga naik (\S+)$", "Price increase {0}"),
    (r"^Tanggal kirim (\S+)$", "Delivery date {0}"),
    (r"^Pembatalan (\S+)$", "Cancellation {0}"),
    (r"^(\d+) dari (\d+) supplier menjawab(?:, (\d+) menolak)?\.$", "{0} of {1} suppliers replied{2?, ! declined}."),
    (r"^Penawaran terendah: (.+) (Rp[\d.]+) untuk (.+)\.$", "Lowest quote: {0} {1} for {2}."),
    (r"^Jadwal kirim (\S+) diterima agent \(dalam batas\) dan PO direvisi ke versi (\d+)\.$", "Delivery date {0} was accepted by the agent (within limits) and the PO was revised to version {1}."),
    (r"^Jadwal kirim (\S+) di luar batas agent; menunggu persetujuan\.$", "Delivery date {0} is outside the agent's limits; awaiting approval."),
    (r"^Jadwal sesuai \((\S+)\)\.$", "Schedule on track ({0})."),
    (r"^Agent meminta penawaran ke (\d+) supplier \(Misi #(\d+)\)\.$", "The agent requested quotes from {0} suppliers (Mission #{1})."),
    (r"^Hasil cek stok Misi #(\d+)\.$", "Stock check results for Mission #{0}."),
    (r"^(.+) mengabarkan jadwal kirim (.+)\.$", "{0} reported a delivery date of {1}."),
    (r"^Tanggal kirim (\S+) dari Misi #(\d+) diterima agent: (.+)$", "Delivery date for {0} from Mission #{1} accepted by the agent: {2}"),
    (r"^Dibatalkan oleh (.+)\.$", "Cancelled by {0}."),
    (r"^Ditutup manual oleh (.+); percakapan PO tetap berjalan\.$", "Closed manually by {0}; the PO conversation keeps running."),
    (r"^Agent akan menghubungi (.+) untuk (konfirmasi|persetujuan pembatalan) (\S+?)(?: \(dibutuhkan mulai (\S+)\))?\.$", "The agent will contact {0} for {1!} of {2}{3? (needed from !)}."),
    (r"^Agent membuka percakapan (.+) (\S+) dengan (.+)\.$", "The agent opened a {0} conversation for {1} with {2}."),
    (r"^Revisi (\S+) disetujui; agent meminta supplier mengonfirmasi versi baru\.$", "Revision of {0} approved; the agent asked the supplier to confirm the new version."),
    (r"^Supplier sudah setuju; agent menunggu data konfirmasi (\S+) yang belum lengkap\.$", "The supplier agreed; the agent is waiting for the missing confirmation data for {0}."),
    (r"^Pesan terkirim; menunggu balasan supplier untuk (\S+)\.$", "Message sent; waiting for the supplier's reply about {0}."),
    (r"^Supplier meminta perubahan (\S+); menunggu keputusan manajer(?: \(Persetujuan (cr-\d+)\))?\.$", "The supplier requested changes to {0}; waiting for the manager's decision{1? (Approval !)}."),
    (r"^(\S+) dikonfirmasi supplier(?:, janji kirim (\S+))?\.$", "{0} confirmed by the supplier{1?, promised delivery !}."),
    (r"^Supplier menyetujui pembatalan; (\S+) dibatalkan\.$", "The supplier agreed to the cancellation; {0} is cancelled."),
    (r"^Supplier menolak (\S+) \((.+)\); diteruskan ke manajer\.$", "The supplier declined {0} ({1!}); forwarded to the manager."),
    (r"^(\S+) dieskalasi \((.+)\); diteruskan ke manajer\.$", "{0} escalated ({1!}); forwarded to the manager."),
    (r"^Percakapan (\S+) ditutup \((.+)\)\.$", "Conversation {0} closed ({1})."),
    (r"^Supplier meminta revisi (\S+) \(total saat ini (.+)\)\.$", "The supplier requested a revision of {0} (current total {1})."),
    (r"^Supplier mengubah harga (\S+) di luar pita harga agent \((.+)\)\.$", "The supplier changed the price of {0} outside the agent's price band ({1})."),
    (r"^Tanggal kirim baru untuk (\S+) di luar batas hari agent: (.*)\.$", "The new delivery date for {0} is outside the agent's day limits: {1}."),
    (r"^Supplier membatalkan (\S+); PO sudah dibatalkan otomatis\.$", "The supplier cancelled {0}; the PO was cancelled automatically."),
    (r"^(\d+) BOM dan (\d+) PO terbuka memakai material ini\.$", "{0} BOMs and {1} open POs use this material."),
    (r"^(.+) \(supplier baru\)$", "{0} (new supplier)"),
    (r"^(.+) \(siap\)$", "{0} (ready)"),
    (r"^(.+) \(tidak valid: (.+)\)$", "{0} (invalid: {1})"),
    (r"^Menolak: (.+)$", "Declined: {0}"),
    (r"^stok (.+)$", "stock {0}"),
    (r"^siap (.+)$", "ready {0}"),
    (r"^janji kirim (.+)$", "promised delivery {0}"),
    (r"^Misi #(\d+) dibuat: (.+?)(?: — agent menghubungi (.+) setelah misi tercatat)?$", "Mission #{0} created: {1!}{2? — the agent contacts ! once the mission is recorded}"),
    (r"^Misi #(\d+) dibatalkan$", "Mission #{0} cancelled"),
    (r"^Misi #(\d+) ditutup & dirangkum$", "Mission #{0} closed & summarized"),
    (r"^Misi #(\d+) ditutup manual$", "Mission #{0} closed manually"),
    (r"^Pengingat Misi #(\d+) ke (\d+) supplier$", "Reminder for Mission #{0} to {1} suppliers"),
    (r"^Eskalasi Misi #(\d+): (.+) belum membalas$", "Escalation for Mission #{0}: {1} has not replied"),
    (r"^Menolak (.+?): (.+)$", "Rejected {0!}: {1}"),
    (r"^Minta revisi (.+?): (.+)$", "Requested a revision of {0!}: {1}"),
    (r"^Menyetujui (.+)$", "Approved {0!}"),
    (r"^(.+) untuk ((?:Revisi|Harga naik|Tanggal kirim|Pembatalan) \S+)$", "{0} for {1!}"),
    (r"^Misi #(\d+) (.+?): (.+)$", "Mission #{0} {1!}: {2!}"),
    (r"^Usulan chat ditolak: (.+)$", "Chat proposal rejected: {0}"),
    (r"^Usulan chat disetujui: (.+)$", "Chat proposal approved: {0}"),
    (r"^(.+) mengambil alih percakapan\.$", "{0} took over the conversation."),
    (r"^(.+) menyerahkan percakapan kembali ke Agent\.$", "{0} handed the conversation back to the agent."),
    (r"^(.+) membuang draf pesan\.$", "{0} discarded the message draft."),
    (r"^Eskalasi Misi #(\d+) ditandai oleh (.+)\.$", "Escalation for Mission #{0} marked by {1}."),
    (r"^Agent menghubungi manajer: (.*)$", "The agent contacted the manager: {0}"),
    (r"^Harga (\S+)$", "Price {0}"),
    (r"^Stok (\S+)$", "Stock {0}"),
]]


def _fill(template: str, groups: tuple, lang: str) -> str:
    """{0} = value as-is, {0!} = value translated too, {2? text ! text} = optional group (! = the value)."""
    def optional(m):
        g = groups[int(m.group(1))]
        return "" if g is None else m.group(2).replace("!", translate(g, lang))
    out = re.sub(r"\{(\d)\?([^}]*)\}", optional, template)
    out = re.sub(r"\{(\d)!\}", lambda m: translate(groups[int(m.group(1))] or "", lang), out)
    return re.sub(r"\{(\d)\}", lambda m: groups[int(m.group(1))] or "", out)


# Batas kalimat: ". " lalu huruf besar/angka (teks Hub sering menyambung beberapa kalimat jadi satu ringkasan).
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")


def _known(text: str, lang: str) -> str | None:
    """Translation from EXACT / PATTERNS only (None = no entry)."""
    if text in EXACT:
        return EXACT[text]
    for pattern, template in PATTERNS:
        m = pattern.match(text)
        if m:
            return _fill(template, m.groups(), lang)
    return None


def _translate_sentences(parts: list[str], lang: str) -> list[str]:
    """Longest run of "sentences" with an entry first: a name such as "Co., Ltd. (Japan)" is not a sentence end."""
    out, i = [], 0
    while i < len(parts):
        for j in range(len(parts), i, -1):
            known = _known(" ".join(parts[i:j]), lang)
            if known is not None:
                out.append(known)
                i = j
                break
        else:
            out.append(translate(parts[i], lang))
            i += 1
    return out


def translate(text, lang: str | None):
    """English version of an Indonesian user-facing text; anything else is returned unchanged."""
    if lang != "en" or not isinstance(text, str) or not text:
        return text
    core = text.strip()
    if core != text:                                            # potongan kalimat: spasi di tepi dipertahankan
        start = text.index(core) if core else len(text)
        return text[:start] + translate(core, lang) + text[start + len(core):]
    known = _known(text, lang)
    if known is not None:
        return known
    sentences = _SENTENCE.split(text)
    if len(sentences) > 1:                                      # ringkasan berisi beberapa kalimat
        return " ".join(_translate_sentences(sentences, lang))
    if "; " in text:                                            # beberapa pesan digabung
        return "; ".join(translate(part, lang) for part in text.split("; "))
    if " · " in text:                                           # "Rp12.000 · 5 hari", "SKU Nama · harga"
        return " · ".join(translate(part, lang) for part in text.split(" · "))
    if ", " in text and all(re.match(r"^\d+ ", p) for p in text.split(", ")):   # "1 material baru, 2 komponen BOM"
        return ", ".join(translate(part, lang) for part in text.split(", "))
    return text


def translate_table(table: dict, lang: str | None) -> dict:
    """Table block (title, headers, cells) in the user's language."""
    if lang != "en":
        return table
    return {**table, "title": translate(table.get("title"), lang), "columns": [translate(c, lang) for c in table["columns"]],
            "rows": [[translate(c, lang) for c in row] for row in table["rows"]]}


def translate_card(card: dict, lang: str | None) -> dict:
    """Confirmation card (title, detail, button, table titles/headers/cells, warnings) in the user's language."""
    if lang != "en":
        return card
    tables = [{**tbl, "title": translate(tbl.get("title"), lang),
               "columns": [translate(c, lang) for c in tbl.get("columns", [])],
               "rows": [[translate(c, lang) for c in row] for row in tbl.get("rows", [])]}
              for tbl in card.get("tables") or []]
    return {**card, "title": translate(card.get("title"), lang), "detail": translate(card.get("detail"), lang),
            "approveLabel": translate(card.get("approveLabel"), lang), "tables": tables,
            "warnings": [translate(w, lang) for w in card.get("warnings") or []]}


def translate_blocks(blocks: list[dict], lang: str | None) -> list[dict]:
    """Text / link / form / option blocks of a chat reply in the user's language."""
    if lang != "en":
        return blocks
    out = []
    for b in blocks:
        b = dict(b)
        if b.get("type") in ("text", "notice"):
            b["text"] = translate(b.get("text"), lang)
        elif b.get("type") == "link":
            b["label"] = translate(b.get("label"), lang)
        elif b.get("type") == "options":
            b["options"] = [{**o, "label": translate(o["label"], lang), "value": translate(o["value"], lang)}
                            for o in b.get("options") or []]
        elif b.get("type") == "form":
            b.update(title=translate(b.get("title"), lang), submitLabel=translate(b.get("submitLabel"), lang),
                     errors={k: translate(v, lang) for k, v in (b.get("errors") or {}).items()})
        out.append(b)
    return out


# Fields of Hub / activity JSON that hold display text written by the backend (stored or composed in Indonesian).
# Supplier/manager message bodies (`text`) are never translated, except the Hub's own SYSTEM lines.
VIEW_KEYS = frozenset({"title", "summary", "label", "action_label", "data", "note", "value", "result", "reason",
                       "waiting_reason", "blocked_reason", "review_reason", "decided_by", "decision_note", "effect",
                       "warnings", "detail"})


def translate_view(obj, lang: str | None):
    """Copy of a JSON view with every display field in VIEW_KEYS translated (recursively)."""
    if lang != "en":
        return obj
    if isinstance(obj, list):
        return [translate_view(v, lang) for v in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        if isinstance(v, str) and (k in VIEW_KEYS or (k == "text" and obj.get("from") == "SYSTEM")):
            out[k] = translate(v, lang)
        elif k in VIEW_KEYS and isinstance(v, list) and all(isinstance(x, str) for x in v):
            out[k] = [translate(x, lang) for x in v]
        else:
            out[k] = translate_view(v, lang)
    return out
