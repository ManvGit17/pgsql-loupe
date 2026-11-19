"""Starting and finishing one recorded statement. Shared by every collector.

The rule for collectors: if building the record fails, the statement runs unrecorded; if
the statement raises, the error is recorded and the original exception re-raised unchanged.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from types import FrameType
from typing import Any

from pgsql_loupe.core.callsite import find_call_site
from pgsql_loupe.core.redact import redact_params
from pgsql_loupe.core.trace import Replay, Statement, StatementKind, Trace

# Set on a DB-API cursor while a higher-level collector (SQLAlchemy) records the statement,
# so a lower-level collector (psycopg) on the same cursor does not record it a second time.
SKIP_ATTRIBUTE = "_pgsql_loupe_recorded_above"


def copy_params(params: Any) -> Any:
    """A shallow copy, so later changes to the caller's list or dict don't alter the replay."""
    if isinstance(params, Mapping):
        return dict(params)
    if isinstance(params, Sequence) and not isinstance(params, (str, bytes)):
        return tuple(params)
    return params


class Recording:
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
        self.statement.sqlstate = sqlstate_of(exc)
        self.statement.error_message = (str(exc).splitlines() or [""])[0][:500]


def sqlstate_of(exc: BaseException | None) -> str | None:
    """SQLSTATE from a driver error, or from the error it wraps (SQLAlchemy wraps drivers)."""
    seen = 0
    while exc is not None and seen < 5:
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(exc, attribute, None)
            if isinstance(value, str) and value:
                return value
        exc = getattr(exc, "orig", None) or exc.__cause__
        seen += 1
    return None


def begin(
    trace: Trace,
    *,
    kind: StatementKind,
    sql: str,
    shown_params: Any,
    replay: Replay | None,
    tx_status: str | None,
    backend_pid: int | None,
    frame: FrameType | None,
    param_sets: int | None = None,
) -> Recording:
    started = time.perf_counter_ns()
    statement = Statement(
        sql=sql,
        params=redact_params(shown_params),
        kind=kind,
        start_ms=trace.elapsed_ms(started),
        param_sets=param_sets,
        call_site=find_call_site(frame),
        tx_status=tx_status,
        backend_pid=backend_pid,
        replay=replay,
    )
    trace.statements.append(statement)
    return Recording(statement, started)
