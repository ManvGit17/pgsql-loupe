"""Shared FastAPI app for the prior-art probes.

The same endpoints are reached through three drivers, so each probe can show
which statements a tool sees:
  /sa/*     SQLAlchemy 2 async engine on psycopg 3
  /raw/*    raw psycopg 3 async connection
  /apg/*    raw asyncpg connection
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import psycopg
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DSN = os.environ.get("LAB_DSN", "postgresql://lab:lab@127.0.0.1:55432/lab")
engine = create_async_engine(DSN.replace("postgresql://", "postgresql+psycopg://"))

TRACK_ID = 7  # row the write endpoints touch


def build_app() -> FastAPI:
    app = FastAPI()

    # --- SQLAlchemy -------------------------------------------------------
    @app.get("/sa/nplus1")
    async def sa_nplus1() -> dict[str, int]:
        async with engine.connect() as conn:
            artists = (await conn.execute(text("SELECT id FROM artists ORDER BY id"))).all()
            for (artist_id,) in artists:  # deliberate N+1
                await conn.execute(text("SELECT title FROM tracks WHERE artist_id = :a"), {"a": artist_id})
        return {"artists": len(artists)}

    @app.get("/sa/dup")
    async def sa_dup() -> dict[str, bool]:
        async with engine.connect() as conn:
            for _ in range(3):  # exact duplicate: same SQL, same params
                await conn.execute(text("SELECT name FROM artists WHERE id = :a"), {"a": 1})
        return {"ok": True}

    @app.post("/sa/write")
    async def sa_write() -> dict[str, bool]:
        async with engine.begin() as conn:  # UPDATE fires the tracks_audit trigger
            await conn.execute(text("UPDATE tracks SET plays = plays + 1 WHERE id = :t"), {"t": TRACK_ID})
        return {"ok": True}

    @app.get("/sa/seq")
    async def sa_seq() -> dict[str, int]:
        async with engine.connect() as conn:  # no index on payload -> seq scan on 200k rows
            n = (await conn.execute(text("SELECT count(*) FROM events WHERE payload = :p"), {"p": "x"})).scalar_one()
        return {"n": n}

    @app.get("/sa/error")
    async def sa_error() -> dict[str, str]:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT * FROM no_such_table"))
        except Exception as exc:  # noqa: BLE001
            return {"error": type(exc).__name__}
        return {"error": ""}

    @app.get("/sa/slow")
    async def sa_slow(tag: str = "") -> dict[str, str]:
        async with engine.connect() as conn:  # used for the concurrency check
            await conn.execute(text("SELECT :tag, pg_sleep(0.3)"), {"tag": tag})
        return {"tag": tag}

    # --- raw psycopg 3 ----------------------------------------------------
    @app.get("/raw/nplus1")
    async def raw_nplus1() -> dict[str, int]:
        async with await psycopg.AsyncConnection.connect(DSN) as conn:
            cur = await conn.execute("SELECT id FROM artists ORDER BY id")
            artists = await cur.fetchall()
            for (artist_id,) in artists:
                await conn.execute("SELECT title FROM tracks WHERE artist_id = %s", (artist_id,))
        return {"artists": len(artists)}

    # --- raw asyncpg -------------------------------------------------------
    @app.get("/apg/nplus1")
    async def apg_nplus1() -> dict[str, int]:
        conn = await asyncpg.connect(DSN)
        try:
            artists = await conn.fetch("SELECT id FROM artists ORDER BY id")
            for row in artists:
                await conn.fetch("SELECT title FROM tracks WHERE artist_id = $1", row["id"])
        finally:
            await conn.close()
        return {"artists": len(artists)}

    return app


async def plays_and_audit() -> tuple[int, int]:
    """Return (plays of TRACK_ID, rows in audit_log) to detect side effects."""
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        cur = await conn.execute(
            "SELECT (SELECT plays FROM tracks WHERE id = %s), (SELECT count(*) FROM audit_log)", (TRACK_ID,)
        )
        row = await cur.fetchone()
        assert row is not None
        return int(row[0]), int(row[1])


def run(coro: object) -> object:
    """asyncio.run with the selector loop psycopg needs on Windows."""
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
    return asyncio.run(coro)  # type: ignore[arg-type]
