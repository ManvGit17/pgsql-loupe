# Changelog

## Unreleased

- `pgsql_loupe.trace()`: records every statement run inside the block (`with` or `async with`).
- `pgsql_loupe.collectors.psycopg.instrument(conn)` and `instrument_async(conn)`: record psycopg 3
  statements (execute, executemany, stream, copy, server-side cursors), sync and async.
- `pgsql_loupe.asgi.install(app)` and `LoupeMiddleware`: trace requests opted in with `?lens=1`,
  `?lens=plan` or an `X-Lens` header; adds `X-Lens-Id` and `Server-Timing` headers; serves
  `GET /__lens/api/requests` and `GET /__lens/api/requests/{id}`. Off unless
  `PGSQL_LOUPE_ENABLED=1`; refuses to start in production; localhost-only by default.
- Plan capture (`LoupeConfig(explain=ExplainOptions(dsn=...))`): `?lens=plan` and
  `POST /__lens/api/requests/{id}/statements/{n}/explain` replay statements under `EXPLAIN` on a
  separate connection. Reads are analysed in a read-only transaction; writes get a plain `EXPLAIN`
  unless `analyze_writes=True` (rolled back). Plans list fired triggers and flag large
  sequential scans, bad row estimates and spills to disk.
- Analyzers: N+1 shapes (same fingerprint, 3+ runs, different values), exact duplicates, slow
  statements and a per-request summary (statement count, database time, share of request time).
  Served as `analysis` in `GET /__lens/api/requests/{id}`; each statement has a `fingerprint`.
  Thresholds: `LoupeConfig(analyzers=AnalyzerOptions(...))`.
- Panel at `/__lens/`: request list, statement timeline, SQL with parameters and call
  sites, plan tree with triggers and flags, N+1 and duplicate warnings, an Explain button,
  keyboard navigation, light and dark themes. Ships built inside the package; no Node needed.
- `LoupeConfig(inject_toggle=True)`: adds a link to the panel on traced HTML pages (off by default).
- SQLAlchemy 2 collector: `pgsql_loupe.collectors.sqlalchemy.instrument_engine(engine)` for sync
  and async engines on any PostgreSQL driver; statements are never recorded twice when the
  psycopg collector is also active. Install with `pip install pgsql-loupe[sqlalchemy]`.
- asyncpg collector: `pgsql_loupe.collectors.asyncpg.TracedConnection` (pass as
  `connection_class`) and `traced_connection_class()`. Install with `pip install pgsql-loupe[asyncpg]`.
- `bench/overhead.py` and its results; the README's overhead table comes from it.
- The default authorisation now also requires a local `Host` header (DNS-rebinding protection).
- Install the psycopg collector with `pip install pgsql-loupe[psycopg]`.
