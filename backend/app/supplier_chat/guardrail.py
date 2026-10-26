"""Guardrail pesan supplier: menolak upaya "query database", prompt injection, dan kebocoran data.

Lapisan (dari yang termurah):
1. `check_inbound`  — aturan deterministik (regex Indonesia + Inggris) pada SETIAP pesan supplier, sebelum
   triage / agent PO / agent misi melihatnya. Pesan yang diblokir tidak pernah sampai ke LLM.
2. Klasifikasi LLM  — `supplier_inbound_triage` (intent `data_request`) dan `guard_flag` pada
   `supplier_reply_agent` / `mission_reply_agent` untuk variasi yang lolos aturan. Penanganannya sama.
3. `check_outbound` — balasan tulisan LLM diperiksa sebelum dikirim: menyebut supplier lain, PO milik
   supplier lain, atau angka stok -> diganti balasan aman.

Balasan penolakan selalu teks tetap dari kode (tidak pernah ditulis LLM), sesuai jenis serangan.
"""
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PurchaseOrder, Supplier

# Kategori -> perlu memberi tahu manajer (upaya serangan, bukan sekadar salah tanya).
ALERT = {"prompt_injection", "secret_exfiltration", "authority_claim", "sql_injection"}

_I = re.IGNORECASE
_QUESTION = r"(\?|\b(berapa|brp|siapa|apa|apakah|mana|kasih\s*tau|kasih\s*tahu|beri\s*tahu|sebutkan|tunjukkan|tampilkan|" \
            r"minta|tolong|kirim(kan)?|bisa\s+(lihat|kirim|share|bagi)|how\s+(many|much)|what|which|who|tell\s+me|show\s+me|give\s+me|" \
            r"send\s+me|list|share)\b)"

RULES: list[tuple[str, str, re.Pattern]] = [
    # --- membocorkan rahasia sistem ---
    ("secret_exfiltration", "system_prompt", re.compile(
        r"\b(system|sistem)\s*prompt\b|\bprompt\s+(kamu|anda|mu|your|you)\b|\byour\s+(instructions|rules|prompt)\b|"
        r"\binstruksi\s+(kamu|anda|awal|sistem)\b", _I)),
    ("secret_exfiltration", "credentials", re.compile(
        r"\b(api[\s_-]?key|access[\s_-]?token|bot[\s_-]?token|password|kata\s*sandi|credential|kredensial|secret\s*key|"
        r"client[\s_-]?secret|\.env\b|env\s+var|connection\s+string|database\s+url)\b", _I)),
    ("secret_exfiltration", "manager_contact", re.compile(
        r"\b(chat[\s_-]?id|telegram[\s_-]?id)\b|\b(nomor|number|kontak|contact|wa|whatsapp)\s+(manajer|manager|direktur|admin)\b", _I)),
    # --- prompt injection ---
    ("prompt_injection", "override", re.compile(
        r"\b(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+|your\s+)?(previous|prior|above|earlier|system)?\s*"
        r"(instructions?|prompts?|rules?|guidelines?)\b|"
        r"\b(abaikan|lupakan|hiraukan|acuhkan)\s+(semua\s+|seluruh\s+)?(instruksi|perintah|aturan|prompt)\b", _I)),
    ("prompt_injection", "role_play", re.compile(
        r"\b(you\s+are\s+now|from\s+now\s+on\s+you|roleplay|"
        r"kamu\s+sekarang\s+(adalah|jadi)|anda\s+sekarang\s+(adalah|jadi)|berperan\s*(lah)?\s+sebagai|bertindak\s*(lah)?\s+sebagai|"
        r"developer\s+mode|dan\s+mode|jailbreak|mode\s+pengembang|new\s+instructions?|instruksi\s+baru)\b", _I)),
    ("prompt_injection", "act_as", re.compile(
        r"\b(act|behave|respond)\s+as\s+(a|an|my|the|if)?\s*(assistant|ai|admin|manager|system|developer|bot|gpt|chatgpt)\b|"
        r"\bpretend\s+(to\s+be|you\s+are)\b", _I)),
    ("prompt_injection", "fake_role_block", re.compile(
        r"(<\s*/?\s*(system|assistant|user|instruction)s?\s*>|\[\s*(system|inst|assistant)\s*\]|^\s*#{2,}\s*(system|instruction)|"
        r"^\s*(system|assistant)\s*:)", _I | re.MULTILINE)),
    # --- SQL / query database ---
    ("sql_injection", "sql_statement", re.compile(
        r"\bselect\s+(\*|distinct\b|count\s*\(|[\w.]+\s*,\s*[\w.]+)[\s\S]{0,120}?\bfrom\s+\w+|"
        r"\bfrom\s+[\w.]+\s+where\s+[\w.]+\s*(=|<|>|like\b|in\s*\()|\bunion\s+(all\s+)?select\b|"
        r"\binsert\s+into\s+\w+\s*(\(|values\b|select\b)|\bupdate\s+\w+\s+set\s+\w+\s*=|"
        r"\bdelete\s+from\s+\w+\s*(where\b|;|$)|\bdrop\s+(table|database|schema)\b|\btruncate\s+table\b|"
        r"\balter\s+table\b|\bcreate\s+(table|role|user)\b|"
        r"'\s*or\s+'?\d+'?\s*=\s*'?\d+|\bor\s+1\s*=\s*1\b|;\s*--|/\*.*?\*/|\b(pg_sleep|information_schema|pg_catalog)\b", _I)),
    # --- payload tersandi / markup ---
    ("encoded_payload", "encoded", re.compile(
        r"[A-Za-z0-9+/]{80,}={0,2}|\b[0-9a-f]{64,}\b|<\s*script|javascript:|on(error|load)\s*=|[‪-‮⁦-⁩]", _I)),
    # --- mengaku berwenang ---
    ("authority_claim", "claims_authority", re.compile(
        r"\b(saya|aku|ini)\s+(adalah\s+)?(manajer|manager|admin|direktur|owner|pemilik|bos|atasan)\b|"
        r"\b(i\s+am|i'm|im|this\s+is)\s+(the\s+|your\s+)?(manager|admin|director|owner|boss)\b|"
        r"\b(manajer|manager|bos|direktur|atasan)(\s+\w+){0,3}\s+(sudah|telah|already)\s+(setuju|menyetujui|approve[d]?|acc)\b|"
        r"\b(approve|confirm)\s+(it|this|the\s+(po|order|change))\s+yourself\b|\bsetujui\s+(saja|sendiri|langsung)\b", _I)),
]

# Pertanyaan tentang data internal KITA (bukan tentang pesanan supplier itu sendiri).
# Stok supplier SENDIRI ("stok kami tinggal 20") bukan data kita: topik stok wajib merujuk ke "kalian/anda/you".
_STOCK = r"(stok|stock|inventory|inventori|persediaan|gudang|warehouse)"
_YOU = r"(kalian|anda|kamu|you|your)"
DATA_TOPICS = [
    ("our_stock", rf"\b{_STOCK}\s+(\w+\s+){{0,3}}(yang\s+)?{_YOU}\b|\byour\s+{_STOCK}\b|"
                  rf"\b{_YOU}\s+(\w+\s+){{0,5}}(punya|miliki|simpan|have|hold|keep|got)\b[^.?!\n]{{0,40}}\b(in\s+)?{_STOCK}\b"),
    ("other_suppliers", r"\b(supplier|pemasok|vendor)\s+(lain|lainnya|other|others)\b|\b(other|competing)\s+(suppliers?|vendors?)\b|"
                        r"\b(kompetitor|competitor|pesaing)\b"),
    ("costs_margins", r"\b(margin|markup|hpp|harga\s+pokok|cost\s+price|profit|keuntungan|laba|budget|anggaran)\b"),
    ("customers", rf"\b(pelanggan|customer|klien|client|pembeli)\s+{_YOU}\b|\byour\s+(customers?|clients?)\b"),
    ("production", r"\b(jadwal|rencana)\s+produksi\b|\bproduction\s+(schedule|plan)s?\b|\b(bom|bill\s+of\s+materials?)\b"),
    ("bulk_records", r"\b(semua|seluruh|all|export|ekspor|dump)\s+(\w+\s+){0,2}"
                     r"(po|purchase\s+orders?|pesanan|data|records?|supplier|suppliers|pemasok|material|materials|harga|prices?|transaksi)\b"),
    ("database", r"\b(database|basis\s+data|sql|query|kueri)\b"),
]
_DATA = [(name, re.compile(rx, _I)) for name, rx in DATA_TOPICS]
_QUESTION_RX = re.compile(_QUESTION, _I)
_PO_RX = re.compile(r"\bPO-\d{6}-\d{3,5}\b", _I)

REPLIES = {
    "data_query": {
        "id": "Mohon maaf, kami tidak dapat membagikan data internal perusahaan (stok, harga, supplier lain, jadwal "
              "produksi, atau isi sistem) melalui chat ini. Saya hanya dapat membantu terkait pesanan (PO) Anda dengan kami.",
        "en": "Sorry, we cannot share internal company data (stock levels, prices, other suppliers, production plans "
              "or system records) through this chat. I can only help with your own purchase orders with us."},
    "sql_injection": {
        "id": "Mohon maaf, perintah atau kueri database tidak dapat diproses melalui chat ini. Silakan sampaikan hal "
              "terkait pesanan (PO) Anda dengan bahasa biasa.",
        "en": "Sorry, database commands or queries cannot be processed through this chat. Please describe your "
              "purchase-order matter in plain words."},
    "prompt_injection": {
        "id": "Mohon maaf, pesan tersebut tidak dapat kami proses. Chat ini hanya untuk konfirmasi, jadwal kirim, "
              "dan perubahan pesanan (PO) Anda.",
        "en": "Sorry, we cannot process that message. This chat is only for confirming, scheduling and changing your "
              "purchase orders."},
    "secret_exfiltration": {
        "id": "Mohon maaf, informasi sistem, kredensial, atau kontak internal tidak dapat dibagikan. Ada yang bisa "
              "kami bantu terkait pesanan Anda?",
        "en": "Sorry, system information, credentials or internal contacts cannot be shared. Can we help with your order?"},
    "authority_claim": {
        "id": "Terima kasih. Persetujuan dan perubahan PO hanya diproses melalui tim pembelian kami, bukan melalui "
              "pernyataan di chat ini. Bila ada perubahan, mohon sebutkan PO dan detailnya; tim kami akan meninjaunya.",
        "en": "Thank you. Approvals and PO changes are only processed by our purchasing team, not by statements in "
              "this chat. Please state the PO and the change you need; our team will review it."},
    "encoded_payload": {
        "id": "Mohon maaf, pesan berisi kode atau data tersandi tidak dapat diproses. Mohon tulis pesan Anda dalam "
              "bahasa biasa.",
        "en": "Sorry, messages containing code or encoded data cannot be processed. Please write in plain words."},
    "foreign_po": {
        "id": "Mohon maaf, kami hanya dapat membahas PO yang diterbitkan untuk perusahaan Anda. Mohon periksa kembali "
              "nomor PO-nya.",
        "en": "Sorry, we can only discuss purchase orders issued to your company. Please check the PO number."},
    "unsafe_reply": {
        "id": "Terima kasih atas pesannya. Tim pembelian kami akan menindaklanjuti dan menghubungi Anda.",
        "en": "Thank you for your message. Our purchasing team will follow up with you."},
}
_EN_WORDS = re.compile(r"\b(the|you|your|please|how|what|have|do|is|are|we|can|will|order|deliver|thanks|thank)\b", _I)
_ID_WORDS = re.compile(r"\b(yang|dan|kami|kalian|anda|mohon|terima|kasih|bisa|apakah|berapa|tidak|sudah|akan|untuk|pak|bu)\b", _I)


@dataclass
class Verdict:
    category: str            # kunci REPLIES
    rule: str                # aturan yang cocok (atau llm_triage / llm_reply / llm_mission)
    layer: str = "rules"

    @property
    def alert(self) -> bool:
        return self.category in ALERT

    def reply(self, text: str) -> str:
        return REPLIES[self.category][language(text)]

    def as_dict(self) -> dict:
        return {"category": self.category, "rule": self.rule, "layer": self.layer}


def language(text: str) -> str:
    """'en' bila pesan jelas berbahasa Inggris, selain itu 'id' (bahasa default supplier)."""
    return "en" if len(_EN_WORDS.findall(text or "")) > len(_ID_WORDS.findall(text or "")) else "id"


def own_po_numbers(db: Session, supplier_id: int) -> set[str]:
    return {n.upper() for n in db.scalars(select(PurchaseOrder.po_number).where(PurchaseOrder.supplier_id == supplier_id))}


def check_inbound(text: str, own_pos: set[str] | None = None) -> Verdict | None:
    """Aturan deterministik; None = aman diteruskan ke agent."""
    t = (text or "").strip()
    if not t:
        return None
    for category, rule, rx in RULES:
        if rx.search(t):
            return Verdict(category, rule)
    if own_pos is not None:
        foreign = {m.upper() for m in _PO_RX.findall(t)} - own_pos
        if foreign:
            return Verdict("foreign_po", "po_not_owned")
    if _QUESTION_RX.search(t):
        for name, rx in _DATA:
            if rx.search(t):
                return Verdict("data_query", name)
    return None


def from_llm(flag: str | None, layer: str) -> Verdict | None:
    """`guard_flag` / intent dari agent LLM -> Verdict (lapisan kedua)."""
    if flag in (None, "", "none"):
        return None
    return Verdict("prompt_injection" if flag == "prompt_injection" else "data_query", flag, layer)


# ------------------------------------------- output -------------------------------------------
_STOCK_FIGURE = re.compile(r"\b(stok|stock|inventory|persediaan|on[\s-]?hand)\b[^.\n]{0,30}\d", _I)


def check_outbound(db: Session, supplier_id: int, text: str) -> str | None:
    """Alasan bila balasan LLM untuk supplier ini membocorkan data; None = aman dikirim."""
    t = text or ""
    names = [n for n in db.scalars(select(Supplier.name).where(Supplier.id != supplier_id)) if n and len(n) >= 4]
    for n in names:
        if re.search(rf"\b{re.escape(n)}\b", t, _I):
            return "mentions_other_supplier"
    own = own_po_numbers(db, supplier_id)
    if {m.upper() for m in _PO_RX.findall(t)} - own:
        return "mentions_foreign_po"
    if _STOCK_FIGURE.search(t):
        return "mentions_stock_figure"
    return None


def safe_reply(db: Session, supplier_id: int, text: str, supplier_text: str = "") -> tuple[str, str | None]:
    """(teks yang boleh dikirim, alasan blokir atau None)."""
    reason = check_outbound(db, supplier_id, text)
    return (REPLIES["unsafe_reply"][language(supplier_text or text)], reason) if reason else (text, None)
