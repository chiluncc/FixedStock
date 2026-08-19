import sqlite3
import traceback
from pathlib import Path
from func_timeout import func_timeout, FunctionTimedOut

from .base import ToolResult


def _connect(path: Path, *, read_only: bool=True) -> sqlite3.Connection:
    if read_only:
        uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
        return sqlite3.connect(uri, uri=True, check_same_thread=False)
    return sqlite3.connect(str(path))


def sql_query(path: Path, sql: str, *, limit: int | None = 32) -> ToolResult:
    try:
        conn = _connect(path, read_only=True)
        cursor = conn.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(limit)
        has_more = cursor.fetchone() is not None
        conn.close()

        lines = []
        lines.append("[name]")
        lines.append(", ".join(columns))
        lines.append("[data]")
        for row in rows:
            lines.append(", ".join(str(v) for v in row))

        if has_more:
            lines.append("[truncate]")
            lines.append(f"Result rows exceeded limit={limit}, output has been truncated")

        return ToolResult(result="\n".join(lines))
    except Exception as e:
        return ToolResult(error=True, error_str=str(e), error_trace=traceback.format_exc())


def time_limit_sql_query(path: Path, sql: str, *, limit: int | None = 32, second_limit: int = 120) -> ToolResult:
    try:
        return func_timeout(second_limit, sql_query, args=(path, sql, limit))
    except FunctionTimedOut:
        return ToolResult(
            error=True,
            error_str=f"SQL query timed out after {second_limit}s\n{sql}",
            error_trace=traceback.format_exc(),
        )
    except Exception as e:
        return ToolResult(error=True, error_str=str(e), error_trace=traceback.format_exc())