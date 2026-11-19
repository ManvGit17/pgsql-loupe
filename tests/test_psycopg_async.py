"""psycopg 3 collector, async connections, against a real PostgreSQL."""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

import pgsql_loupe
from pgsql_loupe.collectors.psycopg import instrument, instrument_async
from tests.test_psycopg_sync import TEN

AConn = psycopg.AsyncConnection[Any]


async def test_ten_statements_are_recorded_in_order(aconn: AConn) -> None:
    async with pgsql_loupe.trace() as t:
        for query, params in TEN:
            await aconn.execute(query, params)

    assert [s.sql for s in t.statements] == [q for q, _ in TEN]
    assert all(s.kind == "execute" and s.error is None for s in t.statements)
    assert all(s.duration_ms is not None for s in t.statements)
    assert t.statements[3].rowcount == 2
    assert t.statements[0].call_site is not None
    assert t.statements[0].call_site.file == __file__


async def test_failing_statement_is_recorded_and_error_is_unchanged(aconn: AConn) -> None:
    async with pgsql_loupe.trace() as t:
        with pytest.raises(psycopg.errors.UndefinedTable):
            await aconn.execute("SELECT * FROM no_such_table")
    (s,) = t.statements
    assert (s.error, s.sqlstate) == ("UndefinedTable", "42P01")


async def test_concurrent_tasks_keep_separate_traces(pg_dsn: str) -> None:
    async def request(tag: str) -> pgsql_loupe.Trace:
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            instrument(c)
            async with pgsql_loupe.trace(tag) as t:
                await c.execute("SELECT %s, pg_sleep(0.2)", (tag,))
                await c.execute("SELECT %s", (tag,))
            return t

    traces = await asyncio.gather(*(request(tag) for tag in "ABC"))
    for tag, t in zip("ABC", traces, strict=True):
        assert [s.params for s in t.statements] == [[repr(tag)], [repr(tag)]]


async def test_tasks_started_inside_a_trace_record_into_it(pg_dsn: str) -> None:
    async def child(n: int) -> None:
        async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
            instrument(c)
            await c.execute("SELECT %s", (n,))

    async with pgsql_loupe.trace() as t:
        await asyncio.gather(child(1), child(2))
    assert sorted(str(s.params) for s in t.statements) == ["['1']", "['2']"]


async def test_executemany_stream_and_copy(aconn: AConn) -> None:
    await aconn.execute("CREATE TEMP TABLE a (id int)")
    async with pgsql_loupe.trace() as t:
        cur = aconn.cursor()
        await cur.executemany("INSERT INTO a VALUES (%s)", [(1,), (2,)])
        rows = [row async for row in cur.stream("SELECT id FROM a")]
        async with cur.copy("COPY a FROM STDIN") as copy:
            await copy.write_row((3,))
    assert rows == [(1,), (2,)]
    many, stream, copy_in = t.statements
    assert (many.kind, many.param_sets) == ("executemany", 2)
    assert (stream.kind, stream.rowcount) == ("stream", 2)
    assert (copy_in.kind, copy_in.rowcount) == ("copy", 1)


async def test_server_side_cursor_records_the_declare(aconn: AConn) -> None:
    async with aconn.transaction(), pgsql_loupe.trace() as t:
        cur = aconn.cursor("named")
        await cur.execute("SELECT 1")
        assert await cur.fetchall() == [(1,)]
        await cur.close()
    assert [s.kind for s in t.statements] == ["declare"]


async def test_async_pool_configure_hook(pg_dsn: str) -> None:
    async with (
        AsyncConnectionPool(pg_dsn, min_size=1, max_size=1, configure=instrument_async) as pool,
        pool.connection() as pooled,
        pgsql_loupe.trace() as t,
    ):
        await pooled.execute("SELECT 1")
    assert [s.sql for s in t.statements] == ["SELECT 1"]
