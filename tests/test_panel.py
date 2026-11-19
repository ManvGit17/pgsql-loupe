"""Serving the panel, and the optional toggle injected into HTML pages."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from pgsql_loupe.asgi import LoupeConfig, install
from pgsql_loupe.asgi.panel import inject

LOCAL = ("127.0.0.1", 50000)
LOCAL_URL = "http://127.0.0.1:8000"
ON = {"PGSQL_LOUPE_ENABLED": "1"}
PAGE = "<!doctype html><html><body><h1>Hello</h1></body></html>"


@pytest.fixture(scope="module")
def pool(pg_dsn: str) -> Iterator[ConnectionPool[Any]]:
    from pgsql_loupe.collectors.psycopg import instrument

    with ConnectionPool(pg_dsn, min_size=1, max_size=2, configure=instrument) as p:
        yield p


def make_app(pool: ConnectionPool[Any], config: LoupeConfig | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/page", response_class=HTMLResponse)
    def page() -> str:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        return PAGE

    @app.get("/data")
    def data() -> dict[str, int]:
        return {"n": 1}

    install(app, config, environ=ON)
    return app


def test_panel_page_and_assets(pool: ConnectionPool[Any]) -> None:
    with TestClient(make_app(pool), client=LOCAL, base_url=LOCAL_URL) as client:
        page = client.get("/__lens/")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert 'data-prefix="/__lens"' in page.text
        csp = page.headers["content-security-policy"]
        assert "default-src 'none'" in csp and "connect-src 'self'" in csp
        assert client.get("/__lens").status_code == 200
        js = client.get("/__lens/static/panel.js")
        css = client.get("/__lens/static/panel.css")
        assert js.headers["content-type"].startswith("text/javascript") and len(js.content) > 1000
        assert css.headers["content-type"].startswith("text/css")
        assert client.get("/__lens/static/other.js").status_code == 404


def test_panel_follows_a_custom_prefix(pool: ConnectionPool[Any]) -> None:
    app = make_app(pool, LoupeConfig(prefix="/_debug/sql"))
    with TestClient(app, client=LOCAL, base_url=LOCAL_URL) as client:
        page = client.get("/_debug/sql/")
        assert 'data-prefix="/_debug/sql"' in page.text
        assert 'src="/_debug/sql/static/panel.js"' in page.text


def test_panel_is_hidden_from_remote_clients(pool: ConnectionPool[Any]) -> None:
    with TestClient(make_app(pool), client=("203.0.113.9", 1), base_url=LOCAL_URL) as client:
        assert client.get("/__lens/").status_code == 404
        assert client.get("/__lens/static/panel.js").status_code == 404


def test_toggle_is_off_by_default(pool: ConnectionPool[Any]) -> None:
    with TestClient(make_app(pool), client=LOCAL, base_url=LOCAL_URL) as client:
        assert client.get("/page?lens=1").text == PAGE


def test_toggle_is_injected_into_traced_html_only(pool: ConnectionPool[Any]) -> None:
    app = make_app(pool, LoupeConfig(inject_toggle=True))
    with TestClient(app, client=LOCAL, base_url=LOCAL_URL) as client:
        traced = client.get("/page?lens=1")
        lens_id = traced.headers["x-lens-id"]
        assert f'href="/__lens/#{lens_id}"' in traced.text
        assert "SQL: 1 statement</a></body>" in traced.text
        assert int(traced.headers["content-length"]) == len(traced.content)
        assert client.get("/page").text == PAGE  # not traced: untouched
        assert client.get("/data?lens=1").json() == {"n": 1}  # not HTML: untouched


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"<html><body>x</body></html>", b"<html><body>x[B]</body></html>"),
        (b"<BODY>x</BODY>", b"<BODY>x[B]</BODY>"),
        (b"no body tag", b"no body tag[B]"),
    ],
)
def test_inject(body: bytes, expected: bytes) -> None:
    assert inject(body, b"[B]") == expected
