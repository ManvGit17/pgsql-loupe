# In tests (pytest)

Installing pgsql-loupe adds a pytest plugin with one fixture, `loupe`. It records every
statement the test runs, including requests made through Starlette's / FastAPI's `TestClient`.

```python
def test_artists_page(loupe, client):
    with loupe.record() as r:  # only what happens in this block
        client.get("/artists/tracks")
    r.assert_max_queries(2)
    r.assert_no_nplus1()
    r.assert_no_seq_scan("tracks")
```

| Assertion | Fails when |
|---|---|
| `assert_max_queries(n)` | more than `n` statements ran |
| `assert_num_queries(n)` | not exactly `n` statements ran |
| `assert_no_nplus1(threshold=None)` | one statement shape ran 3+ times (or `threshold`) with different values |
| `assert_no_seq_scan(table, dsn=None)` | a statement mentioning `table` is planned with a sequential scan on it |

A failure lists every statement involved:

```text
AssertionError: expected at most 1 queries, 3 ran:
  #0 SELECT 1
      params: None | tests/test_api.py:16 in test_budget() | 2.21 ms
  #1 SELECT %s::int
      params: ['2'] | tests/test_api.py:17 in test_budget() | 1.12 ms
  ...
```

`BEGIN`, `COMMIT`, `ROLLBACK` and savepoints are not counted, so a budget means the same on
every driver (`QueryRecorder(count_transaction_control=True)` counts them). `loupe.reset()`
forgets what was recorded so far.

## `assert_no_seq_scan`

It runs plain `EXPLAIN` (your queries are not executed again) on a database given by, in order:
the `dsn=` argument, `--pgsql-loupe-dsn`, the `pgsql_loupe_dsn` ini option, or the
`PGSQL_LOUPE_TEST_DSN` environment variable.

It explains from another connection, so the data must be committed. If a statement cannot be
explained (for example it uses a temp table, or the test's data is in an open transaction), the
assertion fails and says so rather than passing silently.
