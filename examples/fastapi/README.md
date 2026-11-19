# FastAPI example (psycopg, SQLAlchemy or asyncpg)

```bash
docker compose up -d --wait          # from the repo root
cd examples/fastapi
PGSQL_LOUPE_ENABLED=1 uv run uvicorn app:app
```

Set `EXAMPLE_DRIVER=sqlalchemy` or `EXAMPLE_DRIVER=asyncpg` to run the same app on another driver.

Open `http://127.0.0.1:8000/artists/tracks?lens=plan`, then the panel at
`http://127.0.0.1:8000/__lens/`. Compare `/artists/tracks?lens=1` (one query per artist,
flagged as N+1) with `/artists/tracks-fixed?lens=1` (two queries, not flagged).
