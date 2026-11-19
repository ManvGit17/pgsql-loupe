# Overhead

Measured by `bench/overhead.py` on a Windows 11 laptop with PostgreSQL 18.7 in Docker on the
same machine; the full output, with versions and every round, is in
[`bench/results/2026-11-19-windows.md`](https://github.com/ManvGit17/pgsql-loupe/blob/main/bench/results/2026-11-19-windows.md).

| | Added cost |
|---|---:|
| Statement on an instrumented connection, no trace active | 0.11 µs |
| Statement recorded into a trace | 9.74 µs |
| `GET /artists/tracks` (6 statements) with `?lens=1`, p50 | +0.16 ms (11.86 ms without the lens) |

## How it is measured

- **Tracer cost**: the psycopg collector's real recording path around a no-op instead of a
  database call. Pure CPU work, so it is stable between runs; it is exactly what tracing adds
  to each statement.
- **Per request**: the example app on two servers (lens disabled and enabled), one request at a
  time, rotating through the setups. Every setup is measured at the same moments, so changes
  in machine speed cannot favour one of them.

Earlier designs (each setup measured for ten seconds in turn) gave differences larger than the
effect itself on a laptop, so they were dropped. Run it yourself:

```bash
docker compose up -d --wait
uv run python bench/overhead.py
```
