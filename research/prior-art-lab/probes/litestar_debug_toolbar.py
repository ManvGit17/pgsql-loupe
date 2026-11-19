# /// script
# requires-python = "==3.13.*"
# dependencies = [
#   "fastapi==0.164.0",
#   "sqlalchemy==2.1.9",
#   "psycopg[binary]==3.3.9",
#   "asyncpg==0.32.0",
#   "httpx==0.28.1",
#   "greenlet==3.5.6",
#   "litestar-debug-toolbar[fastapi,advanced-alchemy]==1.1.1",
# ]
# ///
"""Probe: litestar-debug-toolbar 1.1.1 (FastAPI integration + SQLAlchemy panel)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from debug_toolbar.fastapi import FastAPIDebugToolbarConfig, setup_debug_toolbar

from labapp import build_app, plays_and_audit, run

PANEL = "debug_toolbar.extras.advanced_alchemy.panel.SQLAlchemyPanel"


def sql_panel(data: dict) -> dict:
    for key, value in data.get("panel_data", data.get("panels", {})).items():
        if "SQL" in key:
            return value
    return {}


async def main() -> None:
    app = build_app()
    toolbar = setup_debug_toolbar(app, FastAPIDebugToolbarConfig(enabled=True, extra_panels=[PANEL]))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://lab") as client:

        async def last_panel() -> dict:
            stored = toolbar.storage.get_all()
            return sql_panel(stored[0][1]) if stored else {}

        print("stored keys:", list((toolbar.storage.get_all() or [(None, {})])[0][1].keys()))
        for method, path in [
            ("GET", "/sa/nplus1"),
            ("GET", "/sa/dup"),
            ("POST", "/sa/write"),
            ("GET", "/sa/seq"),
            ("GET", "/sa/error"),
            ("GET", "/raw/nplus1"),
            ("GET", "/apg/nplus1"),
        ]:
            r = await client.request(method, path)
            p = await last_panel()
            if not p and toolbar.storage.get_all():
                print("  storage entry keys:", list(toolbar.storage.get_all()[0][1].keys()))
            print(
                f"{method} {path}: status={r.status_code} queries={p.get('query_count')} "
                f"n_plus_one={p.get('n_plus_one_count')} duplicates={p.get('duplicate_count')}"
            )
            for q in (p.get("queries") or [])[:2]:
                print(f"    sql={q['sql'][:60]!r} params={q['parameters']!r}")

        # EXPLAIN: the UI posts to /_debug_toolbar/api/explain.
        before = await plays_and_audit()
        r = await client.post(
            "/_debug_toolbar/api/explain",
            json={"sql": "UPDATE tracks SET plays = plays + 1 WHERE id = %(t)s", "parameters": {"t": 7}},
        )
        print(f"POST /_debug_toolbar/api/explain -> {r.status_code}")
        print("data unchanged by explain attempt:", before == await plays_and_audit())

        # EXPLAIN executor called directly, as the Litestar route would.
        from debug_toolbar.extras.advanced_alchemy.panel import ExplainExecutor

        from labapp import engine

        res = await ExplainExecutor.execute_explain(
            engine, "SELECT count(*) FROM events WHERE payload = %(p)s", {"p": "x"}
        )
        print("ExplainExecutor (psycopg pyformat params):", json.dumps(res)[:300])
        res = await ExplainExecutor.execute_explain(engine, "SELECT count(*) FROM events WHERE payload = 'x'", None)
        print("ExplainExecutor (no params):", res.get("explain_sql"), "|", (res.get("plan") or res.get("error", ""))[:200])

        # Concurrency: two overlapping requests; does each trace hold only its own statement?
        await asyncio.gather(client.get("/sa/slow?tag=A"), client.get("/sa/slow?tag=B"))
        for _, data in toolbar.storage.get_all()[:2]:
            tags = [q["parameters"] for q in sql_panel(data).get("queries", [])]
            print("concurrent request trace params:", tags)


if __name__ == "__main__":
    run(main())
