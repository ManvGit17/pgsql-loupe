# ADR 0007: The pytest plugin

Date: 2026-11-19. Checked against pytest 9.2.0, anyio 4.16.0, Starlette 1.10.0.

## Decisions

1. **Registered through the `pytest11` entry point**, so installing the package is enough:
   no `-p` flag, no conftest. The plugin module imports only the core at load time, because
   it is loaded in every pytest session of a project that has the package installed.
2. **One fixture, `loupe`**, a `QueryRecorder` that records the whole test. `loupe.record()`
   narrows to a block, which keeps start-up SQL (an app's lifespan creating tables) out of a
   budget. Checked first: Starlette's `TestClient` runs the app in another thread through an
   anyio portal, and anyio 4.16 carries the caller's context into it, so requests made with
   `TestClient` are recorded on all three drivers.
3. **Assertions**: `assert_max_queries(n)`, `assert_num_queries(n)`, `assert_no_nplus1()`,
   `assert_no_seq_scan(table)`. A failure lists each statement involved with its parameters
   (redacted), call site (relative to the working directory) and time. Plain ASCII only, so
   the message reads the same in every terminal.
4. **Transaction control is not counted** (`BEGIN`, `COMMIT`, `ROLLBACK`, `SAVEPOINT`, ...):
   asyncpg records them, psycopg does not, and a budget should not depend on the driver.
   `count_transaction_control=True` counts them.
5. **`assert_no_seq_scan` uses plain `EXPLAIN`** (new `ExplainOptions.analyze_reads=False`) on
   the statements mentioning the table, so the test's queries are not run again. Its DSN comes
   from `dsn=`, then `--pgsql-loupe-dsn`, then the `pgsql_loupe_dsn` ini option, then
   `PGSQL_LOUPE_TEST_DSN`. A statement that cannot be explained fails the assertion: a check
   that silently skips would pass when it should not.

## Consequences

- `assert_no_seq_scan` explains from another connection, so the data must be committed; a test
  that keeps everything in one open transaction gets a clear failure, not a false pass.
- The planner may choose a sequential scan for a tiny table even with a usable index; the
  assertion reports what the planner chose for the data present.
