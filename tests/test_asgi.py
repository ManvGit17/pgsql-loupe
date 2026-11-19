"""LoupeMiddleware, the guard and the JSON API, with a real psycopg pool."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from pgsql_loupe.asgi import LoupeConfig, LoupeMiddleware, ProductionGuardError, install
from pgsql_loupe.asgi.middleware import requested_mode

LOCAL = ("127.0.0.1", 50000)
ON = {"PGSQL_LOUPE_ENABLED": "1"}


@pytest.fixture(scope="module")
def pool(pg_dsn: str) -> Iterator[ConnectionPool[Any]]:
    from pgsql_loupe.collectors.psycopg import instrument

    with ConnectionPool(pg_dsn, min_size=1, max_size=2, configure=instrument) as p:
        yield p


def make_app(
    pool: ConnectionPool[Any], config: LoupeConfig | None = None, environ: dict[str, str] = ON
) -> FastAPI:
    app = FastAPI()

    @app.get("/one")
    def one() -> int:
        with pool.connection() as conn:
            row = conn.execute("SELECT 1").fetchone()
        return 0 if row is None else int(row[0])

    @app.get("/boom")
    def boom() -> None:
        with pool.connection() as conn:
            conn.execute("SELECT * FROM no_such_table")

    install(app, config, environ=environ)
    return app


def requests_list(client: TestClient) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = client.get("/__lens/api/requests").json()["requests"]
    return data


def test_untraced_requests_are_left_alone(pool: ConnectionPool[Any]) -> None:
    with TestClient(make_app(pool), client=LOCAL) as client:
        response = client.get("/one")
        assert "x-lens-id" not in response.headers
        assert requests_list(client) == []


def test_header_activation_and_list_endpoint(pool: ConnectionPool[Any]) -> None:
    with TestClient(make_app(pool), client=LOCAL) as client:
        lens_id = client.get("/one", headers={"X-Lens": "1"}).headers["x-lens-id"]
        plan_id = client.get("/one?lens=plan").headers["x-lens-id"]
        listed = requests_list(client)
    assert [r["id"] for r in listed] == [plan_id, lens_id]  # newest first
    assert [r["mode"] for r in listed] == ["plan", "trace"]
    assert all(r["statement_count"] == 1 and r["status"] == 200 for r in listed)


def test_failing_statement_appears_in_the_trace(pool: ConnectionPool[Any]) -> None:
    with TestClient(make_app(pool), client=LOCAL, raise_server_exceptions=False) as client:
        response = client.get("/boom?lens=1")
        assert response.status_code == 500
        # Starlette's error handler sends the 500 outside our middleware: no header.
        assert "x-lens-id" not in response.headers
        (listed,) = requests_list(client)
        trace = client.get(f"/__lens/api/requests/{listed['id']}").json()
    assert (trace["status"], trace["exception"]) == (500, "UndefinedTable")
    assert trace["error_count"] == 1
    assert trace["statements"][0]["sqlstate"] == "42P01"


def test_non_local_clients_are_never_traced_and_cannot_see_the_api(
    pool: ConnectionPool[Any],
) -> None:
    app = make_app(pool)
    with TestClient(app, client=("203.0.113.9", 4000)) as remote:
        assert "x-lens-id" not in remote.get("/one?lens=1").headers
        assert remote.get("/__lens/api/requests").status_code == 404
    with TestClient(app, client=LOCAL) as local:
        assert requests_list(local) == []


def test_forwarded_requests_count_as_non_local(pool: ConnectionPool[Any]) -> None:
    with TestClient(make_app(pool), client=LOCAL) as client:
        proxied = client.get("/one?lens=1", headers={"X-Forwarded-For": "203.0.113.9"})
        assert "x-lens-id" not in proxied.headers
        api = client.get("/__lens/api/requests", headers={"Forwarded": "for=203.0.113.9"})
        assert api.status_code == 404


def test_custom_authorize_callback(pool: ConnectionPool[Any]) -> None:
    config = LoupeConfig(authorize=lambda scope: scope["client"][0] == "10.0.0.5")
    with TestClient(make_app(pool, config), client=("10.0.0.5", 1)) as client:
        assert "x-lens-id" in client.get("/one?lens=1").headers


def test_ring_buffer_keeps_only_the_latest(pool: ConnectionPool[Any]) -> None:
    with TestClient(make_app(pool, LoupeConfig(history=2)), client=LOCAL) as client:
        ids = [client.get("/one?lens=1").headers["x-lens-id"] for _ in range(3)]
        assert [r["id"] for r in requests_list(client)] == [ids[2], ids[1]]
        assert client.get(f"/__lens/api/requests/{ids[0]}").status_code == 404


def test_api_rejects_other_methods_and_paths(pool: ConnectionPool[Any]) -> None:
    with TestClient(make_app(pool), client=LOCAL) as client:
        assert client.post("/__lens/api/requests").status_code == 405
        assert client.get("/__lens/api/nothing").status_code == 404
        assert client.get("/__lens/api/requests").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("marker", ["APP_ENV", "ENVIRONMENT", "ENV", "PGSQL_LOUPE_ENV"])
def test_production_guard_refuses_to_start(marker: str) -> None:
    environ = ON | {marker: "Production"}
    with pytest.raises(ProductionGuardError):
        install(FastAPI(), environ=environ)
    with pytest.raises(ProductionGuardError):
        LoupeMiddleware(FastAPI(), environ=environ)


def test_production_guard_can_be_overridden_explicitly() -> None:
    environ = ON | {"APP_ENV": "production", "PGSQL_LOUPE_ALLOW_PRODUCTION": "1"}
    assert install(FastAPI(), environ=environ) is True


def test_disabled_install_leaves_the_app_untouched() -> None:
    app = FastAPI()
    assert install(app, environ={"APP_ENV": "production"}) is False
    assert app.user_middleware == []


@pytest.mark.parametrize(
    ("query", "headers", "expected"),
    [
        (b"", [], None),
        (b"lens=1", [], "trace"),
        (b"lens=plan", [], "plan"),
        (b"lens=0", [], None),
        (b"a=1&lens=TRUE", [], "trace"),
        (b"", [(b"x-lens", b"plan")], "plan"),
        (b"lens=1", [(b"X-Lens", b"off")], None),
    ],
)
def test_requested_mode(query: bytes, headers: list[tuple[bytes, bytes]], expected: str) -> None:
    assert requested_mode({"query_string": query, "headers": headers}) == expected
