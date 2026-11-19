"""One FastAPI app on three drivers, with pgsql-loupe.

    EXAMPLE_DRIVER=psycopg     (default) sync endpoints on a psycopg 3 pool
    EXAMPLE_DRIVER=sqlalchemy  async endpoints on a SQLAlchemy 2 async engine (asyncpg)
    EXAMPLE_DRIVER=asyncpg     async endpoints on an asyncpg pool

    PGSQL_LOUPE_ENABLED=1 DATABASE_URL=postgresql://... uvicorn app:app
    then open http://127.0.0.1:8000/artists/tracks?lens=plan and http://127.0.0.1:8000/__lens/

Every driver serves the same URLs and the same JSON. `/artists/tracks` has a deliberate N+1;
`/artists/tracks-fixed` gives the same answer in two queries.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from pgsql_loupe.asgi import ExplainOptions, LoupeConfig, install

DSN = os.environ.get("DATABASE_URL", "postgresql://test:test@127.0.0.1:54318/test")
DRIVER = os.environ.get("EXAMPLE_DRIVER", "psycopg")

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS example_artists (id int PRIMARY KEY, name text NOT NULL)",
    """CREATE TABLE IF NOT EXISTS example_tracks (
        id int PRIMARY KEY, artist_id int NOT NULL REFERENCES example_artists(id),
        title text NOT NULL)""",
    """INSERT INTO example_artists SELECT g, 'artist ' || g FROM generate_series(1, 5) g
        ON CONFLICT DO NOTHING""",
    """INSERT INTO example_tracks SELECT g, 1 + g % 5, 'track ' || g FROM generate_series(1, 20) g
        ON CONFLICT DO NOTHING""",
]

Artist = dict[str, Any]


def group_tracks(artists: list[Artist], tracks: list[tuple[int, str]]) -> list[Artist]:
    for artist in artists:
        artist["tracks"] = [{"title": title} for aid, title in tracks if aid == artist["id"]]
    return artists


if DRIVER == "psycopg":
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from pgsql_loupe.collectors.psycopg import instrument

    pool = ConnectionPool(DSN, open=False, configure=instrument)  # setup line 1

    @asynccontextmanager
    async def lifespan_psycopg(_: FastAPI) -> AsyncIterator[None]:
        pool.open(wait=True)
        with pool.connection() as conn:
            for statement in SCHEMA:
                conn.execute(statement)
        yield
        pool.close()

    app = FastAPI(lifespan=lifespan_psycopg)

    @app.get("/artists")
    def artists_psycopg() -> list[Artist]:
        with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            return cur.execute("SELECT id, name FROM example_artists ORDER BY id").fetchall()

    @app.get("/artists/tracks")
    def artists_with_tracks_psycopg() -> list[Artist]:
        with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            result = cur.execute("SELECT id, name FROM example_artists ORDER BY id").fetchall()
            for artist in result:
                rows = cur.execute(  # N+1 (psycopg)
                    "SELECT title FROM example_tracks WHERE artist_id = %s ORDER BY id",
                    (artist["id"],),
                ).fetchall()
                artist["tracks"] = [{"title": r["title"]} for r in rows]
        return result

    @app.get("/artists/tracks-fixed")
    def artists_with_tracks_fixed_psycopg() -> list[Artist]:
        with pool.connection() as conn, conn.cursor() as cur:
            rows = cur.execute("SELECT id, name FROM example_artists ORDER BY id").fetchall()
            result = [{"id": i, "name": n} for i, n in rows]
            tracks = cur.execute(
                "SELECT artist_id, title FROM example_tracks WHERE artist_id = ANY(%s) ORDER BY id",
                ([a["id"] for a in result],),
            ).fetchall()
        return group_tracks(result, tracks)

elif DRIVER == "sqlalchemy":
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from pgsql_loupe.collectors.sqlalchemy import instrument_engine

    engine = create_async_engine(DSN.replace("postgresql://", "postgresql+asyncpg://", 1))
    instrument_engine(engine)  # setup line 1

    @asynccontextmanager
    async def lifespan_sqlalchemy(_: FastAPI) -> AsyncIterator[None]:
        async with engine.begin() as conn:
            for statement in SCHEMA:
                await conn.exec_driver_sql(statement)
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan_sqlalchemy)

    @app.get("/artists")
    async def artists_sqlalchemy() -> list[Artist]:
        async with engine.connect() as conn:
            rows = await conn.execute(text("SELECT id, name FROM example_artists ORDER BY id"))
            return [dict(r._mapping) for r in rows]

    @app.get("/artists/tracks")
    async def artists_with_tracks_sqlalchemy() -> list[Artist]:
        async with engine.connect() as conn:
            rows = await conn.execute(text("SELECT id, name FROM example_artists ORDER BY id"))
            result = [dict(r._mapping) for r in rows]
            for artist in result:
                tracks = await conn.execute(  # N+1 (sqlalchemy)
                    text("SELECT title FROM example_tracks WHERE artist_id = :a ORDER BY id"),
                    {"a": artist["id"]},
                )
                artist["tracks"] = [{"title": t.title} for t in tracks]
        return result

    @app.get("/artists/tracks-fixed")
    async def artists_with_tracks_fixed_sqlalchemy() -> list[Artist]:
        async with engine.connect() as conn:
            rows = await conn.execute(text("SELECT id, name FROM example_artists ORDER BY id"))
            result = [dict(r._mapping) for r in rows]
            tracks = await conn.execute(
                text(
                    "SELECT artist_id, title FROM example_tracks"
                    " WHERE artist_id = ANY(:ids) ORDER BY id"
                ),
                {"ids": [a["id"] for a in result]},
            )
        return group_tracks(result, [(t.artist_id, t.title) for t in tracks])

elif DRIVER == "asyncpg":
    import asyncpg

    from pgsql_loupe.collectors.asyncpg import TracedConnection

    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan_asyncpg(_: FastAPI) -> AsyncIterator[None]:
        # setup line 1: every pooled connection records its statements
        state["pool"] = await asyncpg.create_pool(DSN, connection_class=TracedConnection)
        async with state["pool"].acquire() as conn:
            for statement in SCHEMA:
                await conn.execute(statement)
        yield
        await state["pool"].close()

    app = FastAPI(lifespan=lifespan_asyncpg)

    @app.get("/artists")
    async def artists_asyncpg() -> list[Artist]:
        async with state["pool"].acquire() as conn:
            rows = await conn.fetch("SELECT id, name FROM example_artists ORDER BY id")
            return [dict(r) for r in rows]

    @app.get("/artists/tracks")
    async def artists_with_tracks_asyncpg() -> list[Artist]:
        async with state["pool"].acquire() as conn:
            rows = await conn.fetch("SELECT id, name FROM example_artists ORDER BY id")
            result = [dict(r) for r in rows]
            for artist in result:
                tracks = await conn.fetch(  # N+1 (asyncpg)
                    "SELECT title FROM example_tracks WHERE artist_id = $1 ORDER BY id",
                    artist["id"],
                )
                artist["tracks"] = [{"title": t["title"]} for t in tracks]
        return result

    @app.get("/artists/tracks-fixed")
    async def artists_with_tracks_fixed_asyncpg() -> list[Artist]:
        async with state["pool"].acquire() as conn:
            rows = await conn.fetch("SELECT id, name FROM example_artists ORDER BY id")
            result = [dict(r) for r in rows]
            tracks = await conn.fetch(
                "SELECT artist_id, title FROM example_tracks WHERE artist_id = ANY($1) ORDER BY id",
                [a["id"] for a in result],
            )
        return group_tracks(result, [(t["artist_id"], t["title"]) for t in tracks])

else:
    raise SystemExit(f"EXAMPLE_DRIVER must be psycopg, sqlalchemy or asyncpg, not {DRIVER!r}")


install(app, LoupeConfig(explain=ExplainOptions(dsn=DSN)))  # setup line 2
