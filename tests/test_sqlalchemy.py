"""SQLAlchemy 2 collector: sync and async engines on psycopg and asyncpg, real PostgreSQL."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import psycopg
import pytest
from sqlalchemy import Engine, create_engine, event, exc, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import pgsql_loupe
from pgsql_loupe.collectors.psycopg import instrument
from pgsql_loupe.collectors.sqlalchemy import instrument_engine
from pgsql_loupe.explain import ExplainOptions, capture_plans
from tests.test_psycopg_sync import TEN


def url(dsn: str, driver: str) -> str:
    return dsn.replace("postgresql://", f"postgresql+{driver}://", 1)


@pytest.fixture
def engine(pg_dsn: str) -> Iterator[Engine]:
    e = create_engine(url(pg_dsn, "psycopg"))
    instrument_engine(e)
    yield e
    e.dispose()


@pytest.fixture
async def apg_engine(pg_dsn: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(url(pg_dsn, "asyncpg"))
    instrument_engine(e)
    yield e
    await e.dispose()


def test_ten_statements_sync_psycopg(engine: Engine) -> None:
    with engine.connect() as conn, pgsql_loupe.trace() as t:
        for query, params in TEN:
            conn.exec_driver_sql(query, params)
    assert [s.sql for s in t.statements] == [q for q, _ in TEN]
    assert all(s.duration_ms is not None and s.error is None for s in t.statements)
    assert t.statements[1].params == ["1", "'a'"]
    assert t.statements[3].rowcount == 2
    assert t.statements[0].call_site is not None
    assert t.statements[0].call_site.file == __file__
    assert t.statements[0].backend_pid is not None


async def test_async_asyncpg_engine_records_with_call_site(apg_engine: AsyncEngine) -> None:
    async with apg_engine.connect() as conn, pgsql_loupe.trace() as t:
        await conn.execute(text("SELECT CAST(:n AS int)"), {"n": 7})
        await conn.execute(text("SELECT generate_series(1, 3)"))
    first, second = t.statements
    assert first.sql == "SELECT CAST($1 AS int)" and first.params == ["7"]
    assert second.rowcount == 3
    # The driver call runs in a child greenlet; the call site comes from the parent's frames.
    assert first.call_site is not None and first.call_site.file == __file__
    assert first.call_site.function == "test_async_asyncpg_engine_records_with_call_site"


def test_errors_are_recorded_with_sqlstate(engine: Engine) -> None:
    with engine.connect() as conn, pgsql_loupe.trace() as t:
        with pytest.raises(exc.ProgrammingError):
            conn.execute(text("SELECT * FROM no_such_table"))
        conn.rollback()
    (s,) = t.statements
    assert (s.error, s.sqlstate) == ("UndefinedTable", "42P01")


async def test_async_errors_are_recorded_with_sqlstate(apg_engine: AsyncEngine) -> None:
    async with apg_engine.connect() as conn, pgsql_loupe.trace() as t:
        with pytest.raises(exc.DBAPIError):
            await conn.execute(text("SELECT 1 / 0"))
    (s,) = t.statements
    assert s.sqlstate == "22012"


def test_executemany_records_first_set_and_count(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TEMP TABLE m (id int)")
        with pgsql_loupe.trace() as t:
            conn.exec_driver_sql("INSERT INTO m VALUES (%(id)s)", [{"id": 1}, {"id": 2}, {"id": 3}])
        assert conn.exec_driver_sql("SELECT count(*) FROM m").scalar() == 3
    (s,) = t.statements
    assert (s.kind, s.param_sets, s.params) == ("executemany", 3, {"id": "1"})


def test_not_recorded_twice_on_instrumented_psycopg(pg_dsn: str) -> None:
    e = create_engine(url(pg_dsn, "psycopg"))
    event.listen(e, "connect", lambda dbapi_conn, _: instrument(dbapi_conn))
    with e.connect() as conn, pgsql_loupe.trace() as only_psycopg:
        conn.execute(text("SELECT 1"))
    instrument_engine(e)
    with e.connect() as conn, pgsql_loupe.trace() as both:
        conn.execute(text("SELECT 2"))
        conn.exec_driver_sql("SELECT %s::int", (3,))
    e.dispose()
    assert [s.sql for s in only_psycopg.statements] == ["SELECT 1"]
    assert [s.sql for s in both.statements] == ["SELECT 2", "SELECT %s::int"]


async def test_not_recorded_twice_on_instrumented_async_psycopg(pg_dsn: str) -> None:
    e = create_async_engine(url(pg_dsn, "psycopg"))
    event.listen(
        e.sync_engine, "connect", lambda dbapi_conn, _: instrument(dbapi_conn.driver_connection)
    )
    instrument_engine(e)
    async with e.connect() as conn, pgsql_loupe.trace() as t:
        await conn.execute(text("SELECT 1"))
    await e.dispose()
    assert [s.sql for s in t.statements] == ["SELECT 1"]


def test_cursor_mark_is_removed_after_each_statement(pg_dsn: str) -> None:
    e = create_engine(url(pg_dsn, "psycopg"))
    event.listen(e, "connect", lambda dbapi_conn, _: instrument(dbapi_conn))
    instrument_engine(e)
    with e.connect() as conn:
        raw: Any = conn.connection.driver_connection
        assert isinstance(raw, psycopg.Connection)
        with pgsql_loupe.trace() as t:
            conn.execute(text("SELECT 1"))
            raw.execute("SELECT 'psycopg directly'")  # outside SQLAlchemy: psycopg records it
    e.dispose()
    assert [s.sql for s in t.statements] == ["SELECT 1", "SELECT 'psycopg directly'"]


async def test_statements_replay_for_explain(
    engine: Engine, apg_engine: AsyncEngine, pg_dsn: str
) -> None:
    with engine.connect() as conn, pgsql_loupe.trace() as sync_trace:
        conn.execute(text("SELECT relname FROM pg_class WHERE oid = :oid"), {"oid": 1259})
    async with apg_engine.connect() as conn, pgsql_loupe.trace() as async_trace:
        await conn.execute(text("SELECT relname FROM pg_class WHERE oid = :oid"), {"oid": 1259})
    statements = sync_trace.statements + async_trace.statements
    capture_plans(statements, ExplainOptions(dsn=pg_dsn))
    assert [s.plan.mode if s.plan else None for s in statements] == ["analyze", "analyze"]
    assert statements[1].replay is not None and statements[1].replay.raw  # $1 placeholders


def test_nothing_recorded_without_trace_and_instrument_is_idempotent(engine: Engine) -> None:
    instrument_engine(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 41 + 1")).scalar() == 42
    with engine.connect() as conn, pgsql_loupe.trace() as t:
        conn.execute(text("SELECT 1"))
    assert len(t.statements) == 1


def test_a_crashing_handler_never_replaces_the_users_error(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(self: object, exc: BaseException) -> None:
        raise RuntimeError("bug in the tracer")

    monkeypatch.setattr("pgsql_loupe.core.record.Recording.fail", explode)
    with (
        engine.connect() as conn,
        pgsql_loupe.trace(),
        pytest.raises(exc.ProgrammingError, match="no_such_table"),
    ):
        conn.execute(text("SELECT * FROM no_such_table"))
