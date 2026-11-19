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


def test_template_query_can_be_replayed_for_explain(
    conn: psycopg.Connection[Any], pg_dsn: str
) -> None:
    from pgsql_loupe.explain import ExplainOptions, capture_plans

    n = 3
    with pgsql_loupe.trace() as t:
        conn.execute(t"SELECT g FROM generate_series(1, {n}) g")
    capture_plans(t.statements, ExplainOptions(dsn=pg_dsn))
    plan = t.statements[0].plan
    assert plan is not None and plan.mode == "analyze", plan
    assert plan.root is not None and plan.root.actual_rows == 3
