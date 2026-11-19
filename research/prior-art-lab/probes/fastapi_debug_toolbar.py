# /// script
# requires-python = "==3.13.*"
# dependencies = [
#   "sqlalchemy==2.1.9",
#   "psycopg[binary]==3.3.9",
#   "asyncpg==0.32.0",
#   "httpx==0.28.1",
#   "greenlet==3.5.6",
#   "fastapi==0.111.1",
#   "fastapi-debug-toolbar==0.6.3",
# ]
# ///
"""Probe: fastapi-debug-toolbar 0.6.3 (SQLAlchemy panel)."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from debug_toolbar.middleware import DebugToolbarMiddleware
from debug_toolbar.toolbar import DebugToolbar
from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labapp import build_app, engine, run

Session = async_sessionmaker(engine)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with Session() as session:
        yield session


async def main() -> None:
    app = build_app()
    app.debug = True

    # The panel only finds engines through Session/AsyncSession dependencies.
    @app.get("/dep/nplus1")
    async def dep_nplus1(session: AsyncSession = Depends(get_session)) -> dict[str, int]:
        artists = (await session.execute(text("SELECT id FROM artists ORDER BY id"))).all()
        for (artist_id,) in artists:
            await session.execute(text("SELECT title FROM tracks WHERE artist_id = :a"), {"a": artist_id})
        return {"artists": len(artists)}

    app.add_middleware(
        DebugToolbarMiddleware,
        panels=["debug_toolbar.panels.sqlalchemy.SQLAlchemyPanel"],
        ALLOWED_HOSTS=["127.0.0.1"],
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://lab") as client:
        for path in ["/dep/nplus1", "/sa/nplus1", "/sa/dup", "/raw/nplus1", "/apg/nplus1"]:
            DebugToolbar._store.clear()
            r = await client.get(path)
            stats: dict = {}
            for toolbar in DebugToolbar._store.values():
                panel = toolbar.get_panel_by_id("SQLAlchemyPanel")
                stats = panel.get_stats()
            queries = stats.get("queries", [])
            print(f"GET {path}: status={r.status_code} stored={len(DebugToolbar._store)} queries={len(queries)}")
            for alias, q in queries[:2]:
                print(f"    sql={q['sql'][:60]!r} params={q['params']!r} dup={q.get('is_duplicate', q.get('duplicate_count'))}"
                      f" similar={q.get('similar_count')}")


if __name__ == "__main__":
    run(main())
