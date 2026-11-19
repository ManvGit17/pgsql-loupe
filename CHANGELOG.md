# Changelog

## Unreleased

- `pgsql_loupe.trace()`: records every statement run inside the block (`with` or `async with`).
- `pgsql_loupe.collectors.psycopg.instrument(conn)` and `instrument_async(conn)`: record psycopg 3
  statements (execute, executemany, stream, copy, server-side cursors), sync and async.
- `pgsql_loupe.asgi.install(app)` and `LoupeMiddleware`: trace requests opted in with `?lens=1`,
  `?lens=plan` or an `X-Lens` header; adds `X-Lens-Id` and `Server-Timing` headers; serves
  `GET /__lens/api/requests` and `GET /__lens/api/requests/{id}`. Off unless
  `PGSQL_LOUPE_ENABLED=1`; refuses to start in production; localhost-only by default.
- Install the psycopg collector with `pip install pgsql-loupe[psycopg]`.
