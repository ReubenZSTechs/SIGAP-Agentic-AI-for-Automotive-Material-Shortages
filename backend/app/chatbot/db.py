"""Read-only database access for the chatbot."""
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


@lru_cache(maxsize=1)
def chat_engine() -> Engine:
    """Engine on `CHAT_DATABASE_URL` (fallback `DATABASE_URL`) whose transactions are READ ONLY."""
    engine = create_engine(settings.CHAT_DATABASE_URL or settings.DATABASE_URL,
                           pool_pre_ping=True, pool_recycle=1800, pool_size=3, max_overflow=2)

    @event.listens_for(engine, "begin")
    def _read_only(conn):
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")

    return engine


def chat_session() -> Session:
    """New ORM session bound to the read-only engine."""
    return sessionmaker(bind=chat_engine(), autoflush=False)()
