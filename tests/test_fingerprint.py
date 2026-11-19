"""SQL fingerprints: table-driven cases for PostgreSQL's lexical rules."""

from __future__ import annotations

import pytest

from pgsql_loupe.analyzers.fingerprint import fingerprint

CASES = [
    # basics
    ("SELECT 1", "select ?"),
    ("  SELECT\n\t*  FROM   t  ", "select * from t"),
    ("SeLeCt * FrOm Users", "select * from users"),
    ("SELECT * FROM t;", "select * from t"),
    ("SELECT * FROM public.t", "select * from public.t"),
    ("SELECT t1.col2 FROM t1", "select t1.col2 from t1"),
    ("SELECT a$b FROM t", "select a$b from t"),
    ('SELECT "Name" FROM "Users"', 'select "Name" from "Users"'),
    ('SELECT "a""b" FROM t', 'select "a""b" from t'),
    ("SELECT café FROM t", "select café from t"),
    # string literals
    ("SELECT * FROM t WHERE name = 'bob'", "select * from t where name = ?"),
    ("SELECT 'it''s'", "select ?"),
    ("SELECT ''", "select ?"),
    ("SELECT E'it\\'s'", "select ?"),
    ("SELECT B'1010', X'ff'", "select ?, ?"),
    ("SELECT U&'d\\0061t'", "select ?"),
    ("SELECT N'abc'", "select ?"),
    ("SELECT $$it's -- not a comment$$", "select ?"),
    ("SELECT $fn$ body $$ inside $fn$", "select ?"),
    ("SELECT '/* not a comment */'", "select ?"),
    # numbers and booleans
    ("SELECT 42, 4.2, .5, 1e10, 2.5E-3", "select ?, ?, ?, ?, ?"),
    ("SELECT * FROM t WHERE a = -1", "select * from t where a = ?"),
    ("SELECT a - 1 FROM t", "select a - ? from t"),
    ("SELECT * FROM t WHERE x IN (-1, 2)", "select * from t where x in (...)"),
    ("SELECT * FROM t WHERE active = true", "select * from t where active = ?"),
    ("SELECT * FROM t WHERE active = FALSE", "select * from t where active = ?"),
    ("SELECT * FROM t WHERE deleted_at IS NULL", "select * from t where deleted_at is null"),
    ("SELECT * FROM t LIMIT 10 OFFSET 20", "select * from t limit ? offset ?"),
    # placeholders
    ("SELECT * FROM t WHERE id = %s", "select * from t where id = ?"),
    ("SELECT * FROM t WHERE id = %(id)s", "select * from t where id = ?"),
    ("SELECT * FROM t WHERE data = %b", "select * from t where data = ?"),
    ("SELECT * FROM t WHERE id = $1 AND x = $12", "select * from t where id = ? and x = ?"),
    ("SELECT %s::int", "select ?::int"),
    ("SELECT 10 %% 3", "select ? % ?"),
    # lists
    ("SELECT * FROM t WHERE id IN (1, 2, 3)", "select * from t where id in (...)"),
    ("SELECT * FROM t WHERE id IN (%s)", "select * from t where id in (...)"),
    ("SELECT * FROM t WHERE id IN ( 1 , 2 )", "select * from t where id in (...)"),
    (
        "SELECT * FROM t WHERE id IN (SELECT id FROM u)",
        "select * from t where id in (select id from u)",
    ),
    ("INSERT INTO t (a, b) VALUES (1, 'x')", "insert into t (a, b) values (...)"),
    (
        "INSERT INTO t (a, b) VALUES (1, 'x'), (2, 'y'), (3, 'z')",
        "insert into t (a, b) values (...)",
    ),
    ("SELECT ARRAY[1, 2, 3]", "select array[...]"),
    ("SELECT * FROM t WHERE id = ANY(%s)", "select * from t where id = any (...)"),
    # comments
    ("SELECT 1 -- trailing", "select ?"),
    ("-- leading\nSELECT 1", "select ?"),
    ("SELECT /* hint */ 1", "select ?"),
    ("SELECT /* outer /* nested */ still */ 1", "select ?"),
    # operators
    ("SELECT data->>'name' FROM t", "select data ->> ? from t"),
    ("SELECT * FROM t WHERE a <> 1 AND b >= 2", "select * from t where a <> ? and b >= ?"),
    ("SELECT a || b FROM t", "select a || b from t"),
    ("UPDATE t SET plays = plays + 1 WHERE id = %s", "update t set plays = plays + ? where id = ?"),
]


@pytest.mark.parametrize(("sql", "expected"), CASES)
def test_fingerprint(sql: str, expected: str) -> None:
    assert fingerprint(sql) == expected


def test_there_are_at_least_forty_cases() -> None:
    assert len(CASES) >= 40


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("SELECT * FROM t WHERE id = 5", "select * from t where id = %s"),
        ("SELECT * FROM t WHERE id = $1", "SELECT * FROM t WHERE id = 'x'"),
        ("SELECT * FROM t WHERE id IN (1)", "SELECT * FROM t WHERE id IN (1, 2, 3, 4)"),
        ("SELECT 1 -- a", "SELECT  2 /* b */"),
    ],
)
def test_same_shape_same_fingerprint(a: str, b: str) -> None:
    assert fingerprint(a) == fingerprint(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("SELECT * FROM t WHERE id = 1", "SELECT * FROM u WHERE id = 1"),
        ("SELECT a FROM t", "SELECT b FROM t"),
        ('SELECT * FROM "T"', "SELECT * FROM t"),
        ("SELECT * FROM t WHERE x IS NULL", "SELECT * FROM t WHERE x = 1"),
    ],
)
def test_different_shape_different_fingerprint(a: str, b: str) -> None:
    assert fingerprint(a) != fingerprint(b)
