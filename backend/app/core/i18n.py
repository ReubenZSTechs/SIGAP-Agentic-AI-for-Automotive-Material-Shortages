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
]]


def _fill(template: str, groups: tuple, lang: str) -> str:
    """{0} = value as-is, {0!} = value translated too, {2? text ! text} = optional group (! = the value)."""
    def optional(m):
        g = groups[int(m.group(1))]
        return "" if g is None else m.group(2).replace("!", translate(g, lang))
    out = re.sub(r"\{(\d)\?([^}]*)\}", optional, template)
    out = re.sub(r"\{(\d)!\}", lambda m: translate(groups[int(m.group(1))] or "", lang), out)
    return re.sub(r"\{(\d)\}", lambda m: groups[int(m.group(1))] or "", out)


def translate(text, lang: str | None):
    """English version of an Indonesian user-facing text; anything else is returned unchanged."""
    if lang != "en" or not isinstance(text, str) or not text:
        return text
    if text in EXACT:
        return EXACT[text]
    for pattern, template in PATTERNS:
        m = pattern.match(text)
        if m:
            return _fill(template, m.groups(), lang)
    if "; " in text:                                            # beberapa pesan digabung
        return "; ".join(translate(part, lang) for part in text.split("; "))
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
