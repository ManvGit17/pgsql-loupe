"""psycopg 3 collector, sync connections, against a real PostgreSQL."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from psycopg import ClientCursor, RawCursor, sql
from psycopg_pool import ConnectionPool

import pgsql_loupe
from pgsql_loupe.collectors.psycopg import instrument

Conn = psycopg.Connection[Any]

# Ten mixed statements, used by the sync and async collector tests.
TEN: list[tuple[str, Any]] = [
    ("CREATE TEMP TABLE t (id int PRIMARY KEY, name text)", None),
    ("INSERT INTO t VALUES (%s, %s)", (1, "a")),
    ("INSERT INTO t VALUES (%(id)s, %(name)s)", {"id": 2, "name": "b"}),
    ("SELECT * FROM t ORDER BY id", None),
    ("UPDATE t SET name = %s WHERE id = %s", ("c", 1)),
    ("SELECT count(*) FROM t", None),
    ("DELETE FROM t WHERE id = %s", (2,)),
    ("SELECT name FROM t WHERE id = %s", (1,)),
    ("SELECT now()", None),
    ("DROP TABLE t", None),
]


def test_ten_statements_are_recorded_in_order(conn: Conn) -> None:
    with pgsql_loupe.trace() as t:
        for query, params in TEN:
            conn.execute(query, params)

    assert [s.sql for s in t.statements] == [q for q, _ in TEN]
    assert all(s.kind == "execute" and s.error is None for s in t.statements)
    assert all(s.duration_ms is not None and s.duration_ms >= 0 for s in t.statements)
    assert [s.rowcount for s in t.statements][1:3] == [1, 1]  # the two INSERTs
    assert t.statements[3].rowcount == 2
    assert t.statements[1].params == ["1", "'a'"]
    assert t.statements[2].params == {"id": "2", "name": "'b'"}
    assert {s.backend_pid for s in t.statements} == {conn.info.backend_pid}
    assert t.statements[0].call_site is not None
    assert t.statements[0].call_site.file == __file__
    starts = [s.start_ms for s in t.statements]
    assert starts == sorted(starts)


def test_failing_statement_is_recorded_and_error_is_unchanged(conn: Conn) -> None:
    with pgsql_loupe.trace() as t:
        conn.execute("BEGIN")
        with pytest.raises(psycopg.errors.DivisionByZero):
            conn.execute("SELECT 1 / 0")
        with pytest.raises(psycopg.errors.InFailedSqlTransaction):
            conn.execute("SELECT 1")
    failed = t.statements[1]
    assert (failed.error, failed.sqlstate) == ("DivisionByZero", "22012")
    assert failed.error_message is not None and "division by zero" in failed.error_message
    assert failed.duration_ms is not None
    assert t.statements[2].tx_status == "INERROR"
    assert t.statements[2].sqlstate == "25P02"


def test_nothing_is_recorded_without_a_trace(conn: Conn) -> None:
    assert pgsql_loupe.current_trace() is None
    assert conn.execute("SELECT 41 + 1").fetchone() == (42,)


def test_results_match_an_uninstrumented_connection(conn: Conn, pg_dsn: str) -> None:
    query = "SELECT g, md5(g::text) FROM generate_series(1, 50) g"
    with psycopg.connect(pg_dsn) as plain:
        expected = plain.execute(query).fetchall()
    with pgsql_loupe.trace():
        assert conn.execute(query).fetchall() == expected
    assert conn.execute(query).fetchall() == expected


def test_executemany_with_a_list(conn: Conn) -> None:
    conn.execute("CREATE TEMP TABLE m (id int, secret_token text)")
    rows = [(1, "x"), (2, "y"), (3, "z")]
    with pgsql_loupe.trace() as t:
        conn.cursor().executemany("INSERT INTO m VALUES (%s, %s)", rows)
    (s,) = t.statements
    assert (s.kind, s.param_sets, s.params) == ("executemany", 3, ["1", "'x'"])
    assert conn.execute("SELECT count(*) FROM m").fetchone() == (3,)


def test_executemany_with_a_generator_is_not_consumed_early(conn: Conn) -> None:
    conn.execute("CREATE TEMP TABLE m (id int)")
    with pgsql_loupe.trace() as t:
        conn.cursor().executemany("INSERT INTO m VALUES (%(id)s)", ({"id": i} for i in range(4)))
    (s,) = t.statements
    assert (s.param_sets, s.params) == (4, {"id": "0"})
    assert conn.execute("SELECT count(*) FROM m").fetchone() == (4,)


def test_stream_counts_rows_and_early_stop_is_not_an_error(conn: Conn) -> None:
    with pgsql_loupe.trace() as t:
        assert len(list(conn.cursor().stream("SELECT generate_series(1, 5)"))) == 5
        for i, _ in enumerate(conn.cursor().stream("SELECT generate_series(1, 5)")):
            if i == 1:
                break
    full, partial = t.statements
    assert (full.kind, full.rowcount, full.error) == ("stream", 5, None)
    assert (partial.rowcount, partial.error) == (2, None)


def test_copy_in_and_out(conn: Conn) -> None:
    conn.execute("CREATE TEMP TABLE c (id int, name text)")
    with pgsql_loupe.trace() as t:
        cur = conn.cursor()
        with cur.copy("COPY c (id, name) FROM STDIN") as copy:
            for row in [(1, "a"), (2, "b"), (3, "c")]:
                copy.write_row(row)
        with cur.copy("COPY c TO STDOUT") as copy:
            out = list(copy.rows())
    assert len(out) == 3
    copy_in, copy_out = t.statements
    assert (copy_in.kind, copy_in.rowcount) == ("copy", 3)
    assert copy_out.sql == "COPY c TO STDOUT"


def test_server_side_cursor_records_the_declare(conn: Conn) -> None:
    with conn.transaction(), pgsql_loupe.trace() as t:
        cur = conn.cursor("named")
        cur.execute("SELECT generate_series(1, 3)")
        assert cur.fetchall() == [(1,), (2,), (3,)]
        cur.close()
    (s,) = t.statements
    assert (s.kind, s.sql, s.tx_status) == ("declare", "SELECT generate_series(1, 3)", "INTRANS")


def test_users_cursor_class_is_kept(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn, cursor_factory=ClientCursor) as c1:
        instrument(c1)
        with pgsql_loupe.trace() as t:
            cur = c1.execute("SELECT %s::int", (7,))
        assert isinstance(cur, ClientCursor)
        assert cur.fetchone() == (7,)
    with psycopg.connect(pg_dsn, cursor_factory=RawCursor) as c2:
        instrument(c2)
        with pgsql_loupe.trace() as t2:
            raw = c2.execute("SELECT $1::int + $2::int", (1, 2))
        assert isinstance(raw, RawCursor)
        assert raw.fetchone() == (3,)
    assert t.statements[0].params == ["7"]
    assert t2.statements[0].sql == "SELECT $1::int + $2::int"


def test_composed_sql_is_rendered(conn: Conn) -> None:
    query = sql.SQL("SELECT {} FROM {}").format(
        sql.Identifier("relname"), sql.Identifier("pg_class")
    )
    with pgsql_loupe.trace() as t:
        conn.execute(query + sql.SQL(" LIMIT 1"))
    assert t.statements[0].sql == 'SELECT "relname" FROM "pg_class" LIMIT 1'


def test_secret_parameters_are_redacted_and_long_values_truncated(conn: Conn) -> None:
    params = {"password": "hunter2", "api_key": "k", "note": "x" * 1000}
    with pgsql_loupe.trace() as t:
        conn.execute("SELECT %(password)s, %(api_key)s, %(note)s", params)
    shown = t.statements[0].params
    assert isinstance(shown, dict)
    assert shown["password"] == shown["api_key"] == "<redacted>"
    assert len(shown["note"]) < 300 and shown["note"].endswith("(1002 chars)")


def test_pipeline_mode_statements_are_recorded(conn: Conn) -> None:
    with pgsql_loupe.trace() as t, conn.pipeline():
        conn.execute("SELECT 1")
        conn.execute("SELECT 2")
    assert [s.sql for s in t.statements] == ["SELECT 1", "SELECT 2"]


def test_instrument_is_idempotent(conn: Conn) -> None:
    factory = conn.cursor_factory
    instrument(conn)
    assert conn.cursor_factory is factory
    with pgsql_loupe.trace() as t:
        conn.execute("SELECT 1")
    assert len(t.statements) == 1


def test_nested_traces_record_into_the_innermost(conn: Conn) -> None:
    with pgsql_loupe.trace("outer") as outer:
        conn.execute("SELECT 'outer'")
        with pgsql_loupe.trace("inner") as inner:
            conn.execute("SELECT 'inner'")
        conn.execute("SELECT 'outer again'")
    assert [s.sql for s in outer.statements] == ["SELECT 'outer'", "SELECT 'outer again'"]
    assert [s.sql for s in inner.statements] == ["SELECT 'inner'"]


def test_pool_configure_hook(pg_dsn: str) -> None:
    with (
        ConnectionPool(pg_dsn, min_size=1, max_size=1, configure=instrument) as pool,
        pool.connection() as pooled,
        pgsql_loupe.trace() as t,
    ):
        pooled.execute("SELECT 1")
    assert [s.sql for s in t.statements] == ["SELECT 1"]


def test_a_broken_recorder_never_breaks_the_query(
    conn: Conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(params: object) -> None:
        raise RuntimeError("bug in the tracer")

    monkeypatch.setattr("pgsql_loupe.core.record.redact_params", explode)
    with pgsql_loupe.trace() as t:
        assert conn.execute("SELECT %s::int", (5,)).fetchone() == (5,)
    assert t.statements == []
