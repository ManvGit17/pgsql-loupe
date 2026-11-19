# ADR 0003: Capturing plans without changing the user's data

Date: 2026-11-19. Behaviour below was checked on PostgreSQL 16.16 and 18.7.

## Decision

Plans are captured by **replaying** a recorded statement, with its original parameters, on a
**separate connection** (`ExplainOptions.dsn`), never on the user's connection. Replays run
after the request has finished (`?lens=plan`) or when asked for one statement
(`POST /__lens/api/requests/{id}/statements/{n}/explain`).

| Statement | Default | Transaction |
|---|---|---|
| `SELECT`, `VALUES`, `TABLE`, read-only `WITH` | `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` | `BEGIN READ ONLY` … `ROLLBACK` |
| `INSERT`/`UPDATE`/`DELETE`/`MERGE`, data-modifying `WITH`, `SELECT … FOR UPDATE/SHARE`, `SELECT … INTO` | `EXPLAIN (FORMAT JSON)` (not executed) | `BEGIN READ ONLY` … `ROLLBACK` |
| the same, with `analyze_writes=True` | `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` | `BEGIN` … `ROLLBACK` |
| anything else (DDL, `COPY`, `SET`, …) | not explained | — |

Every replay sets `statement_timeout` and `lock_timeout` locally.

## Why

- **Separate connection**: plan capture can never break, slow down or roll back the user's
  own transaction, and never runs inside a failed transaction.
- **`READ ONLY` for analysed reads**: a `SELECT` is not always harmless. Checked:
  `EXPLAIN ANALYZE SELECT nextval('s')` and a `SELECT` calling a function that runs `INSERT`
  both fail with `ReadOnlySqlTransaction` in a read-only transaction, and change nothing.
- **`READ ONLY` for plain explains**: `EXPLAIN UPDATE …` without ANALYZE is accepted in a
  read-only transaction, so even a mis-classified statement cannot write.
- **Rolled back `ANALYZE` on writes**: checked that after `EXPLAIN ANALYZE UPDATE` in a rolled
  back transaction, the row, the trigger's side table and the sequence are unchanged, and the
  fired trigger is reported (`Triggers`, with calls and time). It still does the work twice,
  takes row locks and can advance sequences, so it is opt-in.
- **Classification errs towards safety**: it looks at the first keyword and searches for
  write keywords. A write keyword inside a string literal makes a read look like a write, which
  only loses `ANALYZE`; it can never make a write look like a read that gets executed outside
  a read-only transaction.

## Rejected

- **Explain inline on the user's connection** (the tuple-beat lens): sees uncommitted rows and
  temp tables, but doubles every write and shares the user's transaction and locks.
- **`auto_explain`**: explains the real execution, but needs superuser or server config and
  writes to the server log, not to a per-request trace.

## Consequences

- The replay sees committed data at replay time, not what the request saw. Temp tables and
  rows from a rolled-back request are invisible; the explain records the error instead.
- The replay uses the role and settings of `ExplainOptions.dsn`, which may differ from the app's.
- Raw parameter values are kept in memory (never served by the API) so statements can be
  replayed; they live only as long as the request stays in the ring buffer.
- Cross-site requests: `POST …/explain` requires an `X-Lens` header, which a browser cannot send
  cross-origin without a CORS preflight that the API never approves. The default
  authorisation also requires a local `Host` header, which blocks DNS-rebinding pages from
  reading the API.
