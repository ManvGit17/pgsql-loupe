# Prior art

Checked 2026-11-18 against PostgreSQL 18.7. Every claim below comes from
`research/prior-art-lab` (run `run_all.py`; outputs in `results/`) or, where marked,
from reading the package source.

## Scorecard

| | litestar-debug-toolbar 1.1.1 | fastapi-debug-toolbar 0.6.3 | queryspy 0.6.0 | nplusone 1.0.0 | PostgreSQL auto_explain |
|---|---|---|---|---|---|
| Last release | 2026-10 | 2024-05 | 2026-10 | 2018-05 | ships with PostgreSQL |
| Works with current FastAPI / SQLAlchemy | yes | **no**: crashes every request on FastAPI 0.164 | yes | **no**: import fails on SQLAlchemy 2.1 | n/a |
| SQLAlchemy statements | yes | only sessions injected with `Depends` | yes | ORM lazy loads only | yes |
| Raw psycopg 3 / asyncpg | no | no | no | no | yes (server side) |
| Parameters shown | yes | yes | no (by design) | no | not tested |
| Per-request grouping, correct under concurrency | **no**: two overlapping requests both reported request A's statement | yes | yes | n/a | no (server log) |
| Failed statement recorded | no | not tested | yes (counted) | n/a | no |
| N+1 warning | yes | "similar" count | ORM `select()` only; none for `text()` | none raised in test | no |
| EXPLAIN | not on FastAPI (endpoint 404); plain, text, breaks with psycopg params | no | no | no | ANALYZE, JSON |
| Triggers fired | no | no | no | no | **yes** |
| pytest assertions | no | no | yes | no | no |
| Default guard | on for all hosts | needs `app.debug` + allowed IP | none | n/a | superuser / config |

Also reviewed by reading the source only: **pytest-querycount 0.4.0** (2026-09).
It hooks SQLAlchemy, works in pytest only, and can run `EXPLAIN (FORMAT JSON)`
without ANALYZE in a savepoint to fail tests on sequential scans. It has no panel
and no trigger data.

## Notes

- **litestar-debug-toolbar** is the closest tool. Its SQL panel keeps one
  module-level tracker, not a ContextVar, which is why overlapping requests get
  mixed. `ExplainExecutor` fills parameters in by string replacement of `?` and
  `:name`, so `%(name)s` placeholders fail with a syntax error.
- **queryspy** is a good SQLAlchemy N+1 and query-budget tool with a pytest plugin.
  It never stores parameter values and has no plans.
- **auto_explain** is the only tool that shows plans with triggers, and it covers
  every driver. It writes to the server log with no per-request view, and needs
  superuser rights or server configuration. Worth keeping in mind for Phase 3: it
  explains the *real* execution instead of replaying it.
- **Starting point (tuple-beat `lens.py`)**: psycopg 3 sync only, called explicitly
  through `lens.run()`. In `plan` mode every statement, writes included, runs once
  under `EXPLAIN ANALYZE` in a rolled-back savepoint and then again for real.

## Verdict

**Go.** No tool shows per-request statements with analysed plans and triggers for
raw psycopg 3. The SQLAlchemy toolbars miss raw drivers, triggers and ANALYZE.
auto_explain has the plan data but no per-request view.
