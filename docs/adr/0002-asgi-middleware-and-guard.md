# ADR 0002: ASGI middleware, activation and the production guard

Date: 2026-11-19. Checked against Starlette 1.10.0, FastAPI 0.165.0, psycopg-pool 3.3.3.

## Decisions

1. **Pure ASGI middleware**, not Starlette's `BaseHTTPMiddleware`. It has no framework
   dependency, works with any ASGI app (FastAPI, Starlette, Litestar), and runs the app in
   the same task, so the ContextVar trace reaches the endpoint. FastAPI runs sync endpoints
   in a thread pool with a copy of the context, so they are traced too (tested).
2. **Per-request opt-in**: a request is traced only with `?lens=1`, `?lens=plan` or an
   `X-Lens` header. Others pass straight through.
3. **Off by default**: nothing is added unless `PGSQL_LOUPE_ENABLED=1` (or `enabled=True`).
4. **Production guard**: if `PGSQL_LOUPE_ENV`, `APP_ENV`, `ENVIRONMENT` or `ENV` is
   `prod`, `production` or `live`, enabling raises `ProductionGuardError` when the app is
   set up, unless `PGSQL_LOUPE_ALLOW_PRODUCTION=1`.
5. **Authorisation applies to activation and to the API.** Default: localhost only. A
   request carrying `Forwarded` or `X-Forwarded-For` is treated as non-local, because
   behind a reverse proxy on the same machine every client would otherwise look local.
   Unauthorised requests are never traced, and `/__lens/*` answers as if it did not exist
   (the app's own 404).
6. **Storage**: the last N requests in memory (ring buffer, default 100). Nothing is
   written to disk.
7. **No `pool=` argument on `install()`** (the plan suggested one). psycopg-pool keeps its
   configure callback in a private attribute (`_configure`) and only applies it to
   connections opened later. The supported route is `ConnectionPool(..., configure=instrument)`.

## Consequences

- `Server-Timing` is computed when the response starts. Statements run while a streaming
  body is sent, or in background tasks, appear in the stored trace but not in the header.
- When the endpoint raises, Starlette's outermost error handler sends the 500 response
  past this middleware, so it has no `X-Lens-Id` header. The trace is still stored, with
  status 500 and the exception's class name, and is listed by the API.
- Setup for FastAPI stays two lines: `configure=instrument` on the pool and `install(app)`.
