# The panel and the API

## Tracing a request

A request is traced only when it asks to be, and only when it comes from an authorised client
(by default: this machine):

| Ask with | Records |
|---|---|
| `?lens=1` or header `X-Lens: 1` | statements, parameters, timings, call sites |
| `?lens=plan` or header `X-Lens: plan` | the same, plus a plan for each statement, captured after the response |

The response gets `X-Lens-Id` (the trace's id) and `Server-Timing` (database time and statement
count). The last 100 traced requests are kept in memory (`LoupeConfig(history=...)`).

## The panel

`/__lens/` lists traced requests, newest first. For a request it shows:

- a summary: status, total time, database time and its share of the request;
- warnings: N+1 patterns (with the code that ran them), exact duplicates, slow statements,
  plan warnings; each links to its statements;
- every statement with a timeline bar; open one for its SQL, parameters, call site, row count,
  error, plan tree and fired triggers, and an **Explain** button.

Arrow keys move through the request list; `/__lens/#<id>` opens one request. The panel works
offline: it loads nothing from outside your app.

With `LoupeConfig(inject_toggle=True)`, traced HTML pages get a small "SQL" link to the panel.

## The JSON API

| Request | Returns |
|---|---|
| `GET /__lens/api/requests` | summaries, newest first |
| `GET /__lens/api/requests/{id}` | one request: summary, `analysis`, `statements` |
| `POST /__lens/api/requests/{id}/statements/{n}/explain` | a fresh plan for statement `n` (needs an `X-Lens` header) |

Each statement has `sql`, `params` (redacted text), `kind`, `start_ms`, `duration_ms`,
`rowcount`, `error`, `sqlstate`, `call_site`, `fingerprint`, `explain` (`read`, `write` or
`none`) and `plan`. Unredacted parameter values are kept for replays but never served.
