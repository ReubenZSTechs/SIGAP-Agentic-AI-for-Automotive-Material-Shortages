"""Satu baris per panggilan agent LLM (input, prompt, output, percobaan ulang, latensi, token).

Diisi oleh `Agent.run` lewat `app.chatbot.tracing`; dibaca Agent Hub (Streamlit) lewat `/agent-runs`.
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    agent: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str | None] = mapped_column(String(120), default=None)
    workflow: Mapped[str] = mapped_column(String(32), index=True, default="other")   # chat | supplier | manager | …
    trace_id: Mapped[str] = mapped_column(String(32), index=True)                    # satu giliran chat / satu pesan
    ref: Mapped[dict | None] = mapped_column(JSON, default=None)                     # thread_id, supplier_id, …
    status: Mapped[str] = mapped_column(String(8), index=True)                       # ok | invalid | error
    error: Mapped[str | None] = mapped_column(String(500), default=None)
    latency_ms: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int | None] = mapped_column(default=None)
    output_tokens: Mapped[int | None] = mapped_column(default=None)
    output: Mapped[dict | None] = mapped_column(JSON, default=None)
    input: Mapped[str] = deferred(mapped_column(Text))
    system_prompt: Mapped[str | None] = deferred(mapped_column(Text, default=None))
    attempts: Mapped[list | None] = deferred(mapped_column(JSON, default=None))        # [{raw, errors}]
