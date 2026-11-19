"""N+1, duplicate and summary analysis on statements recorded from a real PostgreSQL."""

from __future__ import annotations

from typing import Any

import psycopg

import pgsql_loupe
from pgsql_loupe.analyzers import AnalyzerOptions, analyze

Conn = psycopg.Connection[Any]


def test_loop_of_lookups_is_an_nplus1(conn: Conn) -> None:
    with pgsql_loupe.trace() as t:
        conn.execute("SELECT g FROM generate_series(1, 5) g")
        for n in range(5):
            conn.execute("SELECT %s::int + 1", (n,))  # one query per row
    analysis = analyze(t.statements)
    (shape,) = analysis.nplus1
    assert (shape.fingerprint, shape.count, shape.distinct_values) == ("select ?::int + ?", 5, 5)
    assert shape.statements == [1, 2, 3, 4, 5]
    (site,) = shape.call_sites
    assert site.startswith(__file__ + ":")
    assert analysis.duplicates == []


def test_below_the_threshold_is_not_flagged(conn: Conn) -> None:
    with pgsql_loupe.trace() as t:
        for n in range(2):
            conn.execute("SELECT %s::int", (n,))
    assert analyze(t.statements).nplus1 == []
    assert len(analyze(t.statements, options=AnalyzerOptions(nplus1_threshold=2)).nplus1) == 1


def test_identical_repeats_are_duplicates_not_nplus1(conn: Conn) -> None:
    with pgsql_loupe.trace() as t:
        for _ in range(4):
            conn.execute("SELECT %s::int", (7,))
    analysis = analyze(t.statements)
    assert analysis.nplus1 == []
    (dup,) = analysis.duplicates
    assert (dup.sql, dup.count, dup.statements) == ("SELECT %s::int", 4, [0, 1, 2, 3])


def test_redacted_values_do_not_create_false_duplicates(conn: Conn) -> None:
    with pgsql_loupe.trace() as t:
        conn.execute("SELECT %(password)s::text", {"password": "first"})
        conn.execute("SELECT %(password)s::text", {"password": "second"})
        conn.execute("SELECT %(password)s::text", {"password": "second"})
    assert t.statements[0].params == t.statements[1].params == {"password": "<redacted>"}
    (dup,) = analyze(t.statements).duplicates
    assert dup.statements == [1, 2]


def test_executemany_is_not_an_nplus1(conn: Conn) -> None:
    conn.execute("CREATE TEMP TABLE m (id int)")
    with pgsql_loupe.trace() as t:
        for _ in range(3):
            conn.cursor().executemany("INSERT INTO m VALUES (%s)", [(1,), (2,)])
    assert analyze(t.statements).nplus1 == []


def test_summary(conn: Conn) -> None:
    with pgsql_loupe.trace() as t:
        conn.execute("SELECT pg_sleep(0.12)")
        conn.execute("SELECT 1")
        try:
            conn.execute("SELECT 1 / 0")
        except psycopg.errors.DivisionByZero:
            conn.rollback()
    summary = analyze(t.statements, request_ms=1000.0).summary
    assert (summary.statement_count, summary.error_count, summary.slow_statements) == (3, 1, [0])
    assert summary.db_share is not None and 0.12 <= summary.db_share < 1.0
    assert analyze(t.statements).summary.db_share is None
