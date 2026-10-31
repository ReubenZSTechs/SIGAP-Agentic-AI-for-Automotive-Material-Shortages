"""Startup migration: Rupiah columns INTEGER -> BIGINT (orders above Rp 2.147.483.647 failed with DataError)."""
from sqlalchemy import text

from app import db_migrate
from app.chatbot import semantic_views
from app.database import SessionLocal
from app.models import PurchaseOrder
from configs.tools import po_actions as A

VIEWS = ("chat_material_suppliers_v", "chat_purchase_order_items_v", "chat_latest_planning_lines_v")


def _types(conn) -> dict[str, str]:
    return {f"{t}.{c}": conn.execute(text(
        "SELECT data_type FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = :t AND column_name = :c"), {"t": t, "c": c}).scalar() for t, c in db_migrate.MONEY_COLUMNS}


def _issue(seeded, unit_price: int, qty: float) -> int:
    with A.write_session() as wdb:
        po = A.create_and_issue_po(wdb, {"supplier_id": seeded["KARET"], "items": [
            {"material_id": seeded["materials"]["RM-RUB-01"], "qty_ordered": qty, "unit_price": unit_price,
             "needed_by_date": None}]}, "Tester")
        return po.id


def test_old_integer_schema_is_widened_without_changing_data(engine, db, seeded):
    po_id = _issue(seeded, 35_000, 10)
    db.close()                                                    # sesi fixture tidak boleh menahan kunci tabel
    with engine.begin() as conn:                                  # skema lama (sebelum migrasi): INTEGER
        semantic_views.drop_views(conn)
        for t, c in db_migrate.MONEY_COLUMNS:
            conn.execute(text(f"ALTER TABLE {t} ALTER COLUMN {c} TYPE INTEGER"))
        semantic_views.create_views(conn)
        assert set(_types(conn).values()) == {"integer"}
        before = conn.execute(text("SELECT (SELECT SUM(unit_price) FROM material_suppliers), "
                                   "(SELECT SUM(line_total) FROM po_items), (SELECT SUM(total_amount) FROM purchase_orders), "
                                   "(SELECT COUNT(*) FROM po_items)")).one()
    try:
        db_migrate.apply(engine)
    finally:                                                      # tes lain selalu mendapat skema BIGINT
        with engine.begin() as conn:
            db_migrate.widen_money_columns(conn)
    with engine.begin() as conn:
        assert set(_types(conn).values()) == {"bigint"}
        after = conn.execute(text("SELECT (SELECT SUM(unit_price) FROM material_suppliers), "
                                  "(SELECT SUM(line_total) FROM po_items), (SELECT SUM(total_amount) FROM purchase_orders), "
                                  "(SELECT COUNT(*) FROM po_items)")).one()
        assert tuple(after) == tuple(before)                    # nilai & jumlah baris tidak berubah
        views = {r[0] for r in conn.execute(text("SELECT viewname FROM pg_views WHERE schemaname = current_schema()"))}
        assert set(VIEWS) <= views
        assert db_migrate.widen_money_columns(conn) == []        # kedua kalinya: tidak ada yang diubah
    with SessionLocal() as db:
        assert db.get(PurchaseOrder, po_id).total_amount == 350_000


def test_po_above_two_billion_is_stored_exactly(engine, seeded):
    po_id = _issue(seeded, 1_500_000_000, 2)                     # 3 miliar: dulu DataError (INTEGER overflow)
    with SessionLocal() as db:
        po = db.get(PurchaseOrder, po_id)
        assert po.total_amount == 3_000_000_000 and po.items[0].line_total == 3_000_000_000
        number = po.po_number
    with engine.connect() as conn:                               # chatbot membaca nilai yang sama lewat view
        row = conn.execute(text("SELECT line_total, po_total_amount FROM chat_purchase_order_items_v "
                                "WHERE po_number = :n"), {"n": number}).one()
    assert tuple(row) == (3_000_000_000, 3_000_000_000)


def test_busy_tables_postpone_the_widening_instead_of_hanging_startup(engine, db, seeded):
    db.close()
    with engine.begin() as conn:
        semantic_views.drop_views(conn)
        conn.execute(text("ALTER TABLE po_items ALTER COLUMN line_total TYPE INTEGER"))
        semantic_views.create_views(conn)
    reader = engine.connect()
    tx = reader.begin()
    reader.execute(text("SELECT COUNT(*) FROM po_items"))         # mis. worker di tengah transaksi
    try:
        with engine.begin() as conn:
            assert db_migrate.widen_money_columns(conn) == []        # menyerah setelah lock_timeout, tidak menggantung
            assert _types(conn)["po_items.line_total"] == "integer"
            assert "chat_purchase_order_items_v" in {r[0] for r in conn.execute(text("SELECT viewname FROM pg_views"))}
    finally:
        tx.rollback()
        reader.close()
    with engine.begin() as conn:                                  # startup berikutnya: tabel bebas -> dimigrasi
        assert db_migrate.widen_money_columns(conn) == ["po_items.line_total"]
