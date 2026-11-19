"""The per-request trace and the statements recorded into it.

The active trace lives in a ContextVar. asyncio copies the current context into every
task it creates, so each request (or each `trace()` block) gets its own trace even when
many run concurrently on one event loop.
"""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal

from pgsql_loupe.core.callsite import CallSite

if TYPE_CHECKING:
    from pgsql_loupe.explain.plan import PlanResult

StatementKind = Literal["execute", "executemany", "stream", "copy", "declare"]

_current: ContextVar[Trace | None] = ContextVar("pgsql_loupe_trace", default=None)


@dataclass(frozen=True)
class Replay:
    """What is needed to run a statement again for EXPLAIN. Never served by the API."""

    query: Any
    """The query object the user passed (str, bytes, sql.Composed or a template string)."""
    params: Any
    """A shallow copy of the original parameters (for executemany: the first set)."""
    raw: bool = False
    """True if the statement used $1-style placeholders (a psycopg RawCursor)."""


@dataclass
class Statement:
    """One statement sent to PostgreSQL. Parameter values are stored redacted, as text."""

    sql: str
    params: list[str] | dict[str, str] | None
    kind: StatementKind
    start_ms: float
    """Milliseconds from the start of the trace to the start of this statement."""
    duration_ms: float | None = None
    rowcount: int | None = None
    param_sets: int | None = None
    """For executemany: how many parameter sets ran. `params` holds the first one."""
    error: str | None = None
    sqlstate: str | None = None
    error_message: str | None = None
    call_site: CallSite | None = None
    tx_status: str | None = None
    """Transaction status before the statement ran: IDLE, INTRANS, INERROR, ..."""
    backend_pid: int | None = None
    plan: PlanResult | None = None
    """Filled in by plan capture (?lens=plan or the explain endpoint)."""
    replay: Replay | None = field(default=None, repr=False, compare=False)


@dataclass
class Trace:
    """Every statement recorded while this trace was active, in start order."""

    label: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_ns: int = field(default_factory=time.perf_counter_ns)
    statements: list[Statement] = field(default_factory=list)

    def elapsed_ms(self, now_ns: int | None = None) -> float:
        now = time.perf_counter_ns() if now_ns is None else now_ns
        return (now - self.started_ns) / 1_000_000

    @property
    def total_ms(self) -> float:
        """Sum of statement durations (statements still running count as 0)."""
        return sum(s.duration_ms or 0.0 for s in self.statements)


def current_trace() -> Trace | None:
    """The trace statements are recorded into right now, or None."""
    return _current.get()


class trace:  # lower-case: used like a function, `with pgsql_loupe.trace() as t:`
    """Record every statement run inside the block. Works with `with` and `async with`.

    Nested blocks record into the innermost trace only.
    """

    def __init__(self, label: str | None = None) -> None:
        self._trace = Trace(label=label)
        self._token: Token[Trace | None] | None = None

    def __enter__(self) -> Trace:
        if self._token is not None:
            raise RuntimeError("this trace() block is already active")
        self._token = _current.set(self._trace)
        return self._trace

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._token is not None:
            _current.reset(self._token)
            self._token = None

    async def __aenter__(self) -> Trace:
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.__exit__(exc_type, exc, tb)
