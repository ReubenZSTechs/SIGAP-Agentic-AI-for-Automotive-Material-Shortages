"""Registri percakapan chat (`chat_threads`): sumber daftar Riwayat percakapan di Dashboard.

Hanya metadata. Isi pesan tetap di checkpointer LangGraph; `ChatService.delete_thread` menghapus keduanya.
Semua fungsi menerima `Session` biasa (bukan sesi READ ONLY milik chatbot) karena menulis.
"""
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.chat_thread import ChatThread, utcnow

TITLE_MAX = 60
DEFAULT_LIMIT = 100


def make_title(message: str) -> str:
    """Judul = pesan pertama, spasi/baris baru dirapikan, dipotong di `TITLE_MAX` karakter."""
    text = " ".join((message or "").split())
    if not text:
        return "Percakapan"
    return text if len(text) <= TITLE_MAX else text[:TITLE_MAX - 1].rstrip() + "…"


def register(db: Session, thread_id: str, owner_id: str | None, message: str) -> None:
    """Giliran baru dengan `message`: buat entri (judul dari pesan ini) atau perbarui waktunya.

    Atomik (`ON CONFLICT`), jadi dua permintaan pertama yang bersamaan tidak saling menjatuhkan. Entri tanpa
    pemilik (mis. dibuat klien lama) diambil oleh klien pertama yang berbicara di thread itu; pemilik yang sudah
    ada tidak pernah diganti.
    """
    now = utcnow()
    stmt = pg_insert(ChatThread).values(thread_id=thread_id, owner_id=owner_id, title=make_title(message),
                                        created_at=now, updated_at=now)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ChatThread.thread_id],
        set_={"updated_at": now, "owner_id": func.coalesce(ChatThread.owner_id, stmt.excluded.owner_id)})
    db.execute(stmt)
    db.commit()


def touch(db: Session, thread_id: str) -> None:
    """Giliran lanjutan (jawab kartu/formulir): perbarui waktu bila entri ada; tidak membuat entri baru."""
    db.execute(update(ChatThread).where(ChatThread.thread_id == thread_id).values(updated_at=utcnow()))
    db.commit()


def list_for(db: Session, owner_id: str, limit: int = DEFAULT_LIMIT) -> list[ChatThread]:
    """Percakapan milik `owner_id`, yang terbaru dulu."""
    return list(db.scalars(select(ChatThread).where(ChatThread.owner_id == owner_id)
                           .order_by(ChatThread.updated_at.desc(), ChatThread.thread_id).limit(limit)))


def owned_ids(db: Session, owner_id: str) -> list[str]:
    return list(db.scalars(select(ChatThread.thread_id).where(ChatThread.owner_id == owner_id)))


def is_owned(db: Session, thread_id: str, owner_id: str) -> bool:
    return db.scalar(select(ChatThread.thread_id).where(ChatThread.thread_id == thread_id,
                                                        ChatThread.owner_id == owner_id)) is not None


def forget(db: Session, thread_id: str) -> None:
    db.execute(delete(ChatThread).where(ChatThread.thread_id == thread_id))
    db.commit()
