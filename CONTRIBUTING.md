# Contributing

```bash
docker compose up -d --wait
uv sync
TEST_PG_DSN=postgresql://test:test@127.0.0.1:54318/test uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

`uv run python scripts/local_matrix.py` runs every check CI runs.

The panel lives in `panel-src/` (React + Vite). After changing it:

```bash
cd panel-src && npm ci && npm test && npm run build   # writes src/pgsql_loupe/panel/
uv run playwright install chromium && uv run pytest -m e2e
```

Commit the rebuilt `src/pgsql_loupe/panel/` files with your change.

Tests use a real PostgreSQL, never a mock. Public API changes need an entry in `CHANGELOG.md`.
