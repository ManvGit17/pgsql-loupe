# Changelog

## Unreleased

- `pgsql_loupe.trace()`: records every statement run inside the block (`with` or `async with`).
- `pgsql_loupe.collectors.psycopg.instrument(conn)` and `instrument_async(conn)`: record psycopg 3
  statements (execute, executemany, stream, copy, server-side cursors), sync and async.
- Install the psycopg collector with `pip install pgsql-loupe[psycopg]`.
