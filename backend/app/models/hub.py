"""Agent Hub (Hub Supplier di frontend): pengaturan, misi, proposal, draf, lampiran, audit.

Semua tabel berprefiks `hub_`. Kolom baru pada tabel yang sudah ada didaftarkan di `app/db_migrate.py`.
Enum Hub sengaja didefinisikan di sini, bukan di `enums.py`, supaya modul lama tidak tersentuh.
"""
import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _enum(e):
    return Enum(e, native_enum=False, length=24)


class ThreadMode(str, enum.Enum):
    AGENT = "AGENT"          # agent menjawab supplier
    HUMAN = "HUMAN"          # admin mengambil alih; agent dijeda untuk supplier ini


class OutboxStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    DISCARDED = "DISCARDED"


class MissionScenario(str, enum.Enum):
    PRICE_QUOTE = "PRICE_QUOTE"
    STOCK_CHECK = "STOCK_CHECK"
    DELIVERY_CONFIRM = "DELIVERY_CONFIRM"
    PO_CONFIRM = "PO_CONFIRM"          # agent PO: kirim PO ke supplier & kumpulkan konfirmasi (percakapan PO)
    PO_CANCEL = "PO_CANCEL"            # agent PO: minta supplier menyetujui pembatalan PO


PO_SCENARIOS = (MissionScenario.PO_CONFIRM, MissionScenario.PO_CANCEL)


class MissionSource(str, enum.Enum):
    MATERIAL = "MATERIAL"
    PO = "PO"


class MissionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUMMARIZING = "SUMMARIZING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class TargetState(str, enum.Enum):
    QUEUED = "QUEUED"        # belum dikirim (menunggu giliran / draf menunggu review)
    SENT = "SENT"            # menunggu balasan
    PAUSED = "PAUSED"        # percakapan PO aktif mengambil giliran; ditanyakan ulang setelahnya
    REPLIED = "REPLIED"
    NO_REPLY = "NO_REPLY"
    ESCALATED = "ESCALATED"
    WAITING_MANAGER = "WAITING_MANAGER"   # misi PO: supplier minta perubahan, menunggu keputusan manajer


class ProposalType(str, enum.Enum):
    PRICE_UPDATE = "PRICE_UPDATE"
    STOCK_CHECK = "STOCK_CHECK"
    PO_DELAY = "PO_DELAY"


class ProposalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISION = "REVISION"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class DocumentStatus(str, enum.Enum):   # kolom lama hub_documents.status (tidak ada lagi alur review)
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ARCHIVED = "ARCHIVED"
    REREQUESTED = "REREQUESTED"


class HubSettings(Base):
    """Satu baris (id=1): status jeda dan kebijakan otonomi/ambang/jam kerja."""
    __tablename__ = "hub_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    policies: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class HubSupplierControl(Base):
    """Status per supplier di Hub: ambil alih, undangan Telegram, dan pesan terakhir yang sudah dilihat."""
    __tablename__ = "hub_supplier_controls"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"), unique=True)
    mode: Mapped[ThreadMode] = mapped_column(_enum(ThreadMode), default=ThreadMode.AGENT)
    taken_over_by: Mapped[str | None] = mapped_column(String(80), default=None)
    taken_over_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_seen_message_id: Mapped[int] = mapped_column(default=0)


class HubMission(Base):
    __tablename__ = "hub_missions"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario: Mapped[MissionScenario] = mapped_column(_enum(MissionScenario))
    title: Mapped[str] = mapped_column(String(160))
    source: Mapped[MissionSource] = mapped_column(_enum(MissionSource), default=MissionSource.MATERIAL)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"),
                                              index=True, default=None)
    po_snapshot: Mapped[dict | None] = mapped_column(JSON, default=None)
    items: Mapped[list] = mapped_column(JSON, default=list)        # [{material_id, sku, name, qty, uom, needed_by}]
    topic: Mapped[str | None] = mapped_column(String(160), default=None)
    message_template: Mapped[str] = mapped_column(Text)            # teks pembuka (default dari MISSION_MESSAGES)
    deadline: Mapped[datetime] = mapped_column(DateTime)
    autonomy: Mapped[str] = mapped_column(String(8), default="AUTO")  # AUTO | REVIEW
    status: Mapped[MissionStatus] = mapped_column(_enum(MissionStatus), default=MissionStatus.ACTIVE, index=True)
    summary: Mapped[str | None] = mapped_column(String(500), default=None)
    automation_action_id: Mapped[str | None] = mapped_column(String(36), default=None)   # kartu chat Dashboard asal
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    targets: Mapped[list["HubMissionTarget"]] = relationship(
        back_populates="mission", cascade="all, delete-orphan", order_by="HubMissionTarget.id")


class HubMissionTarget(Base):
    __tablename__ = "hub_mission_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("hub_missions.id", ondelete="CASCADE"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    state: Mapped[TargetState] = mapped_column(_enum(TargetState), default=TargetState.QUEUED, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    result: Mapped[dict | None] = mapped_column(JSON, default=None)
    last_message_id: Mapped[int | None] = mapped_column(default=None)
    conversation_id: Mapped[int | None] = mapped_column(default=None, index=True)   # misi PO: percakapan PO terkait

    mission: Mapped["HubMission"] = relationship(back_populates="targets")
    supplier: Mapped["Supplier"] = relationship()


class HubOutbox(Base):
    """Draf pesan keluar yang menunggu review admin (otonomi "Draf dulu")."""
    __tablename__ = "hub_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    mission_target_id: Mapped[int | None] = mapped_column(
        ForeignKey("hub_mission_targets.id", ondelete="SET NULL"), default=None)
    kind: Mapped[str] = mapped_column(String(16), default="mission")   # mission | reminder | escalation | document
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[OutboxStatus] = mapped_column(_enum(OutboxStatus), default=OutboxStatus.DRAFT, index=True)
    review_reason: Mapped[str | None] = mapped_column(String(120), default=None)
    sent_message_id: Mapped[int | None] = mapped_column(default=None)
    reviewed_by: Mapped[str | None] = mapped_column(String(80), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HubProposal(Base):
    """Kartu persetujuan hasil misi (perubahan data bisnis selalu lewat sini)."""
    __tablename__ = "hub_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[ProposalType] = mapped_column(_enum(ProposalType))
    status: Mapped[ProposalStatus] = mapped_column(_enum(ProposalStatus), default=ProposalStatus.PENDING, index=True)
    risk: Mapped[str] = mapped_column(String(8), default="LOW")
    version: Mapped[int] = mapped_column(default=1)
    mission_id: Mapped[int | None] = mapped_column(ForeignKey("hub_missions.id", ondelete="SET NULL"), default=None)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), default=None)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"), default=None)
    title: Mapped[str] = mapped_column(String(160))
    payload: Mapped[dict] = mapped_column(JSON)          # summary, diff.rows, evidence, impact
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    decided_by: Mapped[str | None] = mapped_column(String(80), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    decision_note: Mapped[str | None] = mapped_column(String(300), default=None)
    result: Mapped[dict | None] = mapped_column(JSON, default=None)


class HubDocument(Base):
    """Lampiran foto/PDF dari supplier, ditampilkan di thread percakapan (kolom review lama tidak dipakai lagi)."""
    __tablename__ = "hub_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_messages.id", ondelete="SET NULL"), default=None)
    mission_id: Mapped[int | None] = mapped_column(ForeignKey("hub_missions.id", ondelete="SET NULL"), default=None)
    kind: Mapped[str] = mapped_column(String(8))           # image | pdf | file
    file_name: Mapped[str] = mapped_column(String(160))
    mime: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(default=0)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, default=None, deferred=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(200), default=None)
    doc_type: Mapped[str | None] = mapped_column(String(16), default=None)   # INVOICE | DELIVERY_NOTE | TAX_INVOICE
    number: Mapped[str | None] = mapped_column(String(60), default=None)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"), default=None)
    fields: Mapped[dict | None] = mapped_column(JSON, default=None)        # isian manual admin
    status: Mapped[DocumentStatus] = mapped_column(_enum(DocumentStatus), default=DocumentStatus.NEEDS_REVIEW, index=True)
    decided_by: Mapped[str | None] = mapped_column(String(80), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    note: Mapped[str | None] = mapped_column(String(300), default=None)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HubAuditLog(Base):
    """Jejak semua keputusan manajer dan tindakan agent (tidak pernah diubah). Sumber halaman Riwayat Aktivitas."""
    __tablename__ = "hub_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    actor: Mapped[str] = mapped_column(String(80))
    actor_type: Mapped[str | None] = mapped_column(String(8), default=None, index=True)   # MANAGER | AGENT | SYSTEM
    action: Mapped[str] = mapped_column(String(40))
    ref_type: Mapped[str] = mapped_column(String(24))
    ref_id: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str | None] = mapped_column(String(300), default=None)
    supplier_id: Mapped[int | None] = mapped_column(default=None, index=True)
    po_number: Mapped[str | None] = mapped_column(String(24), default=None, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), default=None)             # -> agent_runs / tool_runs
    detail: Mapped[dict | None] = mapped_column(JSON, default=None)
