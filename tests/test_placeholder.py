from __future__ import annotations

import os

import psycopg

import sqlloupe


def test_package_imports() -> None:
    assert sqlloupe.__version__


def test_real_postgres_is_reachable(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        row = conn.execute("SELECT current_setting('server_version_num')::int").fetchone()
    assert row is not None
    major = row[0] // 10000
    assert major >= 16
    # CI and the local matrix set this so each job proves it hit the intended server.
    expected = os.environ.get("EXPECT_PG_MAJOR")
    if expected:
        assert major == int(expected)
