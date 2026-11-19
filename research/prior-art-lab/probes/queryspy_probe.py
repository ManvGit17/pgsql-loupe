# /// script
# requires-python = "==3.13.*"
# dependencies = [
#   "fastapi==0.164.0",
#   "sqlalchemy==2.1.9",
#   "psycopg[binary]==3.3.9",
#   "asyncpg==0.32.0",
#   "httpx==0.28.1",
#   "greenlet==3.5.6",
#   "queryspy==0.6.0",
# ]
# ///
"""Probe: queryspy 0.6.0 (ASGI middleware + panel)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from queryspy.asgi import QuerySpyMiddleware
from sqlalchemy import ForeignKey, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from labapp import build_app, run

reports: list = []


async def main() -> None:
    app = build_app()

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from labapp import engine

    Session = async_sessionmaker(engine)

    @app.get("/orm/nplus1")
    async def orm_nplus1() -> dict[str, int]:
        async with Session() as session:  # same loop, but through an ORM Session
            artists = (await session.execute(text("SELECT id FROM artists ORDER BY id"))).all()
            for (artist_id,) in artists:
                await session.execute(text("SELECT title FROM tracks WHERE artist_id = :a"), {"a": artist_id})
        return {"artists": len(artists)}

    class Base(DeclarativeBase):
        pass

    class Artist(Base):
        __tablename__ = "artists"
        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str]

    class Track(Base):
        __tablename__ = "tracks"
        id: Mapped[int] = mapped_column(primary_key=True)
        artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id"))
        title: Mapped[str]

    @app.get("/model/nplus1")
    async def model_nplus1() -> dict[str, int]:
        async with Session() as session:  # ORM select() of mapped classes in a loop
            artists = (await session.scalars(select(Artist))).all()
            for artist in artists:
                (await session.scalars(select(Track).where(Track.artist_id == artist.id))).all()
        return {"artists": len(artists)}

    app.add_middleware(QuerySpyMiddleware, panel=True, on_report=reports.append)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://lab") as client:
        for method, path in [
            ("GET", "/sa/nplus1"),
            ("GET", "/orm/nplus1"),
            ("GET", "/model/nplus1"),
            ("GET", "/sa/dup"),
            ("POST", "/sa/write"),
            ("GET", "/sa/seq"),
            ("GET", "/sa/error"),
            ("GET", "/raw/nplus1"),
            ("GET", "/apg/nplus1"),
        ]:
            reports.clear()
            r = await client.request(method, path)
            rep = reports[-1] if reports else None
            if rep is None:
                print(f"{method} {path}: no report")
                continue
            kinds = [(f.kind, f.count) if hasattr(f, "count") else f.kind for f in rep.findings]
            print(f"{method} {path}: status={r.status_code} queries={rep.query_count} findings={kinds}")
            print(f"    headers: { {k: v for k, v in r.headers.items() if 'queryspy' in k.lower() or k.lower() == 'server-timing'} }")
        if rep is not None:
            print("sample rendered report:\n" + reports[-1].render() if reports else "")

        # Concurrency: are overlapping requests kept apart?
        reports.clear()
        await asyncio.gather(client.get("/sa/slow?tag=A"), client.get("/sa/slow?tag=B"), client.get("/sa/nplus1"))
        print("concurrent query counts:", sorted((rep.path, rep.query_count) for rep in reports))

        r = await client.get("/__queryspy__")
        print(f"panel GET /__queryspy__ -> {r.status_code}, {len(r.text)} bytes, mentions EXPLAIN: {'EXPLAIN' in r.text}")


if __name__ == "__main__":
    run(main())
