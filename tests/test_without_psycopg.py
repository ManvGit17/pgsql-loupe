"""SQLAlchemy and asyncpg users may not have psycopg installed: everything except plan capture
must work without it. Runs in a subprocess where `import psycopg` fails."""

from __future__ import annotations

import subprocess
import sys

SCRIPT = r"""
import sys
sys.modules["psycopg"] = None  # from here on, `import psycopg` raises ImportError

import pgsql_loupe.analyzers
import pgsql_loupe.collectors.asyncpg
import pgsql_loupe.collectors.sqlalchemy
import pgsql_loupe.explain
import pgsql_loupe.pytest_plugin
import pgsql_loupe.testing
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from pgsql_loupe.asgi import ExplainOptions, LoupeConfig, install


async def home(request):
    return PlainTextResponse("ok")


app = Starlette(routes=[Route("/", home)])
install(app, LoupeConfig(enabled=True, explain=ExplainOptions(dsn="postgresql://unused")))
with TestClient(app, client=("127.0.0.1", 1), base_url="http://127.0.0.1") as client:
    response = client.get("/?lens=plan")
    assert response.text == "ok"
    trace = client.get("/__lens/api/requests/" + response.headers["x-lens-id"]).json()
    assert client.get("/__lens/").status_code == 200
print(trace["plan_note"])
"""


def test_everything_but_plan_capture_works_without_psycopg() -> None:
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", SCRIPT], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("plan capture needs psycopg: pip install pgsql-loupe[psycopg]")


SYNC_SQLALCHEMY = r"""
import os, sys
sys.modules["greenlet"] = None  # sync SQLAlchemy apps do not install greenlet
from sqlalchemy import create_engine, text
import pgsql_loupe
from pgsql_loupe.collectors.sqlalchemy import instrument_engine

engine = create_engine(os.environ["TEST_PG_DSN"].replace("postgresql://", "postgresql+psycopg://"))
instrument_engine(engine)
with engine.connect() as conn, pgsql_loupe.trace() as t:
    conn.execute(text("SELECT 1"))
print([s.sql for s in t.statements])
"""


def test_sync_sqlalchemy_works_without_greenlet(pg_dsn: str) -> None:
    import os

    env = {**os.environ, "TEST_PG_DSN": pg_dsn}
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", SYNC_SQLALCHEMY],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "['SELECT 1']"
