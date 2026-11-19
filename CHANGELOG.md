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
- The default authorisation now also requires a local `Host` header (DNS-rebinding protection).
- Install the psycopg collector with `pip install pgsql-loupe[psycopg]`.
