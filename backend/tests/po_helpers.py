"""Shared helpers for PO automation and supplier Telegram tests."""
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (AutomationAction, MaterialSupplier, POChangeRequest, POSupplierConfirmation, PurchaseOrder,
                        SupplierConversation, SupplierMessage)
from app.models.enums import ConversationPurpose
from app.supplier_chat.service import SupplierChatService
from app.supplier_chat.transport import SANDBOX_MANAGER_CHAT_ID, SandboxTransport, sandbox_chat_id
from configs.tools import po_actions as A
from tests import chat_fakes as F

API = "/api/v1"


def issue_po(seeded, sku: str, supplier_code: str, qty: float) -> int:
    """Creates a MANUAL PO and walks it to ISSUED through the regular status machine."""
    material_id, supplier_id = seeded["materials"][sku], seeded["suppliers"][supplier_code]
    with SessionLocal() as db:
        price = db.scalar(select(MaterialSupplier.unit_price).where(MaterialSupplier.material_id == material_id,
                                                                    MaterialSupplier.supplier_id == supplier_id))
    with A.write_session() as db:
        po = A.create_and_issue_po(db, {"supplier_id": supplier_id, "items": [
            {"material_id": material_id, "qty_ordered": qty, "unit_price": price, "needed_by_date": None}]}, "Tester")
        return po.id


def draft_po(client, seeded, sku: str, supplier_code: str, qty: float) -> dict:
    r = client.post(f"{API}/purchase-orders", json={"supplier_id": seeded["suppliers"][supplier_code], "items": [
        {"material_id": seeded["materials"][sku], "qty_ordered": qty, "unit_price": 1000}]})
    assert r.status_code == 201, r.text
    return r.json()


def supplier_service(script: dict, **cfg) -> tuple[SupplierChatService, F.FakeLLM]:
    agents, fake, registry = F.fake_agents(script)
    return SupplierChatService(agents, {**registry.supplier_chat, **cfg}, SandboxTransport(),
                               SANDBOX_MANAGER_CHAT_ID), fake


def link(svc: SupplierChatService, seeded, supplier_code: str) -> int:
    svc.link_sandbox(seeded["suppliers"][supplier_code])
    return sandbox_chat_id(seeded["suppliers"][supplier_code])


def start(svc, po_id: int, purpose=ConversationPurpose.CONFIRM_ORDER) -> int:
    with A.write_session() as db:
        conv = A.queue_conversation(db, db.get(PurchaseOrder, po_id), purpose)
        cid = conv.id
    svc.dispatch_queued()
    return cid


def po(po_id: int) -> PurchaseOrder | None:
    with SessionLocal() as db:
        p = db.get(PurchaseOrder, po_id)
        if p is not None:
            p.items  # noqa: B018  (load before session closes)
            p.supplier  # noqa: B018
        return p


def conversation(cid: int) -> SupplierConversation:
    with SessionLocal() as db:
        return db.get(SupplierConversation, cid)


def conversations() -> list[SupplierConversation]:
    with SessionLocal() as db:
        return list(db.scalars(select(SupplierConversation).order_by(SupplierConversation.id)))


def confirmation_status(po_id: int) -> str | None:
    with SessionLocal() as db:
        conf = db.scalar(select(POSupplierConfirmation).where(POSupplierConfirmation.po_id == po_id))
        return conf.status.value if conf else None


def messages(direction: str | None = None, chat_id: int | None = None) -> list[SupplierMessage]:
    with SessionLocal() as db:
        stmt = select(SupplierMessage).order_by(SupplierMessage.id)
        if direction:
            stmt = stmt.where(SupplierMessage.direction == direction)
        if chat_id is not None:
            stmt = stmt.where(SupplierMessage.chat_id == chat_id)
        return list(db.scalars(stmt))


def change_requests() -> list[POChangeRequest]:
    with SessionLocal() as db:
        return list(db.scalars(select(POChangeRequest).order_by(POChangeRequest.id)))


def action(action_id: str) -> AutomationAction:
    with SessionLocal() as db:
        return db.get(AutomationAction, action_id)


def on_order(sku: str) -> float:
    from app.services import inventory_service
    with SessionLocal() as db:
        return next(r["on_order"] for r in inventory_service.list_inventory(db) if r["sku"] == sku)
