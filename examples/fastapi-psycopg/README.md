# FastAPI + psycopg example

```bash
docker compose up -d --wait          # from the repo root
cd examples/fastapi-psycopg
PGSQL_LOUPE_ENABLED=1 uv run --with "fastapi[standard]" uvicorn app:app
```

Open `http://127.0.0.1:8000/artists/tracks?lens=1`, copy the `X-Lens-Id` response
header, then open `http://127.0.0.1:8000/__lens/api/requests/<id>`.

Compare `/artists/tracks?lens=1` (one query per artist, flagged as N+1) with
`/artists/tracks-fixed?lens=1` (two queries, not flagged).
