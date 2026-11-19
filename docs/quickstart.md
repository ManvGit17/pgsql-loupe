# Quick start

pgsql-loupe needs Python 3.11 or newer and PostgreSQL 16 or newer.

## 1. Install

```bash
pip install "pgsql-loupe[psycopg]"      # or [sqlalchemy], or [asyncpg]
```

The extras only declare the driver; your app installs the driver the way it already does.
Plan capture always uses psycopg, so install `pgsql-loupe[psycopg]` too if you want plans.

## 2. Hook the driver (one line)

=== "psycopg 3"

    ```python
    from psycopg_pool import ConnectionPool
    from pgsql_loupe.collectors.psycopg import instrument

    pool = ConnectionPool(dsn, configure=instrument)
    # or, for one connection: instrument(conn)
    # AsyncConnectionPool: configure=instrument_async
    ```

=== "SQLAlchemy 2"

    ```python
    from sqlalchemy.ext.asyncio import create_async_engine
    from pgsql_loupe.collectors.sqlalchemy import instrument_engine

    engine = create_async_engine("postgresql+asyncpg://...")  # or a sync Engine
    instrument_engine(engine)
    ```

=== "asyncpg"

    ```python
    import asyncpg
    from pgsql_loupe.collectors.asyncpg import TracedConnection

    pool = await asyncpg.create_pool(dsn, connection_class=TracedConnection)
    # your own Connection subclass: traced_connection_class(MyConnection)
    ```

## 3. Add the middleware (one line)

```python
from pgsql_loupe.asgi import ExplainOptions, LoupeConfig, install

install(app, LoupeConfig(explain=ExplainOptions(dsn=dsn)))  # FastAPI or Starlette
```

For any other ASGI app, wrap it: `app = LoupeMiddleware(app, LoupeConfig(...))`.

## 4. Run with the lens enabled

```bash
PGSQL_LOUPE_ENABLED=1 uvicorn app:app
```

Open a page with `?lens=1` (statements) or `?lens=plan` (statements and plans), then open
`http://127.0.0.1:8000/__lens/`. Each traced response also carries an `X-Lens-Id` header and a
`Server-Timing` header that browser dev tools show.

## Without a web framework

```python
import pgsql_loupe

with pgsql_loupe.trace() as t:
    run_some_code()
for statement in t.statements:
    print(statement.duration_ms, statement.sql, statement.call_site)
```

A full example app that runs on all three drivers is in
[`examples/fastapi`](https://github.com/ManvGit17/pgsql-loupe/tree/main/examples/fastapi).
