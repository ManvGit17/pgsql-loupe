"""The examples/fastapi-psycopg app, run for real against PostgreSQL."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "fastapi-psycopg" / "app.py"
LOCAL = ("127.0.0.1", 50000)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, pg_dsn: str) -> pytest.MonkeyPatch:
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    for name in ("PGSQL_LOUPE_ENABLED", "PGSQL_LOUPE_ALLOW_PRODUCTION", "PGSQL_LOUPE_ENV",
                 "APP_ENV", "ENVIRONMENT", "ENV"):  # fmt: skip
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def load_example() -> ModuleType:
    """A fresh copy of the example module (it reads the environment at import time)."""
    spec = importlib.util.spec_from_file_location(f"example_{uuid.uuid4().hex}", EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_request_returns_trace_id_and_json_has_its_statements(
    clean_env: pytest.MonkeyPatch,
) -> None:
    clean_env.setenv("PGSQL_LOUPE_ENABLED", "1")
    example = load_example()
    with TestClient(example.app, client=LOCAL) as client:
        response = client.get("/artists/tracks?lens=1")
        assert response.status_code == 200
        artists = response.json()
        lens_id = response.headers["x-lens-id"]
        assert response.headers["server-timing"].startswith("db;dur=")

        trace = client.get(f"/__lens/api/requests/{lens_id}").json()

    assert trace["id"] == lens_id
    assert (trace["method"], trace["path"], trace["status"]) == ("GET", "/artists/tracks", 200)
    statements = trace["statements"]
    assert len(statements) == 1 + len(artists)  # the deliberate N+1
    assert statements[0]["sql"] == "SELECT id, name FROM example_artists ORDER BY id"
    assert statements[1]["params"] == [str(artists[0]["id"])]
    assert statements[1]["call_site"]["file"] == str(EXAMPLE)
    assert trace["statement_count"] == len(statements)


def test_routes_return_404_when_disabled(clean_env: pytest.MonkeyPatch) -> None:
    example = load_example()  # PGSQL_LOUPE_ENABLED not set
    with TestClient(example.app, client=LOCAL) as client:
        response = client.get("/artists?lens=1")
        assert response.status_code == 200
        assert "x-lens-id" not in response.headers
        assert "server-timing" not in response.headers
        assert client.get("/__lens/api/requests").status_code == 404
