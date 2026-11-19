"""Request body Agent Hub. Respons dibentuk di `app/hub/*` mengikuti kontrak frontend (ApprovalItem, Thread, Mission)."""
from typing import Literal

from pydantic import BaseModel, Field

Approver = Field(min_length=2, max_length=80)


class ActorIn(BaseModel):
    approver: str = Approver


class MessageIn(ActorIn):
    text: str = Field(min_length=1, max_length=4000)


class OutboxSendIn(ActorIn):
    text: str | None = Field(default=None, max_length=4000)


class ApproveIn(ActorIn):
    version: int
    selected: list[str] | None = None
    edits: dict[str, float] | None = None


class DecideIn(ActorIn):
    reason: str = Field(min_length=3, max_length=300)


class ChooseIn(ActorIn):
    choice: Literal["abort", "approve_change", "resource", "negotiate", "accept_date", "reject_date",
                    "continue_project", "cancel_project"]
    counter_prices: dict[int, int] | None = None      # negotiate: {po_item_id: harga satuan}
    schedule_ids: list[int] | None = None             # cancel_project: subset jadwal yang dibatalkan


class MissionItemIn(BaseModel):
    material_id: int
    qty: float | None = Field(default=None, gt=0)
    needed_by: str | None = None


class MissionIn(ActorIn):
    scenario: Literal["PRICE_QUOTE", "STOCK_CHECK", "DELIVERY_CONFIRM", "PO_CONFIRM", "PO_CANCEL"]
    title: str | None = Field(default=None, max_length=160)
    po_id: int | None = None
    items: list[MissionItemIn] = []
    topic: str | None = Field(default=None, max_length=160)
    supplier_ids: list[int] = Field(min_length=1)
    deadline: str
    autonomy: Literal["AUTO", "REVIEW"] | None = None
    message: str | None = Field(default=None, max_length=2000)


class RemindIn(ActorIn):
    supplier_ids: list[int] | None = None


class EscalateIn(ActorIn):
    supplier_id: int


class SandboxAttachmentIn(BaseModel):
    supplier_id: int
    file_name: str = Field(min_length=1, max_length=160)
    mime: str = Field(min_length=3, max_length=80)
    content_base64: str
    caption: str | None = Field(default=None, max_length=1000)


class SandboxReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ManagerButtonIn(ActorIn):
    data: str = Field(min_length=3, max_length=64)


class SupplierConversationIn(ActorIn):
    purpose: Literal["CONFIRM_ORDER", "CANCEL_ORDER"]
