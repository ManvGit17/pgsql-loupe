"""asyncpg collector: a Connection subclass passed as `connection_class`.

    conn = await asyncpg.connect(dsn, connection_class=TracedConnection)
    pool = await asyncpg.create_pool(dsn, connection_class=TracedConnection)
    traced_connection_class(MyConnection)    # if you already use your own subclass

Not asyncpg's query logger: it runs after the query via `loop.call_soon` (no call site, start
time unknown) and does not see prepared statements. See docs/adr/0006-more-drivers.md.
Not recorded: statements run through `conn.prepare()` and `conn.cursor()`, and the pool's
own `reset()` of a returned connection.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable, Iterable, Sequence
from contextvars import ContextVar
from functools import partial
from typing import Any, TypeVar

import asyncpg

from pgsql_loupe.core.record import Recording, begin, copy_params
from pgsql_loupe.core.trace import Replay, StatementKind, current_trace

__all__ = ["TracedConnection", "traced_connection_class"]

# True while asyncpg's pool resets a connection it is taking back (RESET ALL, UNLISTEN *, ...):
# driver housekeeping, not the application's SQL, and invisible with psycopg's pool too.
_housekeeping: ContextVar[bool] = ContextVar("pgsql_loupe_asyncpg_housekeeping", default=False)

T = TypeVar("T")


def _status_rows(status: Any) -> int | None:
    """Rows from a command tag such as 'UPDATE 3' or 'INSERT 0 2'."""
    if isinstance(status, str):
        last = status.rsplit(" ", 1)[-1]
        return int(last) if last.isdigit() else None
    return None


def _begin(
    conn: Any, kind: StatementKind, sql: str, args: Any, param_sets: int | None = None
) -> Recording | None:
    trace = current_trace()
    if trace is None or _housekeeping.get():
        return None
    try:
        return begin(
            trace,
            kind=kind,
            sql=sql,
            shown_params=list(args) if args is not None else None,
            replay=None if kind == "copy" else Replay(sql, copy_params(args), raw=True),
            tx_status="INTRANS" if conn.is_in_transaction() else "IDLE",
            backend_pid=conn.get_server_pid() or None,
            frame=sys._getframe(2),
            param_sets=param_sets,
        )
    except Exception:  # never let the tracer break the user's query
        return None


async def _record(
    rec: Recording | None, call: Callable[[], Awaitable[T]], rows: Callable[[T], int | None]
) -> T:
    if rec is None:
        return await call()
    try:
        result = await call()
    except BaseException as exc:
        rec.fail(exc)
        raise
    rec.finish(rows(result))
    return result


def _none(_: Any) -> None:
    return None


class TracingMixin:
    """Put in front of asyncpg.Connection (or a subclass of it) in the MRO."""

    __slots__ = ()

    def _next(self) -> Any:
        return super()

    async def reset(self, **kwargs: Any) -> Any:
        token = _housekeeping.set(True)
        try:
            return await self._next().reset(**kwargs)
        finally:
            _housekeeping.reset(token)

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> Any:
        rec = _begin(self, "execute", query, args)
        return await _record(
            rec, partial(self._next().execute, query, *args, **kwargs), _status_rows
        )

    async def fetch(self, query: str, *args: Any, **kwargs: Any) -> Any:
        rec = _begin(self, "execute", query, args)
        return await _record(rec, partial(self._next().fetch, query, *args, **kwargs), len)

    async def fetchrow(self, query: str, *args: Any, **kwargs: Any) -> Any:
        rec = _begin(self, "execute", query, args)
        call = partial(self._next().fetchrow, query, *args, **kwargs)
        return await _record(rec, call, lambda row: 0 if row is None else 1)

    async def fetchval(self, query: str, *args: Any, **kwargs: Any) -> Any:
        rec = _begin(self, "execute", query, args)
        return await _record(rec, partial(self._next().fetchval, query, *args, **kwargs), _none)

    async def fetchmany(self, query: str, args: Iterable[Any], **kwargs: Any) -> Any:
        sets = args if isinstance(args, Sequence) else list(args)
        rec = _begin(self, "executemany", query, sets[0] if sets else None, len(sets))
        return await _record(rec, partial(self._next().fetchmany, query, sets, **kwargs), len)

    async def executemany(self, command: str, args: Iterable[Any], **kwargs: Any) -> Any:
        # A generator is turned into a list here; asyncpg reads all of it anyway.
        sets = args if isinstance(args, Sequence) else list(args)
        rec = _begin(self, "executemany", command, sets[0] if sets else None, len(sets))
        return await _record(rec, partial(self._next().executemany, command, sets, **kwargs), _none)

    async def copy_from_query(self, query: str, *args: Any, **kwargs: Any) -> Any:
        rec = _begin(self, "copy", f"COPY ({query}) TO STDOUT", args)
        call = partial(self._next().copy_from_query, query, *args, **kwargs)
        return await _record(rec, call, _status_rows)

    async def copy_from_table(self, table_name: str, **kwargs: Any) -> Any:
        rec = _begin(self, "copy", f"COPY {table_name} TO STDOUT", None)
        call = partial(self._next().copy_from_table, table_name, **kwargs)
        return await _record(rec, call, _status_rows)

    async def copy_to_table(self, table_name: str, **kwargs: Any) -> Any:
        rec = _begin(self, "copy", f"COPY {table_name} FROM STDIN", None)
        call = partial(self._next().copy_to_table, table_name, **kwargs)
        return await _record(rec, call, _status_rows)

    async def copy_records_to_table(self, table_name: str, **kwargs: Any) -> Any:
        rec = _begin(self, "copy", f"COPY {table_name} FROM STDIN", None)
        call = partial(self._next().copy_records_to_table, table_name, **kwargs)
        return await _record(rec, call, _status_rows)


class TracedConnection(TracingMixin, asyncpg.Connection):  # type: ignore[misc]
    """An asyncpg Connection that records statements into the active trace."""

    __slots__ = ()


_CLASSES: dict[type[Any], type[Any]] = {}


def traced_connection_class(base: type[Any]) -> type[Any]:
    """`base` (an asyncpg.Connection subclass) with recording added. Built once per base."""
    if issubclass(base, TracingMixin):
        return base
    if base not in _CLASSES:
        name = f"Traced{base.__name__}"
        _CLASSES[base] = type(name, (TracingMixin, base), {"__slots__": (), "__module__": __name__})
    return _CLASSES[base]
