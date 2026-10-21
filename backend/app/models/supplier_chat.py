"""Percakapan Telegram dengan supplier: tautan chat, percakapan per PO, pesan, konfirmasi, dan permintaan revisi.

Semua tabel baru (tanpa mengubah tabel lama) agar `create_all` cukup tanpa migrasi.
`po_id` memakai ON DELETE SET NULL + `po_snapshot` sehingga riwayat tetap utuh setelah PO dihapus.
"""
from datetime import date, datetime

from sqlalchemy import (JSON, BigInteger, Date, DateTime, Enum, ForeignKey, LargeBinary, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.database import Base
from app.models.enums import (ChangeRequestStatus, ConversationPurpose, ConversationStatus,
                              MessageDirection, PORevisionStatus, SupplierConfirmationStatus)


def _enum(e):
    return Enum(e, native_enum=False, length=24)


class SupplierTelegramLink(Base):
    """Supplier menautkan chat Telegram lewat t.me/<bot>?start=<link_token>."""
    __tablename__ = "supplier_telegram_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"), unique=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, default=None)
    link_token: Mapped[str] = mapped_column(String(48), unique=True)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    supplier: Mapped["Supplier"] = relationship()


class SupplierConversation(Base):
    __tablename__ = "supplier_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"),
                                              index=True, default=None)
    po_number: Mapped[str] = mapped_column(String(24))
    po_snapshot: Mapped[dict] = mapped_column(JSON)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    purpose: Mapped[ConversationPurpose] = mapped_column(_enum(ConversationPurpose))
    status: Mapped[ConversationStatus] = mapped_column(_enum(ConversationStatus),
                                                       default=ConversationStatus.QUEUED, index=True)
    transport: Mapped[str] = mapped_column(String(16), default="sandbox")
    turn_count: Mapped[int] = mapped_column(default=0)
    outcome: Mapped[dict | None] = mapped_column(JSON, default=None)
    automation_action_id: Mapped[str | None] = mapped_column(String(36), default=None)
    change_request_id: Mapped[int | None] = mapped_column(default=None)   # revisi asal (REVISION_CONFIRM)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    supplier: Mapped["Supplier"] = relationship()


class SupplierMessage(Base):
    """Log semua pesan (supplier & manajer). Di mode sandbox, log ini adalah 'kotak masuk'-nya."""
    __tablename__ = "supplier_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("supplier_conversations.id", ondelete="CASCADE"), index=True, default=None)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), index=True, default=None)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    direction: Mapped[MessageDirection] = mapped_column(_enum(MessageDirection))
    text: Mapped[str] = mapped_column(Text)
    buttons: Mapped[list | None] = mapped_column(JSON, default=None)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    agent_output: Mapped[dict | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(String(300), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class POSupplierConfirmation(Base):
    """Status konfirmasi supplier atas sebuah PO (dihapus otomatis bersama PO)."""
    __tablename__ = "po_supplier_confirmations"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), unique=True)
    status: Mapped[SupplierConfirmationStatus] = mapped_column(
        _enum(SupplierConfirmationStatus), default=SupplierConfirmationStatus.PENDING)
    promised_delivery_date: Mapped[date | None] = mapped_column(Date, default=None)
    supplier_reference: Mapped[str | None] = mapped_column(String(80), default=None)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    revision_round: Mapped[int] = mapped_column(default=0)
    note: Mapped[str | None] = mapped_column(String(300), default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class POChangeRequest(Base):
    """Permintaan revisi dari supplier + opsi deterministik untuk manajer."""
    __tablename__ = "po_change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"),
                                              index=True, default=None)
    po_number: Mapped[str] = mapped_column(String(24))
    po_snapshot: Mapped[dict] = mapped_column(JSON)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("supplier_conversations.id", ondelete="SET NULL"), default=None)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    proposed_changes: Mapped[list] = mapped_column(JSON)
    invalid_changes: Mapped[list] = mapped_column(JSON, default=list)
    supplier_message: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)
    status: Mapped[ChangeRequestStatus] = mapped_column(_enum(ChangeRequestStatus),
                                                        default=ChangeRequestStatus.PENDING_MANAGER, index=True)
    pending_choice: Mapped[str | None] = mapped_column(String(20), default=None)
    manager_choice: Mapped[str | None] = mapped_column(String(20), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    result: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    supplier: Mapped["Supplier"] = relationship()


class PORevision(Base):
    """Versi PO yang dibahas dengan supplier: v1 = yang pertama dikirim, v2+ = revisi yang disetujui manajer.

    Versi yang dikonfirmasi supplier menjadi FINAL dan menyimpan PDF yang dikirim ke supplier.
    """
    __tablename__ = "po_revisions"
    __table_args__ = (UniqueConstraint("po_id", "version", name="uq_po_revisions_po_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"),
                                              index=True, default=None)
    po_number: Mapped[str] = mapped_column(String(24), index=True)
    version: Mapped[int] = mapped_column(default=1)
    snapshot: Mapped[dict] = mapped_column(JSON)
    changes: Mapped[list] = mapped_column(JSON, default=list)          # [{sku, name, field, old, new}] vs versi sebelumnya
    change_request_id: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[PORevisionStatus] = mapped_column(_enum(PORevisionStatus), default=PORevisionStatus.CURRENT)
    created_by: Mapped[str | None] = mapped_column(String(80), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    pdf: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, default=None))
    pdf_message_id: Mapped[int | None] = mapped_column(default=None)
