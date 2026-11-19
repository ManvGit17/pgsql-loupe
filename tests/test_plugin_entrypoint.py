"""The plugin as users get it: a separate pytest process loads it from the `pytest11` entry
point (no `-p` flag, no conftest), and a failing assertion explains itself."""

from __future__ import annotations

import pytest

INNER_TESTS = """
import os

import psycopg

from pgsql_loupe.collectors.psycopg import instrument


def connect():
    conn = psycopg.connect(os.environ["TEST_PG_DSN"])
    instrument(conn)
    return conn


def test_budget(loupe):
    with connect() as conn:
        conn.execute("SELECT 1")
        conn.execute("SELECT %s::int", (2,))
        conn.execute("SELECT 3")
    loupe.assert_max_queries(1)


def test_nplus1(loupe):
    with connect() as conn:
        for artist in (1, 2, 3):
            conn.execute("SELECT %s::int AS artist", (artist,))
    loupe.assert_no_nplus1()


def test_within_budget(loupe):
    with connect() as conn:
        conn.execute("SELECT 1")
    loupe.assert_max_queries(1)
"""


@pytest.fixture
def run(pytester: pytest.Pytester, pg_dsn: str, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    monkeypatch.setenv("TEST_PG_DSN", pg_dsn)
    monkeypatch.delenv("PGSQL_LOUPE_TEST_DSN", raising=False)
    pytester.makepyfile(test_inner=INNER_TESTS)
    return pytester


def line_of(pytester: pytest.Pytester, text: str) -> int:
    source = (pytester.path / "test_inner.py").read_text(encoding="utf-8").splitlines()
    return next(number for number, line in enumerate(source, start=1) if text in line)


def test_failing_assertions_print_statements_and_call_sites(run: pytest.Pytester) -> None:
    result = run.runpytest_subprocess("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, failed=2)
    one = line_of(run, 'conn.execute("SELECT 1")')
    two = line_of(run, 'conn.execute("SELECT %s::int", (2,))')
    loop = line_of(run, "AS artist")
    result.stdout.fnmatch_lines(
        [
            "*AssertionError: expected at most 1 queries, 3 ran:",
            "*#0 SELECT 1",
            f"*params: None | test_inner.py:{one} in test_budget() | *ms",
            "*#1 SELECT %s::int",
            # fnmatch reads [...] as a character class, so list brackets are left out.
            f"*params: *'2'* | test_inner.py:{two} in test_budget() | *",
            "*#2 SELECT 3",
        ]
    )
    result.stdout.fnmatch_lines(
        [
            "*N+1: 'select ?::int as artist' ran 3 times with 3 different values, from *"
            f"test_inner.py:{loop}*",
            f"*params: *'1'* | test_inner.py:{loop} in test_nplus1() | *",
            f"*params: *'3'* | test_inner.py:{loop} in test_nplus1() | *",
        ]
    )


@pytest.mark.parametrize(
    ("args", "ini", "env", "expected"),
    [
        ([], None, None, "None"),
        ([], None, "from-env", "'from-env'"),
        ([], "from-ini", "from-env", "'from-ini'"),
        (["--pgsql-loupe-dsn=from-option"], "from-ini", "from-env", "'from-option'"),
    ],
)
def test_dsn_settings_precedence(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    ini: str | None,
    env: str | None,
    expected: str,
) -> None:
    if env is None:
        monkeypatch.delenv("PGSQL_LOUPE_TEST_DSN", raising=False)
    else:
        monkeypatch.setenv("PGSQL_LOUPE_TEST_DSN", env)
    if ini is not None:
        pytester.makeini(f"[pytest]\npgsql_loupe_dsn = {ini}\n")
    pytester.makepyfile(f"def test_dsn(loupe):\n    assert repr(loupe.dsn) == {expected!r}\n")
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", *args)
    result.assert_outcomes(passed=1)
