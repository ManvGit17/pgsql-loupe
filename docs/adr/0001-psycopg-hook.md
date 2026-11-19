# ADR 0001: How to hook psycopg 3

Date: 2026-11-19. Checked against psycopg 3.3.9 (docs and installed source).

## Context

The tracer must see every statement a psycopg 3 connection runs, without the user
changing their queries.

What the docs and source say:

- psycopg has no public execution hook or event API (none added in 3.2 or 3.3).
- `Connection.cursor_factory` is the class used by `cursor()` and `execute()`;
  `server_cursor_factory` is the class used by `cursor(name=...)`. Both are settable
  per connection. Async connections have the same attributes.
- `Cursor.execute`, `executemany`, `stream` and `copy` are separate entry points;
  `executemany` does not call `execute`.
- `ClientCursor` and `RawCursor` inherit `execute` from `Cursor`.
- A server cursor's `execute` only sends `DECLARE`; rows arrive during fetches.
- `ConnectionPool(configure=...)` runs a callback on every new connection.

## Decision

`instrument(conn)` replaces the connection's `cursor_factory` and
`server_cursor_factory` with a subclass of **the class already there**, with a mixin
first in the MRO that wraps the entry points above. Subclasses are cached per base
class, and instrumenting twice is a no-op. Pools use `configure=instrument`.

## Alternatives rejected

- **Patch `psycopg.Cursor` globally.** Affects every connection in the process,
  including ones the user did not ask to trace, and is hard to undo.
- **Ship a `TracedCursor` the user passes as `cursor_factory`.** Simple, but replaces a
  `ClientCursor` or `RawCursor` the user already chose, changing query behaviour.
- **Subclass `Connection`.** Pools and frameworks create connections themselves; the
  cursor factory is the smaller, documented surface.

## Consequences

- Cost when no trace is active: one `ContextVar.get()` per call.
- Server cursors: the recorded time is the `DECLARE`, not the fetches.
- Pipeline mode: `execute` returns before the server answers, so durations and errors
  may be attributed late. Documented, not fixed.
- Positional parameters have no names, so only named (dict) parameters can be redacted
  by name. Positional values are truncated only.
