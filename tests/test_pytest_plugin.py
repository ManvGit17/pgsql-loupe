"""The pytest plugin: the `loupe` fixture and its assertions, against a real PostgreSQL."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from pgsql_loupe.testing import QueryRecorder
from tests.test_example_fastapi import DRIVERS, load_example

Conn = psycopg.Connection[Any]
LOCAL = ("127.0.0.1", 50000)


@pytest.fixture
def table(pg_dsn: str, conn: Conn) -> Iterator[str]:
    """A committed table (EXPLAIN runs on another connection) with an index on `id` only.

    Depends on `conn` so it is torn down first: the test's open transaction is rolled back
    before DROP TABLE, which would otherwise wait for that transaction's lock forever."""
    name = f"plug_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(pg_dsn, autocommit=True) as c:
        c.execute(f"CREATE TABLE {name} (id int PRIMARY KEY, kind text)")
        c.execute(f"INSERT INTO {name} SELECT g, 'k' || (g % 9) FROM generate_series(1, 20000) g")
        c.execute(f"ANALYZE {name}")
    yield name
    conn.rollback()
    with psycopg.connect(pg_dsn, autocommit=True) as c:
        c.execute("SET lock_timeout = '5s'")  # fail fast instead of hanging
        c.execute(f"DROP TABLE {name}")


def test_fixture_records_the_test(loupe: QueryRecorder, conn: Conn) -> None:
    conn.execute("SELECT 1")
    conn.execute("SELECT 2")
    loupe.assert_max_queries(2)
    loupe.assert_num_queries(2)
    with pytest.raises(AssertionError) as failure:
        loupe.assert_max_queries(1)
    message = str(failure.value)
    assert message.startswith("expected at most 1 queries, 2 ran:")
    assert "#0 SELECT 1" in message and "#1 SELECT 2" in message
    assert "test_pytest_plugin.py:" in message and "in test_fixture_records_the_test()" in message


def test_record_narrows_to_a_block_and_reset_clears(loupe: QueryRecorder, conn: Conn) -> None:
    conn.execute("SELECT 'setup'")
    with loupe.record() as r:
        conn.execute("SELECT 'measured'")
    conn.execute("SELECT 'after'")
    assert [s.sql for s in r.statements] == ["SELECT 'measured'"]
    assert [s.sql for s in loupe.statements] == ["SELECT 'setup'", "SELECT 'after'"]
    loupe.reset()
    loupe.assert_num_queries(0)


def test_transaction_control_is_not_counted(loupe: QueryRecorder, conn: Conn) -> None:
    conn.execute("BEGIN")
    conn.execute("SELECT 1")
    conn.execute("COMMIT")
    loupe.assert_num_queries(1)
    counting = QueryRecorder(loupe.trace, count_transaction_control=True)
    counting.assert_num_queries(3)


def test_nplus1_assertion(loupe: QueryRecorder, conn: Conn) -> None:
    for n in range(4):
        conn.execute("SELECT %s::int", (n,))
    with pytest.raises(AssertionError) as failure:
        loupe.assert_no_nplus1()
    message = str(failure.value)
    assert "N+1: 'select ?::int' ran 4 times with 4 different values" in message
    assert message.count("test_pytest_plugin.py:") >= 4
    loupe.assert_no_nplus1(threshold=5)


def test_seq_scan_assertion(loupe: QueryRecorder, conn: Conn, table: str, pg_dsn: str) -> None:
    with loupe.record() as by_key:
        conn.execute(f"SELECT * FROM {table} WHERE id = %s", (7,))
    by_key.assert_no_seq_scan(table, dsn=pg_dsn)
    with loupe.record() as by_kind:
        conn.execute(f"SELECT count(*) FROM {table} WHERE kind = %s", ("k1",))
    with pytest.raises(AssertionError) as failure:
        by_kind.assert_no_seq_scan(table, dsn=pg_dsn)
    message = str(failure.value)
    assert message.startswith(f"sequential scan on {table}:")
    assert "WHERE kind = %s" in message and """params: ["'k1'"] | """ in message


def test_seq_scan_assertion_does_not_run_the_query_again(
    loupe: QueryRecorder, conn: Conn, table: str, pg_dsn: str
) -> None:
    conn.execute(f"UPDATE {table} SET kind = 'changed' WHERE id = %s", (1,))
    conn.commit()
    loupe.assert_no_seq_scan(table, dsn=pg_dsn)  # plain EXPLAIN: nothing executed
    row = conn.execute(f"SELECT kind FROM {table} WHERE id = 1").fetchone()
    assert row == ("changed",)


def test_seq_scan_assertion_needs_a_dsn(loupe: QueryRecorder, conn: Conn) -> None:
    conn.execute("SELECT 1")
    no_dsn = QueryRecorder(loupe.trace)
    with pytest.raises(AssertionError, match="needs a database"):
        no_dsn.assert_no_seq_scan("anything")


def test_seq_scan_assertion_fails_loudly_when_it_cannot_explain(
    loupe: QueryRecorder, conn: Conn, pg_dsn: str
) -> None:
    conn.execute("CREATE TEMP TABLE scratch (id int)")
    conn.execute("SELECT * FROM scratch")  # a temp table: invisible to another connection
    with pytest.raises(AssertionError, match="could not check every statement"):
        loupe.assert_no_seq_scan("scratch", dsn=pg_dsn)


@pytest.mark.parametrize("driver", DRIVERS)
def test_with_the_example_app_through_testclient(
    loupe: QueryRecorder, monkeypatch: pytest.MonkeyPatch, pg_dsn: str, driver: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    monkeypatch.setenv("EXAMPLE_DRIVER", driver)
    example = load_example()
    with TestClient(example.app, client=LOCAL) as client:  # startup SQL is outside the block
        with loupe.record() as fixed:
            client.get("/artists/tracks-fixed")
        with loupe.record() as slow:
            client.get("/artists/tracks")
    fixed.assert_max_queries(2)
    fixed.assert_no_nplus1()
    with pytest.raises(AssertionError, match=r"N\+1"):
        slow.assert_no_nplus1()
