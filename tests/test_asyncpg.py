"""asyncpg collector (TracedConnection) against a real PostgreSQL."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest

import pgsql_loupe
from pgsql_loupe.collectors.asyncpg import TracedConnection, traced_connection_class
from pgsql_loupe.explain import ExplainOptions, capture_plans


@pytest.fixture
async def conn(pg_dsn: str) -> AsyncIterator[Any]:
    c = await asyncpg.connect(pg_dsn, connection_class=TracedConnection)
    yield c
    await c.close()


async def test_statements_are_recorded(conn: Any) -> None:
    async with pgsql_loupe.trace() as t:
        await conn.execute("CREATE TEMP TABLE a (id int, name text)")
        await conn.execute("INSERT INTO a VALUES ($1, $2), ($3, $4)", 1, "x", 2, "y")
        rows = await conn.fetch("SELECT * FROM a ORDER BY id")
        row = await conn.fetchrow("SELECT name FROM a WHERE id = $1", 2)
        value = await conn.fetchval("SELECT count(*) FROM a")
        await conn.execute("UPDATE a SET name = $1", "z")
    assert (len(rows), row["name"], value) == (2, "y", 2)
    sqls = [s.sql for s in t.statements]
    assert sqls[2] == "SELECT * FROM a ORDER BY id"
    assert [s.rowcount for s in t.statements] == [None, 2, 2, 1, None, 2]
    assert t.statements[1].params == ["1", "'x'", "2", "'y'"]
    assert t.statements[0].call_site is not None
    assert t.statements[0].call_site.file == __file__
    assert {s.backend_pid for s in t.statements} == {conn.get_server_pid()}
    assert t.statements[0].tx_status == "IDLE"


async def test_errors_are_recorded_and_unchanged(conn: Any) -> None:
    async with pgsql_loupe.trace() as t:
        with pytest.raises(asyncpg.UndefinedTableError):
            await conn.fetch("SELECT * FROM no_such_table")
    (s,) = t.statements
    assert (s.error, s.sqlstate) == ("UndefinedTableError", "42P01")


async def test_executemany_and_copy(conn: Any) -> None:
    await conn.execute("CREATE TEMP TABLE m (id int)")
    async with pgsql_loupe.trace() as t:
        await conn.executemany("INSERT INTO m VALUES ($1)", ((i,) for i in range(4)))
        await conn.copy_records_to_table("m", records=[(10,), (11,)])
    assert await conn.fetchval("SELECT count(*) FROM m") == 6
    many, copy = t.statements
    assert (many.kind, many.param_sets, many.params) == ("executemany", 4, ["0"])
    assert (copy.kind, copy.sql, copy.rowcount) == ("copy", "COPY m FROM STDIN", 2)


async def test_transaction_status(conn: Any) -> None:
    async with pgsql_loupe.trace() as t, conn.transaction():
        await conn.fetchval("SELECT 1")
    # asyncpg sends BEGIN/COMMIT through the public execute(), so they are recorded too.
    assert [(s.sql, s.tx_status) for s in t.statements] == [
        ("BEGIN;", "IDLE"),
        ("SELECT 1", "INTRANS"),
        ("COMMIT;", "INTRANS"),
    ]


async def test_pool_and_custom_connection_class(pg_dsn: str) -> None:
    class MyConnection(asyncpg.Connection):  # type: ignore[misc]
        def greeting(self) -> str:
            return "hello"

    cls = traced_connection_class(MyConnection)
    assert traced_connection_class(MyConnection) is cls
    pool = asyncpg.create_pool(pg_dsn, min_size=1, max_size=1, connection_class=cls)
    async with pool, pool.acquire() as c, pgsql_loupe.trace() as t:
        assert c.greeting() == "hello"
        await c.fetchval("SELECT 1")
    assert [s.sql for s in t.statements] == ["SELECT 1"]


async def test_concurrent_tasks_keep_separate_traces(pg_dsn: str) -> None:
    async def request(tag: str) -> pgsql_loupe.Trace:
        c = await asyncpg.connect(pg_dsn, connection_class=TracedConnection)
        try:
            async with pgsql_loupe.trace(tag) as t:
                await c.fetchval("SELECT $1::text, pg_sleep(0.2)", tag)
            return t
        finally:
            await c.close()

    traces = await asyncio.gather(*(request(tag) for tag in "ABC"))
    for tag, t in zip("ABC", traces, strict=True):
        assert [s.params for s in t.statements] == [[repr(tag)]]


async def test_statements_replay_for_explain(conn: Any, pg_dsn: str) -> None:
    async with pgsql_loupe.trace() as t:
        await conn.fetch("SELECT relname FROM pg_class WHERE oid = $1", 1259)
    capture_plans(t.statements, ExplainOptions(dsn=pg_dsn))
    plan = t.statements[0].plan
    assert plan is not None and plan.mode == "analyze", plan


async def test_not_recorded_prepared_statements_and_no_trace(conn: Any) -> None:
    assert await conn.fetchval("SELECT 1") == 1  # no trace: nothing recorded, works
    async with pgsql_loupe.trace() as t:
        stmt = await conn.prepare("SELECT 2")
        await stmt.fetchval()
    assert t.statements == []  # documented limitation: prepared statements are not recorded


async def test_pool_reset_is_not_recorded(pg_dsn: str) -> None:
    pool = asyncpg.create_pool(pg_dsn, min_size=1, max_size=1, connection_class=TracedConnection)
    async with pool, pgsql_loupe.trace() as t, pool.acquire() as c:
        await c.fetchval("SELECT 1")
        # Releasing ran asyncpg's reset (RESET ALL, UNLISTEN *, ...) inside the trace.
    assert [s.sql for s in t.statements] == ["SELECT 1"]
