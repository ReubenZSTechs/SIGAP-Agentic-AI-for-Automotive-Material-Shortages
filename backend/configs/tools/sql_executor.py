"""Executes guarded SQL on the read-only chatbot engine."""
from app.chatbot.db import chat_engine


class SqlExecutionError(RuntimeError):
    """The database rejected or failed the query."""


def run_select(sql: str, timeout_ms: int) -> tuple[list[str], list[dict]]:
    """Runs one SELECT in a READ ONLY transaction with a statement timeout."""
    with chat_engine().connect() as conn:
        try:
            with conn.begin():
                conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
                # Raw DB-API cursor: no bind-parameter parsing, so '%' and ':' in the SQL stay literal.
                cursor = conn.connection.cursor()
                try:
                    cursor.execute(sql)
                    columns = [d[0] for d in cursor.description or []]
                    rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
                finally:
                    cursor.close()
        except Exception as e:
            lines = str(getattr(e, "orig", e)).strip().splitlines()
            raise SqlExecutionError(" | ".join(lines[:3]) or type(e).__name__) from e
    return columns, rows
