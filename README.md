# pgsql-loupe

A debug panel for Python web apps on PostgreSQL: every statement a request ran, with
parameters, timings, `EXPLAIN ANALYZE` plans, fired triggers and N+1 warnings.

**Status:** early development; nothing usable yet. See [docs/prior-art.md](docs/prior-art.md)
for how it compares with existing tools.

## Quick start (FastAPI + psycopg)

```python
from pgsql_loupe.asgi import install
from pgsql_loupe.collectors.psycopg import instrument

pool = ConnectionPool(dsn, configure=instrument)
install(app)
```

Run with `PGSQL_LOUPE_ENABLED=1`, request any page with `?lens=1`, then open
`/__lens/api/requests/<X-Lens-Id>`. It is off by default, refuses to start when the
environment says production, and only answers requests from localhost.

Licence: Apache-2.0.
