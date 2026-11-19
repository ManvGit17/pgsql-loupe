# Contributing

```bash
docker compose up -d --wait
uv sync
TEST_PG_DSN=postgresql://test:test@127.0.0.1:54318/test uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

`uv run python scripts/local_matrix.py` runs every Python × PostgreSQL combination CI runs.

Tests use a real PostgreSQL, never a mock. Public API changes need an entry in `CHANGELOG.md`.
