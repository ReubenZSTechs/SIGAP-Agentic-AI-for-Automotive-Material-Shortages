"""Static validation of LLM-generated SQL before it reaches the database."""
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

_FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop,
                    exp.Alter, exp.TruncateTable, exp.Command, exp.Into, exp.Lock, exp.Set,
                    exp.Transaction, exp.Commit, exp.Rollback, exp.Grant)
_FORBIDDEN_FUNC_PREFIXES = ("pg_", "lo_", "dblink", "query_to_", "txid_", "set_config",
                            "current_setting", "nextval", "setval", "currval", "lastval")


class SqlGuardError(ValueError):
    """The SQL is not a safe, single, read-only query over allowed relations."""


def _func_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def validate_sql(sql: str, allowed: frozenset[str], row_limit: int) -> str:
    """Returns normalized SQL with an enforced LIMIT, or raises `SqlGuardError`."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as e:
        raise SqlGuardError(f"SQL parse error: {e}") from e
    if len(statements) != 1:
        raise SqlGuardError("Exactly one SQL statement is allowed.")
    stmt = statements[0]
    if not isinstance(stmt, exp.Query):
        raise SqlGuardError("Only SELECT queries are allowed.")

    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SqlGuardError(f"Forbidden SQL construct: {node.key.upper()}.")
        if isinstance(node, exp.Func) and _func_name(node).startswith(_FORBIDDEN_FUNC_PREFIXES):
            raise SqlGuardError(f"Function not allowed: {_func_name(node)}.")

    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        if isinstance(table.this, exp.Func):
            continue
        schema = (table.db or "").lower()
        name = table.name.lower()
        if schema not in ("", "public"):
            raise SqlGuardError(f"Schema not allowed: {schema}.")
        if name not in allowed and name not in cte_names:
            raise SqlGuardError(f"Relation not allowed: {name}. Allowed: {', '.join(sorted(allowed))}.")

    limit = stmt.args.get("limit")
    current = None
    if limit is not None and isinstance(limit.expression, exp.Literal) and limit.expression.is_int:
        current = int(limit.expression.this)
    if current is None or current > row_limit:
        stmt = stmt.limit(row_limit)
    return stmt.sql(dialect="postgres")
