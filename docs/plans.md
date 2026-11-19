# Query plans

Plans are captured by **replaying** a recorded statement, with its original parameters, under
`EXPLAIN` on a **separate connection** (`ExplainOptions(dsn=...)`), never on your app's
connection. Replays run after the response has been sent (`?lens=plan`) or when you press
Explain in the panel.

| Statement | Default | Transaction |
|---|---|---|
| `SELECT`, `VALUES`, `TABLE`, read-only `WITH` | `EXPLAIN (ANALYZE, BUFFERS)` | read-only, rolled back |
| `INSERT`, `UPDATE`, `DELETE`, `MERGE`, data-modifying `WITH`, `SELECT ... FOR UPDATE` | `EXPLAIN` (not executed) | read-only, rolled back |
| the same, with `analyze_writes=True` | `EXPLAIN (ANALYZE, BUFFERS)` | rolled back |
| anything else (DDL, `COPY`, `SET`, ...) | not explained | |

Every replay has a statement timeout (5 s) and a lock timeout (1 s).

## Why it is safe

- **A separate connection**: plan capture cannot slow down, block or roll back your
  transaction, and never runs inside a failed one.
- **Read-only transactions**: a `SELECT` can still write, through `nextval()` or a function
  that inserts. In a read-only transaction both fail and change nothing (tested on
  PostgreSQL 16 and 18).
- **Writes are not executed** unless you set `analyze_writes=True`; then the replay is rolled
  back. It still does the work twice, takes row locks and can advance sequences.
- **Classification errs towards safety**: a write keyword anywhere in a read turns it into a
  write, which only loses `ANALYZE`.

## What a plan shows

A tree of plan nodes with each node's own time (its total minus its children), rows expected
and actual, buffers, and the index or table it reads; the triggers that fired with calls and
time; and warnings:

| Warning | When |
|---|---|
| sequential scan | a `Seq Scan` reads 10,000 rows or more |
| row estimate | expected and actual rows differ 10x or more (and one of them is 100+) |
| spill | a sort used disk, or a hash needed more than one batch |

## Limits

The replay sees committed data at replay time, through the role in `ExplainOptions.dsn`. Temp
tables and uncommitted rows from the request are invisible; such statements show an error
instead of a plan. The design is in [ADR 0003](adr/0003-plan-capture-safety.md).
