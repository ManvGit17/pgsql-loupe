# ADR 0006: SQLAlchemy and asyncpg collectors

Date: 2026-11-19. Checked against SQLAlchemy 2.1.9, asyncpg 0.32.0, greenlet 3.5.6.

## SQLAlchemy: engine cursor events

`instrument_engine(engine)` listens to `before_cursor_execute`, `after_cursor_execute` and
`handle_error` on the engine (`engine.sync_engine` for an `AsyncEngine`).

Checked before choosing:

- Async engines run these events in a child greenlet. A probe showed the request's
  ContextVar *is* visible there, so the trace is found. The user's code is not on the child
  greenlet's stack, though: the call-site lookup continues into the parent greenlet's frames.
- Parameters arrive in the driver's own style: `%(name)s` with a dict on psycopg, `$1` with a
  tuple on asyncpg. Both are replayed for EXPLAIN by psycopg (a `RawCursor` for `$1`).
- `handle_error` runs inside SQLAlchemy's error handling: an exception there replaces the
  user's database error. Every step of every handler is guarded (a test proves the user's
  error survives a crashing handler; a mutation check proves the test can fail).

**Not recording twice.** SQLAlchemy on psycopg connections that are also instrumented
would see each statement twice. While SQLAlchemy records a statement it marks the driver
cursor (and the cursor inside SQLAlchemy's async adapter); the psycopg collector skips marked
cursors. The mark is removed after the statement, so the same connection used directly
afterwards is recorded by psycopg again (tested).

## asyncpg: a Connection subclass, not the query logger

`TracedConnection` (or `traced_connection_class(MyConnection)`) is passed as
`connection_class` to `asyncpg.connect` or `asyncpg.create_pool`.

asyncpg's query logger (`add_query_logger`) was rejected after reading its source and a probe:

- It is called through `loop.call_soon` *after* the query: the user's code is no longer on the
  stack, so there is no call site, and the start time can only be estimated.
- It does not see statements run through prepared statements or cursors.

The subclass wraps `execute`, `fetch`, `fetchrow`, `fetchval`, `fetchmany`, `executemany` and
the four `copy_*` methods. It still does not see `conn.prepare()` or `conn.cursor()`
(documented; tested).

`Connection.reset()`, which the pool runs when a connection comes back
(`RESET ALL`, `UNLISTEN *`, ...), is not recorded: it is driver housekeeping, and psycopg's
pool does the same work invisibly.

## Overhead

`bench/overhead.py` measures the tracer's own cost per statement (the recording path around a
no-op, which is stable) and per-request latency with requests interleaved one at a time
across setups (so machine-speed drift and queueing cannot bias the comparison). Earlier
designs (separate timed runs per setup) produced differences larger than the effect on this
laptop and were discarded. Profiling showed half the recording cost was path normalisation in
the call-site lookup; it is now cached per file name.
