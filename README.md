# pgsql-loupe

A debug panel for Python web apps on PostgreSQL. Open any page with `?lens=1` and see what it
did to the database: every statement, its parameters, how long it took, the line of your code
that ran it, `EXPLAIN ANALYZE` plans, the triggers that fired, and a warning when the same
query ran once per row.

![The panel showing an N+1 warning and a query plan](docs/images/panel.png)

## Try it

```bash
pip install "pgsql-loupe[psycopg]" "psycopg[binary]" psycopg-pool fastapi uvicorn
```

Save this as `app.py`; the two marked lines are all pgsql-loupe needs:

```python
import os

from fastapi import FastAPI
from psycopg_pool import ConnectionPool

from pgsql_loupe.asgi import ExplainOptions, LoupeConfig, install
from pgsql_loupe.collectors.psycopg import instrument

DSN = os.environ["DATABASE_URL"]
pool = ConnectionPool(DSN, configure=instrument, open=True)  # 1. record statements
app = FastAPI()
install(app, LoupeConfig(explain=ExplainOptions(dsn=DSN)))  # 2. add the panel


@app.get("/tables")
def tables() -> list[str]:
    with pool.connection() as conn:
        rows = conn.execute("SELECT tablename FROM pg_tables ORDER BY 1 LIMIT %s", (5,))
        return [name for (name,) in rows]
```

```bash
PGSQL_LOUPE_ENABLED=1 DATABASE_URL=postgresql://user:password@localhost/db uvicorn app:app
```

Open <http://127.0.0.1:8000/tables?lens=plan>, then the panel at
<http://127.0.0.1:8000/__lens/>.

It is off unless `PGSQL_LOUPE_ENABLED=1`, refuses to start when the environment says
production, answers only requests from this machine, and redacts parameters that look secret.
Plan capture runs on its own connection and never executes a write unless you ask
([how](docs/plans.md)).

## Drivers

| Driver | Setup |
|---|---|
| psycopg 3 | `ConnectionPool(dsn, configure=instrument)` or `instrument(conn)` |
| SQLAlchemy 2 (sync or async) | `instrument_engine(engine)` |
| asyncpg | `asyncpg.create_pool(dsn, connection_class=TracedConnection)` |

Any ASGI app works: `install(app)` for FastAPI and Starlette, `LoupeMiddleware(app)` otherwise.

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

## Compared with other tools

Checked hands-on on 2026-11-18 ([details and how to reproduce](docs/prior-art.md)):

| | pgsql-loupe | litestar-debug-toolbar | queryspy | PostgreSQL auto_explain |
|---|---|---|---|---|
| Raw psycopg 3 / asyncpg | yes | no | no | yes (server side) |
| SQLAlchemy | yes | yes | yes | yes (server side) |
| Per request, correct under concurrency | yes | no | yes | no (server log) |
| Analysed plans with fired triggers | yes | no | no | yes |
| N+1 warnings | yes | yes | ORM `select()` only | no |
| pytest assertions | yes | no | yes | no |

## Overhead

Measured by [`bench/overhead.py`](bench/overhead.py); full output, machine and versions in
[`bench/results/2026-11-19-windows.md`](bench/results/2026-11-19-windows.md)
(Windows 11 laptop, PostgreSQL 18.7 in Docker on the same machine).

| | Added cost |
|---|---:|
| Statement on an instrumented connection, no trace active | 0.11 µs |
| Statement recorded into a trace | 9.74 µs |
| `GET /artists/tracks` (6 statements) with `?lens=1`, p50 | +0.16 ms (11.86 ms without the lens) |

## Documentation

[Quick start per driver](docs/quickstart.md) · [Query plans](docs/plans.md) ·
[In tests](docs/testing.md) · [Configuration](docs/configuration.md) ·
[Safety model](docs/safety.md) · [Recipes](docs/recipes.md) ·
[Design decisions](docs/adr/0001-psycopg-hook.md)

Python 3.11 to 3.15, PostgreSQL 16 to 18. Licence: Apache-2.0.

Built with help from [Claude Code](https://claude.com/claude-code).
