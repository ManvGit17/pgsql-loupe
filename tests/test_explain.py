"""Plan capture against a real PostgreSQL: safety rules, parsing, flags."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from psycopg import sql

import pgsql_loupe
from pgsql_loupe.collectors.psycopg import instrument
from pgsql_loupe.core.trace import Statement
from pgsql_loupe.explain import ExplainOptions, FlagThresholds, capture_plans, classify
from pgsql_loupe.explain.flags import node_flags
from pgsql_loupe.explain.plan import PlanResult, parse_node

Conn = psycopg.Connection[Any]


@dataclass
class Tables:
    items: str
    audit: str
    seq: str


@pytest.fixture
def tables(pg_dsn: str) -> Iterator[Tables]:
    """Committed tables (the replay connection must see them) with an audit trigger."""
    suffix = uuid.uuid4().hex[:8]
    t = Tables(f"items_{suffix}", f"audit_{suffix}", f"seq_{suffix}")
    with psycopg.connect(pg_dsn, autocommit=True) as c:
        c.execute(f"""
            CREATE TABLE {t.items} (id int PRIMARY KEY, plays int NOT NULL DEFAULT 0, kind text);
            INSERT INTO {t.items} SELECT g, 0, 'k' || (g % 7) FROM generate_series(1, 20000) g;
            CREATE TABLE {t.audit} (item_id int, old_plays int, new_plays int);
            CREATE SEQUENCE {t.seq};
            CREATE FUNCTION log_{suffix}() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN INSERT INTO {t.audit} VALUES (OLD.id, OLD.plays, NEW.plays); RETURN NEW; END $$;
            CREATE TRIGGER audit_{suffix} AFTER UPDATE ON {t.items}
                FOR EACH ROW EXECUTE FUNCTION log_{suffix}();
            ANALYZE {t.items};
        """)
    yield t
    with psycopg.connect(pg_dsn, autocommit=True) as c:
        c.execute("SET lock_timeout = '5s'")  # fail fast if a test left a transaction open
        c.execute(f"DROP TABLE {t.items}, {t.audit}; DROP SEQUENCE {t.seq};")
        c.execute(f"DROP FUNCTION log_{suffix}()")


def state(conn: Conn, t: Tables) -> tuple[Any, ...]:
    """(plays of row 7, audit rows, sequence value). Ends its transaction so no lock is held."""
    row = conn.execute(
        f"SELECT (SELECT plays FROM {t.items} WHERE id = 7), (SELECT count(*) FROM {t.audit}),"
        f" (SELECT last_value FROM {t.seq})"
    ).fetchone()
    conn.rollback()
    assert row is not None
    return tuple(row)


def run_traced(conn: Conn, query: Any, params: Any = None) -> Statement:
    with pgsql_loupe.trace() as t:
        conn.execute(query, params)
    conn.commit()
    (statement,) = t.statements
    return statement


def plan_of(statement: Statement, options: ExplainOptions) -> PlanResult:
    capture_plans([statement], options)
    assert statement.plan is not None
    return statement.plan


# --- the three "done when" checks ---------------------------------------------------------


def test_select_gets_an_analysed_plan(conn: Conn, tables: Tables, pg_dsn: str) -> None:
    statement = run_traced(conn, f"SELECT * FROM {tables.items} WHERE id = %s", (7,))
    plan = plan_of(statement, ExplainOptions(dsn=pg_dsn))
    assert plan.mode == "analyze", plan.error
    assert plan.root is not None and plan.root.actual_rows == 1
    assert plan.root.index is not None  # primary key lookup
    assert plan.execution_ms is not None and plan.planning_ms is not None


def test_update_gets_a_plan_that_is_not_executed(conn: Conn, tables: Tables, pg_dsn: str) -> None:
    statement = run_traced(conn, f"UPDATE {tables.items} SET plays = plays + 1 WHERE id = %s", (7,))
    before = state(conn, tables)
    plan = plan_of(statement, ExplainOptions(dsn=pg_dsn))
    assert plan.mode == "plain", plan.error
    assert plan.root is not None and plan.root.actual_rows is None
    assert plan.triggers == []
    assert state(conn, tables) == before == (1, 1, 1)


def test_analyze_writes_updates_the_row_exactly_once(
    conn: Conn, tables: Tables, pg_dsn: str
) -> None:
    statement = run_traced(conn, f"UPDATE {tables.items} SET plays = plays + 1 WHERE id = %s", (7,))
    plan = plan_of(statement, ExplainOptions(dsn=pg_dsn, analyze_writes=True))
    assert plan.mode == "analyze", plan.error
    (fired,) = plan.triggers
    assert (fired.name, fired.relation, fired.calls) == (
        f"audit_{tables.items[6:]}",
        tables.items,
        1,
    )
    # The user's UPDATE ran once; the replay ran and was rolled back.
    assert state(conn, tables) == (1, 1, 1)


# --- safety ---------------------------------------------------------------------------------


def test_read_only_transaction_blocks_hidden_writes(
    conn: Conn, tables: Tables, pg_dsn: str
) -> None:
    statement = run_traced(conn, f"SELECT nextval('{tables.seq}')")
    before = state(conn, tables)
    plan = plan_of(statement, ExplainOptions(dsn=pg_dsn))
    assert (plan.mode, plan.sqlstate) == ("error", "25006")  # read_only_sql_transaction
    assert state(conn, tables) == before


def test_locking_select_is_not_analysed(conn: Conn, tables: Tables, pg_dsn: str) -> None:
    statement = run_traced(conn, f"SELECT * FROM {tables.items} WHERE id = 7 FOR UPDATE")
    assert plan_of(statement, ExplainOptions(dsn=pg_dsn)).mode == "plain"


def test_statement_timeout_stops_a_slow_replay(conn: Conn, pg_dsn: str) -> None:
    statement = run_traced(conn, "SELECT pg_sleep(2)")
    plan = plan_of(statement, ExplainOptions(dsn=pg_dsn, timeout_ms=100))
    assert (plan.mode, plan.sqlstate) == ("error", "57014")  # query_canceled


def test_temp_tables_are_invisible_to_the_replay(conn: Conn, pg_dsn: str) -> None:
    conn.execute("CREATE TEMP TABLE scratch (id int)")
    statement = run_traced(conn, "SELECT * FROM scratch")
    plan = plan_of(statement, ExplainOptions(dsn=pg_dsn))
    assert (plan.mode, plan.sqlstate) == ("error", "42P01")


@pytest.mark.parametrize("query", ["CREATE TEMP TABLE x (id int)", "SET search_path = public"])
def test_other_statements_are_skipped(conn: Conn, pg_dsn: str, query: str) -> None:
    statement = run_traced(conn, query)
    assert plan_of(statement, ExplainOptions(dsn=pg_dsn)).mode == "skipped"


def test_copy_is_skipped(conn: Conn, pg_dsn: str) -> None:
    with pgsql_loupe.trace() as t, conn.cursor().copy("COPY (SELECT 1) TO STDOUT") as copy:
        list(copy)
    assert plan_of(t.statements[0], ExplainOptions(dsn=pg_dsn)).mode == "skipped"


def test_unreachable_explain_database_is_reported(conn: Conn) -> None:
    statement = run_traced(conn, "SELECT 1")
    bad = ExplainOptions(dsn="postgresql://nobody:x@127.0.0.1:1/none?connect_timeout=2")
    plan = plan_of(statement, bad)
    assert plan.mode == "error" and plan.error is not None
    assert plan.error.startswith("could not connect")


# --- replaying different query forms ------------------------------------------------------------


def test_raw_cursor_and_composed_queries_replay(pg_dsn: str, tables: Tables) -> None:
    with psycopg.connect(pg_dsn, cursor_factory=psycopg.RawCursor) as raw:
        instrument(raw)
        statement = run_traced(raw, f"SELECT * FROM {tables.items} WHERE id = $1", (7,))
    assert plan_of(statement, ExplainOptions(dsn=pg_dsn)).mode == "analyze"
    with psycopg.connect(pg_dsn) as c:
        instrument(c)
        query = sql.SQL("SELECT * FROM {} WHERE id = {}").format(
            sql.Identifier(tables.items), sql.Placeholder()
        )
        statement = run_traced(c, query, (7,))
    assert plan_of(statement, ExplainOptions(dsn=pg_dsn)).mode == "analyze"


def test_executemany_replays_its_first_parameter_set(
    conn: Conn, tables: Tables, pg_dsn: str
) -> None:
    with pgsql_loupe.trace() as t:
        conn.cursor().executemany(
            f"UPDATE {tables.items} SET plays = plays + 1 WHERE id = %s", [(7,), (8,)]
        )
    conn.commit()
    plan = plan_of(t.statements[0], ExplainOptions(dsn=pg_dsn, analyze_writes=True))
    assert plan.mode == "analyze" and plan.root is not None
    assert [tr.calls for tr in plan.triggers] == [1]  # one row: the first parameter set


def test_identical_statements_are_explained_once_and_limit_applies(conn: Conn, pg_dsn: str) -> None:
    with pgsql_loupe.trace() as t:
        for n in (1, 1, 2, 3):
            conn.execute("SELECT %s::int", (n,))
    runs = capture_plans(t.statements, ExplainOptions(dsn=pg_dsn, max_plans=2))
    assert runs == 2
    plans = [s.plan for s in t.statements]
    assert plans[0] is plans[1]
    assert plans[3] is not None and plans[3].mode == "skipped"


# --- flags ----------------------------------------------------------------------------------


def test_big_sequential_scan_is_flagged(conn: Conn, tables: Tables, pg_dsn: str) -> None:
    statement = run_traced(conn, f"SELECT count(*) FROM {tables.items} WHERE kind = %s", ("k1",))
    plan = plan_of(statement, ExplainOptions(dsn=pg_dsn))
    assert [(f.kind, f.relation) for f in plan.flags] == [("seq_scan", tables.items)]
    small = ExplainOptions(dsn=pg_dsn, thresholds=FlagThresholds(seq_scan_rows=10**9))
    statement.plan = None
    assert plan_of(statement, small).flags == []


def test_sort_spilling_to_disk_is_flagged(conn: Conn, pg_dsn: str) -> None:
    statement = run_traced(conn, "SELECT g FROM generate_series(1, 200000) g ORDER BY g DESC")
    tiny_memory = pg_dsn + ("&" if "?" in pg_dsn else "?") + "options=-c%20work_mem%3D64kB"
    plan = plan_of(statement, ExplainOptions(dsn=tiny_memory))
    assert "spill" in [f.kind for f in plan.flags], plan.error


def test_row_estimate_and_hash_batches_flags_from_plan_json() -> None:
    node = parse_node(
        {
            "Node Type": "Hash Join",
            "Plan Rows": 10,
            "Actual Rows": 5000,
            "Actual Loops": 1,
            "Actual Total Time": 12.0,
            "Plans": [
                {
                    "Node Type": "Hash",
                    "Plan Rows": 1,
                    "Hash Batches": 4,
                    "Actual Total Time": 5.0,
                    "Actual Loops": 1,
                },
            ],
        }
    )
    assert node.self_ms == 7.0
    assert [f.kind for f in node_flags(node, FlagThresholds())] == ["row_estimate"]
    assert [f.kind for f in node_flags(node.children[0], FlagThresholds())] == ["spill"]


# --- classification -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("SELECT 1", "read"),
        ("  select * from t", "read"),
        ("-- note\nSELECT 1", "read"),
        ("/* a */ /* b */ SELECT 1", "read"),
        ("VALUES (1), (2)", "read"),
        ("TABLE t", "read"),
        ("WITH x AS (SELECT 1) SELECT * FROM x", "read"),
        ("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x", "write"),
        ("SELECT * FROM t FOR UPDATE", "write"),
        ("SELECT * FROM t FOR NO KEY UPDATE", "write"),
        ("SELECT * FROM t FOR SHARE", "write"),
        ("SELECT * INTO new_t FROM t", "write"),
        ("SELECT 'delete me'", "write"),  # errs towards safety
        ("INSERT INTO t VALUES (1)", "write"),
        ("update t set a = 1", "write"),
        ("DELETE FROM t", "write"),
        ("MERGE INTO t USING s ON true WHEN MATCHED THEN DELETE", "write"),
        ("CREATE TABLE t (id int)", "none"),
        ("DROP TABLE t", "none"),
        ("COPY t TO STDOUT", "none"),
        ("SET search_path = x", "none"),
        ("BEGIN", "none"),
        ("CALL p()", "none"),
        ("", "none"),
    ],
)
def test_classify(query: str, expected: str) -> None:
    assert classify(query) == expected
