# pgsql-loupe

A debug panel for Python web apps on PostgreSQL: every statement a request ran, with
parameters, timings, `EXPLAIN ANALYZE` plans, fired triggers and N+1 warnings.

**Status:** early development; nothing usable yet. See [docs/prior-art.md](docs/prior-art.md)
for how it compares with existing tools.

## Drivers

| Driver | Setup |
|---|---|
| psycopg 3 | `ConnectionPool(dsn, configure=instrument)` or `instrument(conn)` |
| SQLAlchemy 2 (sync or async) | `instrument_engine(engine)` |
| asyncpg | `asyncpg.create_pool(dsn, connection_class=TracedConnection)` |

## Quick start (FastAPI + psycopg)

```python
from pgsql_loupe.asgi import ExplainOptions, LoupeConfig, install
from pgsql_loupe.collectors.psycopg import instrument

pool = ConnectionPool(dsn, configure=instrument)
install(app, LoupeConfig(explain=ExplainOptions(dsn=dsn)))
```

Run with `PGSQL_LOUPE_ENABLED=1`, request any page with `?lens=1`, then open `/__lens/`
(the JSON is at `/__lens/api/requests`). Use `?lens=plan` to also capture `EXPLAIN ANALYZE`
plans and fired triggers (see [docs/adr/0003-plan-capture-safety.md](docs/adr/0003-plan-capture-safety.md)
for how writes are kept safe). Each trace also lists N+1 patterns, duplicate queries and
slow statements. It is off by default, refuses to start when the
environment says production, and only answers requests from localhost.

## In tests (pytest)

Installing the package adds a `loupe` fixture:

```python
def test_artists_page(loupe, client):
    with loupe.record() as r:
        client.get("/artists/tracks")
    r.assert_max_queries(2)
    r.assert_no_nplus1()
    r.assert_no_seq_scan("tracks")  # needs --pgsql-loupe-dsn or PGSQL_LOUPE_TEST_DSN
```

A failing assertion lists each statement with its parameters, the line of your code that ran
it, and its time.

## Overhead

Measured by [`bench/overhead.py`](bench/overhead.py); full output, machine and versions in
[`bench/results/2026-11-19-windows.md`](bench/results/2026-11-19-windows.md)
(Windows 11 laptop, PostgreSQL 18.7 in Docker on the same machine).

| | Added cost |
|---|---:|
| Statement on an instrumented connection, no trace active | 0.11 µs |
| Statement recorded into a trace | 9.74 µs |
| `GET /artists/tracks` (6 statements) with `?lens=1`, p50 | +0.16 ms (11.86 ms without the lens) |

Licence: Apache-2.0.
