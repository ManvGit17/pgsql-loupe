# Contributing

Bugs and ideas: open an issue with one of the forms at
https://github.com/ManvGit17/pgsql-loupe/issues/new/choose. Fixes: open a pull request.

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

Performance numbers in the README come only from `uv run python bench/overhead.py`; commit its
output file from `bench/results/` with any change to them.

## Docs

```bash
uv run --group docs mkdocs serve      # http://127.0.0.1:8000
```

## Releasing (maintainer)

1. Set the version in `pyproject.toml` and `src/pgsql_loupe/__init__.py`; date the
   `CHANGELOG.md` section.
2. `uv run python scripts/local_matrix.py` and `uv run python scripts/clean_install_check.py`.
3. Once only: on pypi.org add a trusted publisher (this repository, workflow `release.yml`,
   environment `pypi`), and create the `pypi` environment in the repository settings.
4. Merge to `main`, then tag and push: `git tag v0.1.0 && git push origin v0.1.0`.
   The `Release` workflow checks the tag against the version, builds and publishes.
5. Docs: when the repository is public, enable Pages (source: GitHub Actions) and run the
   `Docs` workflow.
