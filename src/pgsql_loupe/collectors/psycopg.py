"""psycopg 3 collector.

`instrument(conn)` swaps the connection's cursor classes for subclasses of the classes
already there, with a mixin first in the MRO that records each statement into the active
trace. See docs/adr/0001-psycopg-hook.md for why this hook was chosen.

Two rules hold everywhere in this module:
- With no active trace, the original method runs directly.
- Recording never changes what the user's query does: if building the record fails,
  the statement runs unrecorded; if the statement raises, the error is recorded and the
  original exception is re-raised unchanged.
"""

from __future__ import annotations

import sys
import time
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from contextlib import asynccontextmanager, contextmanager
from functools import partial
from typing import TYPE_CHECKING, Any, TypeAlias, TypeVar

import psycopg

from pgsql_loupe.core.callsite import find_call_site
from pgsql_loupe.core.redact import redact_params
from pgsql_loupe.core.trace import Replay, Statement, StatementKind, Trace, current_trace

if sys.version_info >= (3, 14):
    from string.templatelib import Template
else:  # pragma: no cover - template strings need Python 3.14
    Template = None

__all__ = ["instrument", "instrument_async"]

T = TypeVar("T")

if TYPE_CHECKING:
    _CursorBase: TypeAlias = psycopg.Cursor[Any]
    _AsyncCursorBase: TypeAlias = psycopg.AsyncCursor[Any]
    _ServerCursorBase: TypeAlias = psycopg.ServerCursor[Any]
    _AsyncServerCursorBase: TypeAlias = psycopg.AsyncServerCursor[Any]
else:
    _CursorBase = _AsyncCursorBase = _ServerCursorBase = _AsyncServerCursorBase = object


# --- describing a statement -------------------------------------------------------------


def _describe(query: Any, params: Any, conn: Any) -> tuple[str, Any]:
    """SQL text to show, and the parameters to show with it."""
    if Template is not None and isinstance(query, Template):
        # Keep placeholders in the text; the interpolated values become named params,
        # so they go through redaction like any other parameter.
        parts: list[str] = []
        values: dict[str, Any] = {}
        for item in query:
            if isinstance(item, str):
                parts.append(item)
            else:
                spec = f":{item.format_spec}" if item.format_spec else ""
                parts.append(f"{{{item.expression}{spec}}}")
                values[item.expression] = item.value
        return "".join(parts), values
    if isinstance(query, str):
        return query, params
    if isinstance(query, bytes):
        return query.decode("utf-8", "replace"), params
    if isinstance(query, psycopg.sql.Composable):
        return query.as_string(conn), params
    return str(query), params


_RAW_CURSORS = (
    psycopg.RawCursor,
    psycopg.AsyncRawCursor,
    psycopg.RawServerCursor,
    psycopg.AsyncRawServerCursor,
)


def _copy_params(params: Any) -> Any:
    """A shallow copy, so later changes to the caller's list or dict don't alter the replay."""
    if isinstance(params, Mapping):
        return dict(params)
    if isinstance(params, Sequence) and not isinstance(params, (str, bytes)):
        return tuple(params)
    return params


def _replay(cursor: Any, query: Any, params: Any) -> Replay:
    if Template is not None and isinstance(query, Template):
        params = None  # the values live inside the template
    return Replay(query=query, params=_copy_params(params), raw=isinstance(cursor, _RAW_CURSORS))


def _rowcount(cursor: Any) -> int | None:
    count = cursor.rowcount
    return count if isinstance(count, int) and count >= 0 else None


class _Recording:
    """A statement that has started; `finish` or `fail` completes it."""

    __slots__ = ("started_ns", "statement")

    def __init__(self, statement: Statement, started_ns: int) -> None:
        self.statement = statement
        self.started_ns = started_ns

    def _stop(self) -> None:
        self.statement.duration_ms = (time.perf_counter_ns() - self.started_ns) / 1_000_000

    def finish(self, rowcount: int | None) -> None:
        self._stop()
        self.statement.rowcount = rowcount

    def fail(self, exc: BaseException) -> None:
        self._stop()
        self.statement.error = type(exc).__name__
        self.statement.sqlstate = getattr(exc, "sqlstate", None)
        self.statement.error_message = (str(exc).splitlines() or [""])[0][:500]


def _begin(
    trace: Trace, cursor: Any, kind: StatementKind, query: Any, params: Any
) -> _Recording | None:
    try:
        conn = cursor.connection
        text, shown = _describe(query, params, conn)
        info = conn.info
        started = time.perf_counter_ns()
        statement = Statement(
            sql=text,
            params=redact_params(shown),
            kind=kind,
            start_ms=trace.elapsed_ms(started),
            call_site=find_call_site(sys._getframe(1)),
            tx_status=info.transaction_status.name,
            backend_pid=info.backend_pid or None,
            replay=_replay(cursor, query, params),
        )
    except Exception:  # never let the tracer break the user's query
        return None
    trace.statements.append(statement)
    return _Recording(statement, started)


def _record_sync(
    cursor: Any, kind: StatementKind, query: Any, params: Any, call: Callable[[], T]
) -> T:
    trace = current_trace()
    rec = _begin(trace, cursor, kind, query, params) if trace is not None else None
    if rec is None:
        return call()
    try:
        result = call()
    except BaseException as exc:
        rec.fail(exc)
        raise
    rec.finish(_rowcount(cursor))
    return result


async def _record_async(
    cursor: Any, kind: StatementKind, query: Any, params: Any, call: Callable[[], Awaitable[T]]
) -> T:
    trace = current_trace()
    rec = _begin(trace, cursor, kind, query, params) if trace is not None else None
    if rec is None:
        return await call()
    try:
        result = await call()
    except BaseException as exc:
        rec.fail(exc)
        raise
    rec.finish(_rowcount(cursor))
    return result


class _CountingParams:
    """Wraps executemany's parameter iterable: counts sets and keeps the first one,
    without consuming a generator the user passed."""

    def __init__(self, params_seq: Iterable[Any]) -> None:
        self.count = 0
        self.first: Any = None
        self._source = params_seq

    def __iter__(self) -> Iterator[Any]:
        for item in self._source:
            if self.count == 0:
                self.first = item
            self.count += 1
            yield item


def _begin_many(
    cursor: Any, query: Any, params_seq: Iterable[Any]
) -> tuple[_Recording | None, Iterable[Any], _CountingParams | None]:
    trace = current_trace()
    if trace is None:
        return None, params_seq, None
    if isinstance(params_seq, Sequence):
        first = params_seq[0] if len(params_seq) else None
        rec = _begin(trace, cursor, "executemany", query, first)
        if rec is not None:
            rec.statement.param_sets = len(params_seq)
        return rec, params_seq, None
    counter = _CountingParams(params_seq)
    return _begin(trace, cursor, "executemany", query, None), counter, counter


def _finish_many(rec: _Recording, cursor: Any, counter: _CountingParams | None) -> None:
    if counter is not None:
        rec.statement.param_sets = counter.count
        rec.statement.params = redact_params(counter.first)
        if rec.statement.replay is not None:
            rec.statement.replay = _replay(cursor, rec.statement.replay.query, counter.first)
    rec.finish(_rowcount(cursor))


# --- mixins -----------------------------------------------------------------------------


class TracedCursorMixin(_CursorBase):
    """Records execute, executemany, stream and copy on a sync client-side cursor."""

    def execute(self, query: Any, params: Any = None, **kwargs: Any) -> Any:
        return _record_sync(
            self, "execute", query, params, partial(super().execute, query, params, **kwargs)
        )

    def executemany(self, query: Any, params_seq: Iterable[Any], **kwargs: Any) -> None:
        rec, params_seq, counter = _begin_many(self, query, params_seq)
        if rec is None:
            return super().executemany(query, params_seq, **kwargs)
        try:
            super().executemany(query, params_seq, **kwargs)
        except BaseException as exc:
            rec.fail(exc)
            raise
        _finish_many(rec, self, counter)

    def stream(self, query: Any, params: Any = None, **kwargs: Any) -> Iterator[Any]:
        trace = current_trace()
        rec = _begin(trace, self, "stream", query, params) if trace is not None else None
        if rec is None:
            yield from super().stream(query, params, **kwargs)
            return
        rows = 0
        try:
            for row in super().stream(query, params, **kwargs):
                rows += 1
                yield row
        except GeneratorExit:  # the caller stopped iterating early: not an error
            rec.finish(rows)
            raise
        except BaseException as exc:
            rec.fail(exc)
            raise
        rec.finish(rows)

    @contextmanager
    def copy(self, statement: Any, params: Any = None, **kwargs: Any) -> Iterator[Any]:
        trace = current_trace()
        rec = _begin(trace, self, "copy", statement, params) if trace is not None else None
        if rec is None:
            with super().copy(statement, params, **kwargs) as copy:
                yield copy
            return
        try:
            with super().copy(statement, params, **kwargs) as copy:
                yield copy
        except BaseException as exc:
            rec.fail(exc)
            raise
        rec.finish(_rowcount(self))


class AsyncTracedCursorMixin(_AsyncCursorBase):
    """Async twin of TracedCursorMixin."""

    async def execute(self, query: Any, params: Any = None, **kwargs: Any) -> Any:
        return await _record_async(
            self, "execute", query, params, partial(super().execute, query, params, **kwargs)
        )

    async def executemany(self, query: Any, params_seq: Iterable[Any], **kwargs: Any) -> None:
        rec, params_seq, counter = _begin_many(self, query, params_seq)
        if rec is None:
            return await super().executemany(query, params_seq, **kwargs)
        try:
            await super().executemany(query, params_seq, **kwargs)
        except BaseException as exc:
            rec.fail(exc)
            raise
        _finish_many(rec, self, counter)

    async def stream(self, query: Any, params: Any = None, **kwargs: Any) -> AsyncIterator[Any]:
        trace = current_trace()
        rec = _begin(trace, self, "stream", query, params) if trace is not None else None
        if rec is None:
            async for row in super().stream(query, params, **kwargs):
                yield row
            return
        rows = 0
        try:
            async for row in super().stream(query, params, **kwargs):
                rows += 1
                yield row
        except GeneratorExit:
            rec.finish(rows)
            raise
        except BaseException as exc:
            rec.fail(exc)
            raise
        rec.finish(rows)

    @asynccontextmanager
    async def copy(self, statement: Any, params: Any = None, **kwargs: Any) -> AsyncIterator[Any]:
        trace = current_trace()
        rec = _begin(trace, self, "copy", statement, params) if trace is not None else None
        if rec is None:
            async with super().copy(statement, params, **kwargs) as copy:
                yield copy
            return
        try:
            async with super().copy(statement, params, **kwargs) as copy:
                yield copy
        except BaseException as exc:
            rec.fail(exc)
            raise
        rec.finish(_rowcount(self))


class TracedServerCursorMixin(_ServerCursorBase):
    """Records the DECLARE of a sync server-side (named) cursor."""

    def execute(self, query: Any, params: Any = None, **kwargs: Any) -> Any:
        return _record_sync(
            self, "declare", query, params, partial(super().execute, query, params, **kwargs)
        )


class AsyncTracedServerCursorMixin(_AsyncServerCursorBase):
    """Records the DECLARE of an async server-side (named) cursor."""

    async def execute(self, query: Any, params: Any = None, **kwargs: Any) -> Any:
        return await _record_async(
            self, "declare", query, params, partial(super().execute, query, params, **kwargs)
        )


# --- installing -------------------------------------------------------------------------


_TRACED_CLASSES: dict[tuple[type[Any], type[Any]], type[Any]] = {}


def _traced(base: type[Any], mixin: type[Any]) -> type[Any]:
    """`base` with `mixin` in front, built once per (base, mixin) pair."""
    if issubclass(base, mixin):
        return base
    key = (base, mixin)
    if key not in _TRACED_CLASSES:
        name = f"Traced{base.__name__}"
        _TRACED_CLASSES[key] = type(name, (mixin, base), {"__module__": __name__})
    return _TRACED_CLASSES[key]


def _class_of(factory: Any, attribute: str) -> type[Any]:
    if not isinstance(factory, type):
        raise TypeError(
            f"pgsql-loupe can only instrument a connection whose {attribute} is a class, "
            f"got {factory!r}"
        )
    return factory


def instrument(conn: psycopg.Connection[Any] | psycopg.AsyncConnection[Any]) -> None:
    """Record this connection's statements into the active trace. Safe to call twice.

    Works for sync and async connections. For a pool, pass it as the configure hook:
    `ConnectionPool(dsn, configure=instrument)`; for `AsyncConnectionPool`, which needs an
    async hook, use `configure=instrument_async`.
    """
    if isinstance(conn, psycopg.AsyncConnection):
        cursor_mixin: type[Any] = AsyncTracedCursorMixin
        server_mixin: type[Any] = AsyncTracedServerCursorMixin
    elif isinstance(conn, psycopg.Connection):
        cursor_mixin, server_mixin = TracedCursorMixin, TracedServerCursorMixin
    else:
        raise TypeError(f"expected a psycopg connection, got {type(conn).__name__}")
    conn.cursor_factory = _traced(_class_of(conn.cursor_factory, "cursor_factory"), cursor_mixin)
    conn.server_cursor_factory = _traced(
        _class_of(conn.server_cursor_factory, "server_cursor_factory"), server_mixin
    )


async def instrument_async(conn: psycopg.AsyncConnection[Any]) -> None:
    """`instrument` as a coroutine, for `AsyncConnectionPool(configure=...)`."""
    instrument(conn)
