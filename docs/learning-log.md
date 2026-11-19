# Learning log

## Phase 0: is it worth building? (2026-11-18)

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
  statement as it really ran, with no replay. That idea matters for Phase 3.
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
