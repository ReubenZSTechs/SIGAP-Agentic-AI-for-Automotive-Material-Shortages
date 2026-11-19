"""Satu baris per eksekusi tool Postgres (tool baca chatbot, query SQL agent, tool tulis PO / master data).

Diisi oleh `app.chatbot.tracing.record_tool`; dibaca Agent Hub (Streamlit) lewat `/tool-runs`.
Memakai `trace_id` yang sama dengan `agent_runs`, jadi satu giliran chat bisa diikuti dari LLM sampai SQL.
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.database import Base


class ToolRun(Base):
    __tablename__ = "tool_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    tool: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(8), index=True)                         # read | sql | write
    workflow: Mapped[str] = mapped_column(String(32), index=True, default="other")
    trace_id: Mapped[str] = mapped_column(String(32), index=True)
    ref: Mapped[dict | None] = mapped_column(JSON, default=None)
    status: Mapped[str] = mapped_column(String(8), index=True)                       # ok | error
    error: Mapped[str | None] = mapped_column(String(500), default=None)
    latency_ms: Mapped[int] = mapped_column(default=0)
    row_count: Mapped[int | None] = mapped_column(default=None)
    args: Mapped[dict | None] = mapped_column(JSON, default=None)
    result_preview: Mapped[list | dict | None] = deferred(mapped_column(JSON, default=None))  # maks. 20 baris
    statements: Mapped[list | None] = deferred(mapped_column(JSON, default=None))   # [{sql, params, ms}]
