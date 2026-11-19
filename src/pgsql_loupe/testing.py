"""Query assertions for tests. The pytest plugin's `loupe` fixture is a `QueryRecorder`.

    def test_artists(loupe, client):
        with loupe.record() as r:
            client.get("/artists/tracks")
        r.assert_max_queries(2)
        r.assert_no_nplus1()
        r.assert_no_seq_scan("example_tracks")

A failing assertion lists every statement involved with its parameters, call site and time.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import Token

from pgsql_loupe.analyzers import AnalyzerOptions, analyze, fingerprint
from pgsql_loupe.core.trace import Statement, Trace, _current

__all__ = ["QueryRecorder"]

# Transaction control is not counted: asyncpg records BEGIN/COMMIT, psycopg does not, and a
# query budget should not depend on the driver.
_TRANSACTION_CONTROL = re.compile(
    r"^\s*(BEGIN|START\s+TRANSACTION|COMMIT|END|ROLLBACK|SAVEPOINT|RELEASE)\b", re.IGNORECASE
)


def _where(statement: Statement) -> str:
    site = statement.call_site
    if site is None:
        return "unknown caller"
    try:
        path = os.path.relpath(site.file)
    except ValueError:  # another drive on Windows
        path = site.file
    return f"{path}:{site.line} in {site.function}()"


def describe(statements: list[Statement], indexes: list[int] | None = None) -> str:
    """Numbered lines: SQL, parameters, call site and duration."""
    chosen = range(len(statements)) if indexes is None else indexes
    lines: list[str] = []
    for i in chosen:
        s = statements[i]
        sql = " ".join(s.sql.split())
        duration = f"{s.duration_ms:.2f} ms" if s.duration_ms is not None else "running"
        lines.append(f"  #{i} {sql}")
        lines.append(f"      params: {s.params} | {_where(s)} | {duration}")
        if s.error:
            lines.append(f"      error: {s.error} {s.sqlstate or ''}".rstrip())
    return "\n".join(lines)


class QueryRecorder:
    """Statements recorded into one trace, with assertions over them."""

    def __init__(
        self,
        trace: Trace | None = None,
        *,
        dsn: str | None = None,
        count_transaction_control: bool = False,
    ) -> None:
        self.trace = trace if trace is not None else Trace(label="test")
        self.dsn = dsn
        self.count_transaction_control = count_transaction_control
        self._token: Token[Trace | None] | None = None

    # --- recording ---------------------------------------------------------------------

    def start(self) -> None:
        self._token = _current.set(self.trace)

    def stop(self) -> None:
        if self._token is not None:
            # A reset from another context raises ValueError: leave the variable alone then.
            with suppress(ValueError):
                _current.reset(self._token)
            self._token = None

    @contextmanager
    def record(self) -> Iterator[QueryRecorder]:
        """Record only the statements run inside the block, into a new recorder."""
        inner = QueryRecorder(
            dsn=self.dsn, count_transaction_control=self.count_transaction_control
        )
        inner.start()
        try:
            yield inner
        finally:
            inner.stop()

    def reset(self) -> None:
        """Forget everything recorded so far."""
        self.trace.statements.clear()

    @property
    def statements(self) -> list[Statement]:
        """Recorded statements, without transaction control unless asked to count it."""
        if self.count_transaction_control:
            return list(self.trace.statements)
        return [s for s in self.trace.statements if not _TRANSACTION_CONTROL.match(s.sql)]

    # --- assertions --------------------------------------------------------------------

    def assert_max_queries(self, limit: int) -> None:
        __tracebackhide__ = True  # pytest: point the failure at the test, not here
        statements = self.statements
        if len(statements) > limit:
            raise AssertionError(
                f"expected at most {limit} queries, {len(statements)} ran:\n" + describe(statements)
            )

    def assert_num_queries(self, expected: int) -> None:
        __tracebackhide__ = True  # pytest: point the failure at the test, not here
        statements = self.statements
        if len(statements) != expected:
            raise AssertionError(
                f"expected exactly {expected} queries, {len(statements)} ran:\n"
                + describe(statements)
            )

    def assert_no_nplus1(self, threshold: int | None = None) -> None:
        __tracebackhide__ = True  # pytest: point the failure at the test, not here
        statements = self.statements
        options = AnalyzerOptions() if threshold is None else AnalyzerOptions(threshold)
        found = analyze(statements, options=options).nplus1
        if found:
            parts = []
            for shape in found:
                sites = ", ".join(shape.call_sites) or "unknown caller"
                parts.append(
                    f"N+1: {shape.fingerprint!r} ran {shape.count} times "
                    f"with {shape.distinct_values} different values, from {sites}:\n"
                    + describe(statements, shape.statements)
                )
            raise AssertionError("\n".join(parts))

    def assert_no_seq_scan(self, table: str, *, dsn: str | None = None) -> None:
        """No statement mentioning `table` is planned with a sequential scan on it.

        Statements are replayed under plain EXPLAIN (not executed) on `dsn`, so the data they
        need must be committed: a test that keeps everything in an open transaction cannot
        be explained from another connection.
        """
        __tracebackhide__ = True
        from pgsql_loupe.explain.capture import capture_plans
        from pgsql_loupe.explain.options import ExplainOptions
        from pgsql_loupe.explain.plan import walk

        target = dsn or self.dsn
        if not target:
            raise AssertionError(
                "assert_no_seq_scan needs a database to run EXPLAIN on: pass dsn=, use "
                "--pgsql-loupe-dsn, the pgsql_loupe_dsn ini option, or PGSQL_LOUPE_TEST_DSN"
            )
        name = table.rsplit(".", 1)[-1].strip('"').lower()
        mentions = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
        statements = self.statements
        candidates = [i for i, s in enumerate(statements) if mentions.search(s.sql)]
        for i in candidates:
            statements[i].plan = None
        options = ExplainOptions(dsn=target, analyze_reads=False)
        capture_plans([statements[i] for i in candidates], options)
        offenders: list[int] = []
        failures: list[str] = []
        for i in candidates:
            plan = statements[i].plan
            if plan is None or plan.mode == "skipped":
                continue
            if plan.root is None:
                failures.append(f"  #{i}: could not be explained: {plan.error}")
                continue
            for node in walk(plan.root):
                relation = (node.relation or "").lower()
                if node.node_type.endswith("Seq Scan") and relation == name:
                    offenders.append(i)
                    break
        if failures:
            raise AssertionError(
                f"assert_no_seq_scan({table!r}) could not check every statement:\n"
                + "\n".join(failures)
            )
        if offenders:
            raise AssertionError(f"sequential scan on {table}:\n" + describe(statements, offenders))

    def fingerprints(self) -> list[str]:
        """The shape of each recorded statement, handy for exact assertions."""
        return [fingerprint(s.sql) for s in self.statements]
