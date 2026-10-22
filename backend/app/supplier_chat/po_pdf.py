"""PDF of a PO version (sent to the supplier once the final version is confirmed).

Built only from the stored snapshot, so the PDF shows exactly what was agreed. Core PDF fonts
cover Latin-1 only; `_t` replaces anything else (e.g. arrows, em dashes).
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fpdf import FPDF

from configs.tools import po_actions as A

COMPANY = "SIGAP"
COLS = [("No", 10), ("SKU", 26), ("Material", 54), ("Qty", 22), ("Harga", 26), ("Subtotal", 28), ("Dibutuhkan", 24)]  # = 190 mm (A4 - margin)
TZ = ZoneInfo("Asia/Jakarta")


def _t(text) -> str:
    s = str(text if text is not None else "-").replace("—", "-").replace("→", "->")
    return s.encode("latin-1", "replace").decode("latin-1")


def pdf_file_name(po_number: str, version: int) -> str:
    return f"{po_number}-v{version}.pdf"


def render_po_pdf(snapshot: dict, version: int, final: bool = True, finalized_at: datetime | None = None) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, _t(f"{COMPANY} - Purchase Order"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _t(f"{snapshot['po_number']} · versi {version}" + (" · FINAL" if final else "")),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    rows = [("Supplier", f"{snapshot.get('supplier_code', '')} {snapshot['supplier_name']}".strip()),
            ("Tanggal PO", snapshot.get("po_date") or "-"),
            ("Termin", f"Net {snapshot.get('payment_term_days', 0)} hari")]
    if snapshot.get("promised_delivery_date"):
        rows.append(("Janji kirim", snapshot["promised_delivery_date"]))
    if snapshot.get("supplier_reference"):
        rows.append(("Ref. supplier", snapshot["supplier_reference"]))
    if finalized_at:
        local = finalized_at.replace(tzinfo=timezone.utc).astimezone(TZ)      # disimpan sebagai UTC naif
        rows.append(("Dikonfirmasi", local.strftime("%Y-%m-%d %H:%M WIB")))
    for label, value in rows:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(32, 6, _t(label))
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, _t(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(235, 238, 243)
    for name, w in COLS:
        pdf.cell(w, 7, _t(name), border=1, fill=True, align="C")
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    for n, it in enumerate(snapshot["items"], 1):
        values = [str(n), it["sku"], it["name"][:34], f"{A.fmt_qty(it['qty_ordered'])} {it['uom']}",
                  A.rupiah(it["unit_price"]), A.rupiah(it["line_total"]), it.get("needed_by_date") or "-"]
        for (_, w), v in zip(COLS, values):
            pdf.cell(w, 7, _t(v), border=1, align="R" if v and v[:2] == "Rp" else "L")
        pdf.ln()
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(sum(w for _, w in COLS[:5]), 8, "Total", border=1, align="R")
    pdf.cell(sum(w for _, w in COLS[5:]), 8, _t(A.rupiah(snapshot["total_amount"])), border=1, align="R")
    pdf.ln(12)
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, _t("Dokumen ini dibuat otomatis dari data PO yang telah dikonfirmasi melalui Telegram. "
                            "Mohon periksa dan balas di chat bila ada yang tidak sesuai."))
    return bytes(pdf.output())
