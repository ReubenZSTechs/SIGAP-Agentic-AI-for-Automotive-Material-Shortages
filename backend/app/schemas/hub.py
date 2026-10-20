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
    choice: Literal["abort", "approve_change", "resource"]


class MissionItemIn(BaseModel):
    material_id: int
    qty: float | None = Field(default=None, gt=0)
    needed_by: str | None = None


class MissionIn(ActorIn):
    scenario: Literal["PRICE_QUOTE", "STOCK_CHECK", "DELIVERY_CONFIRM", "DOC_REQUEST"]
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


class DocumentPatchIn(ActorIn):
    doc_type: Literal["INVOICE", "DELIVERY_NOTE", "TAX_INVOICE", "OTHER"] | None = None
    number: str | None = Field(default=None, max_length=60)
    po_id: int | None = None
    po_number: str | None = Field(default=None, max_length=40)
    doc_date: str | None = None
    total: float | None = Field(default=None, ge=0)
    qty: dict[str, float] | None = None


class ArchiveIn(ActorIn):
    confirm_mismatch: bool = False


class SandboxAttachmentIn(BaseModel):
    supplier_id: int
    file_name: str = Field(min_length=1, max_length=160)
    mime: str = Field(min_length=3, max_length=80)
    content_base64: str
    caption: str | None = Field(default=None, max_length=1000)


class SandboxReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class TemplateIn(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    scenario: str = Field(min_length=3, max_length=24)
    body: str = Field(min_length=10, max_length=2000)
