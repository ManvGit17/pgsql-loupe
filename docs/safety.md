# Safety model

pgsql-loupe records SQL parameters and can run `EXPLAIN`. It is a development tool, and the
defaults are chosen so that it cannot quietly become a production one.

## Who can see it

- **Off by default**: nothing is added unless `PGSQL_LOUPE_ENABLED=1` (or `enabled=True`).
- **Production guard**: if `PGSQL_LOUPE_ENV`, `APP_ENV`, `ENVIRONMENT` or `ENV` says `prod`,
  `production` or `live`, enabling raises `ProductionGuardError` at start-up, not on the first
  request. `PGSQL_LOUPE_ALLOW_PRODUCTION=1` overrides it, deliberately.
- **Localhost only**: the default `authorize` accepts a request only if the client is
  `127.0.0.1`/`::1`, the `Host` header names this machine, and no `Forwarded`/`X-Forwarded-For`
  header is present. The last two close two holes: a reverse proxy on the same machine makes
  every visitor look local, and a DNS-rebinding page reaches 127.0.0.1 under its own host name.
- **Unauthorised requests are never traced**, and `/__lens/*` answers as if it did not exist.
- **Cross-site POSTs**: the explain endpoint requires an `X-Lens` header, which a page on
  another site cannot send without a CORS preflight the API never approves.
- **The panel's Content-Security-Policy** allows scripts, styles and requests only from the
  same origin.

## What is stored

- Parameters are stored as short text. Named values whose name contains `pass` (so also
  `password`, `passwd`), `pwd`, `secret`, `token` or `key`, in any case, become
  `<redacted>`; long values are truncated; binary values become `<N bytes>`. Positional
  values have no name, so they are truncated only.
- Unredacted values are kept in memory for replays and never served by the API or shown in
  `repr()`.
- Everything lives in memory, for the last `history` requests. Nothing is written to disk.

## What it runs

Recording never changes a query: if building a record fails, the statement runs unrecorded;
if the statement fails, its original error is re-raised. Plan capture runs on its own
connection with read-only transactions and timeouts; see [Query plans](plans.md).

Report security problems privately (see `SECURITY.md`).
