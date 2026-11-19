"""Template-string queries (Python 3.14+). Skipped from collection on older Pythons."""

from __future__ import annotations

from typing import Any

import psycopg

import pgsql_loupe


def test_template_query_keeps_placeholders_and_redacts_values(
    conn: psycopg.Connection[Any],
) -> None:
    user_id = 7
    password = "hunter2"
    with pgsql_loupe.trace() as t:
        row = conn.execute(t"SELECT {user_id}::int, {password}::text").fetchone()
    assert row == (7, "hunter2")
    (s,) = t.statements
    assert s.sql == "SELECT {user_id}::int, {password}::text"
    assert s.params == {"user_id": "7", "password": "<redacted>"}
