"""Read-only database access for the chatbot.

The chatbot shares the application database (`DATABASE_URL`); there is no separate chat database or role.
Two ways to read, both READ ONLY (every transaction starts with `SET TRANSACTION READ ONLY` and a
statement timeout, both transaction-scoped so they also work behind the Supabase transaction pooler):

    ORM (curated tools):          db = chat_session()            -> db.scalars(select(...))
    raw SQL (text-to-SQL agent):  conn = create_connection()      -> execute_sql_query(conn, sql, timeout_ms)
"""
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


DEFAULT_STATEMENT_TIMEOUT_MS = 10_000


@lru_cache(maxsize=1)
def chat_engine() -> Engine:
    """Engine on `DATABASE_URL` whose transactions are READ ONLY and time-limited. Built once."""
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800, pool_size=3, max_overflow=2)

    @event.listens_for(engine, "begin")
    def _read_only(conn):
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {DEFAULT_STATEMENT_TIMEOUT_MS}")

    return engine


def chat_session() -> Session:
    """New ORM session bound to the read-only engine (use as `with chat_session() as db:`)."""
    return sessionmaker(bind=chat_engine(), autoflush=False)()


def create_connection() -> Connection:
    """Step 1: open a connection to the read-only engine (use as `with create_connection() as conn:`)."""
    return chat_engine().connect()


def execute_sql_query(conn: Connection, sql: str, timeout_ms: int) -> tuple[list[str], list[dict]]:
    """Step 2: run one SELECT in its own READ ONLY transaction, stopped after `timeout_ms`.

    Returns (column names, rows as dicts). A raw DB-API cursor is used, so '%' and ':' inside the SQL
    stay literal (no bind-parameter parsing).
    """
    with conn.begin():
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
        cursor = conn.connection.cursor()
        try:
            cursor.execute(sql)
            columns = [d[0] for d in cursor.description or []]
            rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
        finally:
            cursor.close()
    return columns, rows
