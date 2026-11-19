"""pytest plugin, registered through the `pytest11` entry point: the `loupe` fixture.

The fixture records every statement the test runs (including requests made through
Starlette's TestClient, which carries the test's context into the app). See
`pgsql_loupe.testing.QueryRecorder` for the assertions.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from pgsql_loupe.testing import QueryRecorder

DSN_ENV = "PGSQL_LOUPE_TEST_DSN"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("pgsql-loupe")
    group.addoption(
        "--pgsql-loupe-dsn",
        dest="pgsql_loupe_dsn",
        default=None,
        help=f"database for assert_no_seq_scan's EXPLAIN (default: ini or ${DSN_ENV})",
    )
    parser.addini("pgsql_loupe_dsn", "database for assert_no_seq_scan's EXPLAIN", default="")


def _dsn(config: pytest.Config) -> str | None:
    value = config.getoption("pgsql_loupe_dsn") or config.getini("pgsql_loupe_dsn")
    return str(value) if value else os.environ.get(DSN_ENV) or None


@pytest.fixture
def loupe(request: pytest.FixtureRequest) -> Iterator[QueryRecorder]:
    """Records the test's SQL statements; offers assert_max_queries, assert_no_nplus1 and
    assert_no_seq_scan, and `with loupe.record() as r:` for a narrower block."""
    recorder = QueryRecorder(dsn=_dsn(request.config))
    recorder.start()
    try:
        yield recorder
    finally:
        recorder.stop()
