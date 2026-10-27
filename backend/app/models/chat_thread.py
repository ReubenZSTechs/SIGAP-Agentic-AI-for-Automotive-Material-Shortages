"""Daftar percakapan chatbot Dashboard, untuk fitur Riwayat percakapan.

Isi pesan TIDAK disimpan di sini: pesan ada di checkpointer LangGraph (tabel `checkpoints*`) dengan `thread_id`
yang sama. Tabel ini hanya menyimpan metadata yang dibutuhkan daftar riwayat (judul, pemilik, waktu).

`owner_id` = id acak per browser (header `X-Client-Id`). MVP ini tanpa autentikasi, jadi ini bukan pengaman:
hanya memisahkan riwayat antar browser agar daftar & tombol hapus tidak menyentuh percakapan orang lain.
Bila autentikasi ditambahkan, ganti dengan id pengguna.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    """UTC tanpa tzinfo (sama dengan kolom waktu lain; frontend menambahkan 'Z' saat memformat)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ChatThread(Base):
    __tablename__ = "chat_threads"
    __table_args__ = (Index("ix_chat_threads_owner_updated", "owner_id", "updated_at"),)

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), default=None)     # NULL = tak diketahui (tidak tampil)
    title: Mapped[str] = mapped_column(String(120))                            # potongan pesan pertama
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
