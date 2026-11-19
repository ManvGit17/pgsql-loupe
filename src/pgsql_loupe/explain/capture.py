"""Replay recorded statements under EXPLAIN on a separate connection.

Synchronous on purpose: the ASGI middleware runs it in a worker thread, which works on
every event loop (psycopg's async mode needs a selector loop on Windows).
See docs/adr/0003-plan-capture-safety.md for the rules.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg import sql

from pgsql_loupe.core.trace import Statement
from pgsql_loupe.explain.flags import FlagThresholds, add_flags
from pgsql_loupe.explain.plan import PlanResult, parse_document
from pgsql_loupe.explain.safety import classify

if sys.version_info >= (3, 14):
    from string.templatelib import Template
else:  # pragma: no cover - template strings need Python 3.14
    Template = None

ANALYZE_OPTIONS = "ANALYZE, BUFFERS, FORMAT JSON"
PLAIN_OPTIONS = "FORMAT JSON"


@dataclass(frozen=True)
class ExplainOptions:
    dsn: str
    """Connection used for replays. Never the application's own connection."""
    analyze_reads: bool = True
    """Run reads under EXPLAIN ANALYZE (read-only transaction). False: plain EXPLAIN only."""
    analyze_writes: bool = False
    """Run INSERT/UPDATE/DELETE under EXPLAIN ANALYZE (in a rolled-back transaction)."""
    timeout_ms: int = 5_000
    lock_timeout_ms: int = 1_000
    max_plans: int = 25
    """At most this many replays per request in ?lens=plan mode."""
    thresholds: FlagThresholds = field(default_factory=FlagThresholds)


def _with_prefix(query: Any, options: str) -> Any:
    prefix = f"EXPLAIN ({options}) "
    if isinstance(query, str):
        return prefix + query
    if isinstance(query, bytes):
        return prefix.encode() + query
    if isinstance(query, sql.Composable):
        return sql.SQL(prefix) + query
    if Template is not None and isinstance(query, Template):
        return Template(prefix) + query
    raise TypeError(f"cannot replay a query of type {type(query).__name__}")


def explain_statement(
    conn: psycopg.Connection[Any], statement: Statement, options: ExplainOptions
) -> PlanResult:
    """Explain one statement on `conn`, which must be in autocommit mode."""
    replay = statement.replay
    if replay is None:
        return PlanResult(mode="skipped", error="no replay data was recorded for this statement")
    kind = "none" if statement.kind == "copy" else classify(statement.sql)
    if kind == "none":
        return PlanResult(
            mode="skipped",
            error="only SELECT, INSERT, UPDATE, DELETE, MERGE and WITH are explained",
        )
    analyze = options.analyze_reads if kind == "read" else options.analyze_writes
    read_only = kind == "read" or not analyze
    cursor_class: type[psycopg.Cursor[Any]] = psycopg.RawCursor if replay.raw else psycopg.Cursor
    try:
        conn.execute("BEGIN READ ONLY" if read_only else "BEGIN")
        try:
            conn.execute(f"SET LOCAL statement_timeout = {int(options.timeout_ms)}")
            conn.execute(f"SET LOCAL lock_timeout = {int(options.lock_timeout_ms)}")
            cursor = cursor_class(conn)
            cursor.execute(
                _with_prefix(replay.query, ANALYZE_OPTIONS if analyze else PLAIN_OPTIONS),
                replay.params,
            )
            row = cursor.fetchone()
        finally:
            conn.execute("ROLLBACK")
    except psycopg.Error as exc:
        return PlanResult(
            mode="error",
            error=(str(exc).splitlines() or [type(exc).__name__])[0][:500],
            sqlstate=getattr(exc, "sqlstate", None),
        )
    if row is None:
        return PlanResult(mode="error", error="EXPLAIN returned no rows")
    return add_flags(parse_document(row[0][0], analyzed=analyze), options.thresholds)


def capture_plans(statements: Iterable[Statement], options: ExplainOptions) -> int:
    """Explain up to `options.max_plans` statements, sharing one connection. Identical
    statements (same SQL and parameters) are explained once. Returns replays run."""
    seen: dict[tuple[str, str], PlanResult] = {}
    todo = [s for s in statements if s.replay is not None and s.plan is None]
    if not todo:
        return 0
    try:
        conn = psycopg.connect(options.dsn, autocommit=True)
    except psycopg.Error as exc:
        failed = PlanResult(mode="error", error=f"could not connect for EXPLAIN: {exc}"[:500])
        for statement in todo:
            statement.plan = failed
        return 0
    runs = 0
    with conn:
        for statement in todo:
            assert statement.replay is not None
            key = (statement.sql, repr(statement.replay.params))
            if key in seen:
                statement.plan = seen[key]
                continue
            if runs >= options.max_plans:
                statement.plan = PlanResult(
                    mode="skipped", error=f"limit of {options.max_plans} plans per request reached"
                )
                continue
            statement.plan = seen[key] = explain_statement(conn, statement, options)
            runs += 1
    return runs
