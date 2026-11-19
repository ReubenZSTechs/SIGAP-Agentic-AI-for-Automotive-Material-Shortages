"""Executes guarded SQL on the read-only chatbot engine (used by the text-to-SQL agent)."""
import time

from app.chatbot import tracing
from app.chatbot.db import create_connection, execute_sql_query


class SqlExecutionError(RuntimeError):
    """The database rejected or failed the query."""


def _short_error(e: Exception) -> str:
    """First lines of the database message, e.g. 'relation "x" does not exist'."""
    lines = str(getattr(e, "orig", e)).strip().splitlines()
    return " | ".join(lines[:3]) or type(e).__name__


def run_select(sql: str, timeout_ms: int) -> tuple[list[str], list[dict]]:
    """Runs one SELECT and returns (columns, rows); traced in `tool_runs` as `query_database`.

        1. create_connection()             open a read-only connection
        2. execute_sql_query(conn, sql)    run the SELECT with a statement timeout
    """
    with tracing.record_tool("query_database", "sql", {"sql": sql}) as run, create_connection() as conn:
        started = time.perf_counter()
        try:
            columns, rows = execute_sql_query(conn, sql, timeout_ms)
        except Exception as e:
            raise SqlExecutionError(_short_error(e)) from e
        finally:
            # the raw cursor bypasses SQLAlchemy's events, so the statement is recorded here
            run.add_statement(sql, ms=(time.perf_counter() - started) * 1000)
        run.done(rows)
    return columns, rows
