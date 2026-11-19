from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import psycopg
import pytest

from pgsql_loupe.collectors.psycopg import instrument

# Template-string tests use t"..." syntax, which older Pythons cannot even parse.
collect_ignore = ["test_psycopg_py314.py"] if sys.version_info < (3, 14) else []


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    """psycopg's async mode needs a selector loop; Windows defaults to the proactor loop."""
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    """DSN of the real PostgreSQL the tests run against. Missing DSN fails, never skips."""
    dsn = os.environ.get("TEST_PG_DSN")
    if not dsn:
        pytest.fail("TEST_PG_DSN is not set; start a database with `docker compose up -d --wait`")
    return dsn


@pytest.fixture
def conn(pg_dsn: str) -> Iterator[psycopg.Connection[Any]]:
    """An instrumented sync connection. Temp tables vanish when it closes."""
    with psycopg.connect(pg_dsn) as connection:
        instrument(connection)
        yield connection


@pytest.fixture
async def aconn(pg_dsn: str) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """An instrumented async connection."""
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        instrument(connection)
        yield connection
