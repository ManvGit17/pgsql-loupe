"""FastAPI + psycopg 3 pool with pgsql-loupe.

PGSQL_LOUPE_ENABLED=1 DATABASE_URL=postgresql://... uvicorn app:app
curl -i "http://127.0.0.1:8000/artists?lens=1"          # note the X-Lens-Id header
curl "http://127.0.0.1:8000/__lens/api/requests/<id>"
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from pgsql_loupe.asgi import install
from pgsql_loupe.collectors.psycopg import instrument

DSN = os.environ.get("DATABASE_URL", "postgresql://test:test@127.0.0.1:54318/test")

pool = ConnectionPool(DSN, open=False, configure=instrument)  # line 1 of the setup

SCHEMA = """
CREATE TABLE IF NOT EXISTS example_artists (id int PRIMARY KEY, name text NOT NULL);
CREATE TABLE IF NOT EXISTS example_tracks (
    id int PRIMARY KEY, artist_id int NOT NULL REFERENCES example_artists(id), title text NOT NULL
);
INSERT INTO example_artists SELECT g, 'artist ' || g FROM generate_series(1, 5) g
    ON CONFLICT DO NOTHING;
INSERT INTO example_tracks SELECT g, 1 + g % 5, 'track ' || g FROM generate_series(1, 20) g
    ON CONFLICT DO NOTHING;
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    pool.open(wait=True)
    with pool.connection() as conn:
        conn.execute(SCHEMA)
    yield
    pool.close()


app = FastAPI(lifespan=lifespan)
install(app)  # line 2 of the setup


@app.get("/artists")
def artists() -> list[dict[str, Any]]:
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        return cur.execute("SELECT id, name FROM example_artists ORDER BY id").fetchall()


@app.get("/artists/tracks")
def artists_with_tracks() -> list[dict[str, Any]]:
    """Deliberate N+1: one query per artist."""
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        result = cur.execute("SELECT id, name FROM example_artists ORDER BY id").fetchall()
        for artist in result:
            artist["tracks"] = cur.execute(
                "SELECT title FROM example_tracks WHERE artist_id = %s ORDER BY id",
                (artist["id"],),
            ).fetchall()
    return result
