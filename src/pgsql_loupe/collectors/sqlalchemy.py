"""SQLAlchemy 2 collector (sync and async engines, any PostgreSQL driver).

    instrument_engine(engine)        # Engine or AsyncEngine

Uses the engine's cursor events. When the engine runs on psycopg connections that are also
instrumented, the statement is recorded here only: the cursor is marked while SQLAlchemy
records it, and the psycopg collector skips marked cursors. See docs/adr/0006-more-drivers.md.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine, ExceptionContext, ExecutionContext

from pgsql_loupe.core.record import SKIP_ATTRIBUTE, Recording, begin, copy_params
from pgsql_loupe.core.trace import Replay, current_trace

if TYPE_CHECKING:
    # Type checking only: importing sqlalchemy.ext.asyncio needs greenlet, which sync
    # SQLAlchemy apps do not install.
    from sqlalchemy.ext.asyncio import AsyncEngine

__all__ = ["instrument_engine"]

_RECORDING = "_pgsql_loupe_recording"
# Paramstyles a psycopg replay understands: %(name)s / %s, or $1 with a RawCursor.
_REPLAYABLE = {"pyformat": False, "format": False, "numeric_dollar": True}


def _driver_cursors(cursor: Any) -> list[Any]:
    """The DB-API cursor, and the driver cursor inside SQLAlchemy's async adapters."""
    inner = getattr(cursor, "_cursor", None)
    return [cursor] if inner is None else [cursor, inner]


def _mark(cursor: Any, recorded_above: bool) -> None:
    for target in _driver_cursors(cursor):
        try:
            if recorded_above:
                setattr(target, SKIP_ATTRIBUTE, True)
            elif SKIP_ATTRIBUTE in getattr(target, "__dict__", {}):
                delattr(target, SKIP_ATTRIBUTE)
        except (AttributeError, TypeError):
            pass  # plain driver cursors have __slots__; only instrumented ones need the mark


def _backend_pid(conn: Connection) -> int | None:
    try:
        driver = conn.connection.driver_connection
        info = getattr(driver, "info", None)
        if info is not None:  # psycopg
            return int(info.backend_pid) or None
        get_pid = getattr(driver, "get_server_pid", None)  # asyncpg
        return int(get_pid()) if get_pid else None
    except Exception:
        return None


def _rowcount(cursor: Any) -> int | None:
    count = getattr(cursor, "rowcount", -1)
    return count if isinstance(count, int) and count >= 0 else None


def _before(
    conn: Connection,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: ExecutionContext | None,
    executemany: bool,
) -> None:
    trace = current_trace()
    if trace is None or context is None:
        return
    try:
        if executemany:
            first = parameters[0] if parameters else None
            param_sets: int | None = len(parameters)
        else:
            first, param_sets = parameters, None
        raw = _REPLAYABLE.get(conn.dialect.paramstyle)
        replay = None if raw is None else Replay(statement, copy_params(first), raw=raw)
        rec = begin(
            trace,
            kind="executemany" if executemany else "execute",
            sql=statement,
            shown_params=first,
            replay=replay,
            tx_status="INTRANS" if conn.in_transaction() else "IDLE",
            backend_pid=_backend_pid(conn),
            frame=sys._getframe(1),
            param_sets=param_sets,
        )
    except Exception:  # never let the tracer break the user's query
        return
    setattr(context, _RECORDING, rec)
    _mark(cursor, True)


def _after(
    conn: Connection,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: ExecutionContext | None,
    executemany: bool,
) -> None:
    try:
        rec: Recording | None = getattr(context, _RECORDING, None)
        if rec is not None:
            delattr(context, _RECORDING)
            rec.finish(_rowcount(cursor))
        _mark(cursor, False)
    except Exception:  # never let the tracer break the user's query
        pass


def _error(exception_context: ExceptionContext) -> None:
    # Runs inside SQLAlchemy's own error handling: raising here would replace the user's
    # database error with ours, so every step is guarded.
    try:
        context = getattr(exception_context, "execution_context", None)
        rec: Recording | None = getattr(context, _RECORDING, None)
        if rec is not None:
            delattr(context, _RECORDING)
            rec.fail(exception_context.original_exception)
        cursor = getattr(exception_context, "cursor", None) or getattr(context, "cursor", None)
        if cursor is not None:
            _mark(cursor, False)
    except Exception:
        pass


def instrument_engine(engine: Engine | AsyncEngine) -> None:
    """Record this engine's statements into the active trace. Safe to call twice."""
    # An AsyncEngine wraps a sync Engine. Checking for Engine (not AsyncEngine) avoids importing
    # sqlalchemy.ext.asyncio, which needs greenlet, which sync-only apps do not install.
    target = engine if isinstance(engine, Engine) else engine.sync_engine
    if event.contains(target, "before_cursor_execute", _before):
        return
    event.listen(target, "before_cursor_execute", _before)
    event.listen(target, "after_cursor_execute", _after)
    event.listen(target, "handle_error", _error)
