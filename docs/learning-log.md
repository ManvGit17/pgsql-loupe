# Learning log

## Prior art and scaffold (2026-11-18)

**What was built**

- `research/prior-art-lab/`: a small FastAPI app, run against real PostgreSQL in Docker,
  with deliberate problems: an N+1 loop, duplicate queries, an `UPDATE` that fires a
  trigger, a sequential scan, and a failing statement. Each endpoint runs through
  SQLAlchemy, raw psycopg 3 and raw asyncpg. One probe script per existing tool records
  what that tool actually saw. `run_all.py` re-creates every file in `results/`.
- `docs/prior-art.md`: the scorecard and the go/no-go verdict.
- The repo skeleton: `uv` project with a `src/` layout, ruff, `mypy --strict`, pytest, a
  placeholder test that talks to a real database, `compose.yaml` with PostgreSQL 16, 17
  and 18, a GitHub Actions matrix (5 Pythons × 3 PostgreSQL versions), and
  `scripts/local_matrix.py`, which runs the same matrix locally.

**Why**

- Before writing a library, check that it isn't already solved. Reading summaries was not
  enough: the probes found things no README says. For example, one toolbar mixes up
  concurrent requests, another crashes on current FastAPI, and a third reports N+1 only
  for ORM `select()`.
- Every existing panel hooks SQLAlchemy. A tool that hooks the driver (psycopg's cursor,
  asyncpg's logger) also sees raw SQL, which is the gap SQL Lens fills.
- PostgreSQL's `auto_explain` proves the server can report plans *and* triggers for the
  statement as it really ran, with no replay. That idea matters for plan capture.
- The placeholder test fails, rather than skips, without a database, and checks the server
  version. Each matrix job therefore proves it ran against the version it claims.

**Quiz**

1. Why did two overlapping requests in litestar-debug-toolbar both show request A's
   statement, and which Python feature prevents that?
2. queryspy counted 11 statements for both `/sa/nplus1` and `/model/nplus1`, but warned
   only on the second. Why?
3. What does `auto_explain.log_triggers` add, and why can't a normal app user turn it
   on for their own session?
4. In tuple-beat's `plan` mode, how many times does an `UPDATE` run on the server, and
   what is not undone by the rollback?
5. The CI test job sets `EXPECT_PG_MAJOR`. What mistake would go unnoticed without it?

## The trace and the psycopg collector (2026-11-19)

**What was built**

- `core/trace.py`: `Statement` (one SQL statement: text, redacted parameters, timing, row
  count, error, call site, transaction status, server process id) and `Trace` (a list of
  statements). `pgsql_loupe.trace()` makes a trace active for a `with` or `async with` block.
- `core/redact.py`: parameters are stored as short text. Named values that look secret
  (`password`, `token`, `key`, ...) become `<redacted>`; long values are cut.
- `core/callsite.py`: walks the Python stack to the first frame outside the stdlib,
  site-packages and this library, so a statement points at the user's own line.
- `collectors/psycopg.py`: `instrument(conn)` puts a recording mixin in front of the
  connection's own cursor classes. It wraps `execute`, `executemany`, `stream`, `copy` and
  server-side cursors, sync and async. `instrument_async` is the same for async pools.
- `docs/adr/0001-psycopg-hook.md`: why the cursor factory was chosen over alternatives.

**Why**

- psycopg has no "on every query" hook, but every cursor is created from
  `conn.cursor_factory`. Subclassing whatever class is already there keeps a user's
  `ClientCursor` or `RawCursor` working.
- The active trace is a `ContextVar`. asyncio gives each task a copy of the context, so
  concurrent requests on one event loop never mix their statements; a test runs three at
  once to prove it.
- The tracer must never change a query's result. Recording happens around the real call;
  the user's exception is re-raised untouched; a bug inside the recorder makes the
  statement go unrecorded instead of failing (tested by forcing the recorder to crash).
- A mutation check (making `instrument` do nothing) made 21 tests fail, so the tests
  really exercise the hook.

**Quiz**

1. Why does `instrument` build a subclass of the connection's current `cursor_factory`
   instead of always using one `TracedCursor` class?
2. `executemany` is wrapped separately from `execute`. What would go wrong if it were not,
   and why can't the wrapper simply call `len()` on its parameters?
3. A server-side cursor's statement shows a tiny duration even for a huge query. Why?
4. Two requests run concurrently on one event loop. Explain step by step why their
   statements land in different traces.
5. Why does `stream()` treat `GeneratorExit` differently from other exceptions?

## ASGI middleware and JSON output (2026-11-19)

**What was built**

- `asgi/middleware.py`: `LoupeMiddleware`, a plain ASGI middleware. A request asking for
  tracing (`?lens=1`, `?lens=plan`, `X-Lens` header) runs inside `pgsql_loupe.trace()`. The
  response gets `X-Lens-Id` (where to find the trace) and `Server-Timing` (database time,
  shown by browser dev tools). It also answers `GET /__lens/api/requests[/{id}]` as JSON.
- `asgi/store.py`: the last 100 traced requests in memory (a ring buffer).
- `asgi/config.py`: off unless `PGSQL_LOUPE_ENABLED=1`; refuses to start if `APP_ENV` (or
  similar) says production; only localhost may trigger tracing or read the API.
- `asgi.install(app)`: the second line of the two-line FastAPI setup.
- `examples/fastapi-psycopg`: a small app with a deliberate N+1, used by the tests.

**Why**

- A pure ASGI middleware calls the app in the same asyncio task, so the trace ContextVar is
  visible in the endpoint. FastAPI runs `def` endpoints in a thread pool but copies the
  context first, which is why the example's sync endpoints are traced too.
- Authorisation guards *activation*, not only the API: once plan capture exists, `?lens=plan` will run
  `EXPLAIN ANALYZE`, so a stranger must not be able to turn it on.
- "Localhost only" is broken by a reverse proxy on the same machine (every request then
  comes from 127.0.0.1), so a request with `X-Forwarded-For` or `Forwarded` counts as remote.
- The plan's `install(app, pool=...)` was dropped: psycopg-pool's configure hook is private
  and only applies to new connections. `ConnectionPool(..., configure=instrument)` is the
  supported way.
- An endpoint that crashes gets its 500 from Starlette's outermost error handler, outside
  our middleware, so that response has no `X-Lens-Id`. The stored trace still records
  status 500 and the exception name.

**Quiz**

1. Why must the authorisation check run before a request is traced, not only on `/__lens`?
2. What does a reverse proxy on the same host do to a "localhost only" rule, and how does
   pgsql-loupe defend against it?
3. A FastAPI `def` (not `async def`) endpoint runs in another thread. Why are its
   statements still recorded into the request's trace?
4. Why is `Server-Timing` sometimes lower than the database time in the stored trace?
5. Why does the production guard run inside `install()` instead of on the first request?

## Plans and triggers (2026-11-19)

**What was built**

- `explain/safety.py`: sorts a statement into *read*, *write* or *not explainable* from its
  first keyword and a search for write keywords.
- `explain/capture.py`: replays a recorded statement with its original parameters, under
  `EXPLAIN`, on a separate connection. Reads: `EXPLAIN (ANALYZE, BUFFERS)` in a `READ ONLY`
  transaction. Writes: plain `EXPLAIN` (not executed), or `ANALYZE` in a rolled-back
  transaction when `analyze_writes=True`. Each replay has a statement and lock timeout.
- `explain/plan.py` and `flags.py`: the JSON plan as a tree (time per node, expected vs actual
  rows, buffers, triggers that fired) and three warnings: big sequential scans, row estimates
  off by 10x or more, sorts or hashes that spilled to disk.
- `?lens=plan` captures plans after the response is sent; `POST .../statements/{n}/explain`
  captures one on demand.
- `docs/adr/0003-plan-capture-safety.md`.

**Why**

- `EXPLAIN ANALYZE` *runs* the statement. A separate connection means plan capture can never
  touch the user's transaction, locks or data.
- A read-only transaction closes a hole: a `SELECT` can still write, through `nextval()` or a
  function that inserts. Tested: both fail in read-only mode and change nothing.
- The classifier only ever errs towards safety: a stray keyword makes a read look like a
  write (losing `ANALYZE`), never the other way round.
- The API must never serve raw parameters, but replays need them. They live in
  `Statement.replay`, which the JSON serialiser leaves out; a test proves a password value
  never appears in any response, and a mutation check proves that test can fail.
- Two browser attacks on a localhost tool: a cross-site `POST` (blocked by requiring an
  `X-Lens` header, which needs a CORS preflight) and DNS rebinding (blocked by requiring a
  local `Host` header).

**Quiz**

1. Why does plan capture use its own connection instead of the user's?
2. Give two ways a plain `SELECT` can change data, and what stops them during capture.
3. With `analyze_writes=True`, how can a test prove the user's `UPDATE` ran exactly once?
4. Why can't the replay see a temporary table the request created?
5. What is DNS rebinding, and why does checking the `Host` header stop it here?

## N+1 and duplicate detection (2026-11-19)

**What was built**

- `analyzers/fingerprint.py`: a tokenizer that turns SQL into its *shape*: values and
  placeholders become `?`, value lists become `(...)`, comments go, words are lower cased.
  50 table-driven test cases cover PostgreSQL's quoting rules.
- `analyzers/report.py`: per request, N+1 suspects (one shape run 3+ times with different
  values, with call sites), exact duplicates (same SQL and values), slow statements, and a
  summary (count, database time, share of the request spent in the database).
- The JSON API now returns `analysis` and a `fingerprint` per statement; the example has a
  deliberate N+1 endpoint and a fixed one.
- `docs/adr/0004-sql-fingerprint.md`.

**Why**

- An N+1 is the same statement with different values, so the detector needs a way to see
  "same statement" through different literals and placeholder styles.
- A hand-written tokenizer instead of `sqlglot`: grouping needs tokens, not a full parse, and
  a fast-moving 810 KB dependency would cost more than ~150 tested lines.
- Duplicates are compared on raw values: redacted passwords all look alike.
- `executemany` is the batched fix for an N+1, so it never counts as one.

**Quiz**

1. Why must `id = 5`, `id = %s` and `id = $1` produce the same fingerprint?
2. What is the difference between an N+1 and an exact duplicate, and how is each fixed?
3. Why are duplicates compared on raw values rather than the stored, redacted ones?
4. Why does `= -1` become `= ?` while `a - 1` becomes `a - ?`?
5. The fixed example endpoint uses `= ANY(%s)`. Why is that one statement no matter how many
   artists there are?
