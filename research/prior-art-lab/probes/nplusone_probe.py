# /// script
# requires-python = "==3.13.*"
# dependencies = [
#   "sqlalchemy==2.0.58",
#   "psycopg[binary]==3.3.9",
#   "nplusone==1.0.0",
# ]
# ///
"""Probe: nplusone 1.0.0 (last release 2018) with SQLAlchemy 2.1 lazy loading."""

from __future__ import annotations

import sys
import warnings

from sqlalchemy import ForeignKey, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

print("python", sys.version.split()[0])
try:
    import nplusone.ext.sqlalchemy  # noqa: F401  (patches SQLAlchemy loaders on import)
    from nplusone.core import profiler

    print("import nplusone.ext.sqlalchemy: ok")
except Exception as exc:  # noqa: BLE001
    print(f"import nplusone.ext.sqlalchemy failed: {type(exc).__name__}: {exc}")
    raise SystemExit(0)


class Base(DeclarativeBase):
    pass


class Artist(Base):
    __tablename__ = "artists"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    tracks: Mapped[list[Track]] = relationship(back_populates="artist")


class Track(Base):
    __tablename__ = "tracks"
    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id"))
    title: Mapped[str]
    artist: Mapped[Artist] = relationship(back_populates="tracks")


engine = create_engine("postgresql+psycopg://lab:lab@127.0.0.1:55432/lab")
try:
    with warnings.catch_warnings(record=True) as caught, profiler.Profiler():
        warnings.simplefilter("always")
        with Session(engine) as session:
            for artist in session.scalars(select(Artist)).all():
                _ = list(artist.tracks)  # classic lazy-load N+1
    print("lazy-load N+1 in profiler: no error raised; warnings:", [str(w.message)[:80] for w in caught])
except Exception as exc:  # noqa: BLE001
    print(f"lazy-load N+1 in profiler -> {type(exc).__name__}: {str(exc)[:160]}")
