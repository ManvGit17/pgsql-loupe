"""The examples/fastapi app on all three drivers, run for real against PostgreSQL."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "fastapi" / "app.py"
LOCAL = ("127.0.0.1", 50000)
LOCAL_URL = "http://127.0.0.1:8000"


DRIVERS = ["psycopg", "sqlalchemy", "asyncpg"]


@pytest.fixture(params=DRIVERS)
def driver(request: pytest.FixtureRequest) -> str:
    value: str = request.param
    return value


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, pg_dsn: str, driver: str) -> pytest.MonkeyPatch:
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    monkeypatch.setenv("EXAMPLE_DRIVER", driver)
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
    with TestClient(example.app, client=LOCAL, base_url=LOCAL_URL) as client:
        response = client.get("/artists/tracks?lens=1")
        assert response.status_code == 200
        artists = response.json()
        lens_id = response.headers["x-lens-id"]
        assert response.headers["server-timing"].startswith("db;dur=")

        trace = client.get(f"/__lens/api/requests/{lens_id}").json()

    assert trace["id"] == lens_id
    assert (trace["method"], trace["path"], trace["status"]) == ("GET", "/artists/tracks", 200)
    assert all(s["error"] is None for s in trace["statements"])
    statements = trace["statements"]
    assert len(statements) == 1 + len(artists)  # the deliberate N+1
    assert statements[0]["sql"] == "SELECT id, name FROM example_artists ORDER BY id"
    assert list(_values(statements[1]["params"])) == [str(artists[0]["id"])]
    assert statements[1]["call_site"]["file"] == str(EXAMPLE)
    assert trace["statement_count"] == len(statements)


def test_routes_return_404_when_disabled(clean_env: pytest.MonkeyPatch) -> None:
    example = load_example()  # PGSQL_LOUPE_ENABLED not set
    with TestClient(example.app, client=LOCAL, base_url=LOCAL_URL) as client:
        response = client.get("/artists?lens=1")
        assert response.status_code == 200
        assert "x-lens-id" not in response.headers
        assert "server-timing" not in response.headers
        assert client.get("/__lens/api/requests").status_code == 404


def test_plan_mode_on_the_example(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("PGSQL_LOUPE_ENABLED", "1")
    example = load_example()
    with TestClient(example.app, client=LOCAL, base_url=LOCAL_URL) as client:
        first = client.get("/artists/tracks").json()
        lens_id = client.get("/artists/tracks?lens=plan").headers["x-lens-id"]
        trace = client.get(f"/__lens/api/requests/{lens_id}").json()
        assert client.get("/artists/tracks").json() == first  # data unchanged
    plans = [s["plan"] for s in trace["statements"]]
    assert all(p is not None and p["mode"] == "analyze" for p in plans)
    # The N+1 queries differ only in their parameter, so each is explained separately.
    assert trace["plan_note"] == f"{len(plans)} plan(s) captured"


def test_nplus1_is_flagged_and_the_fixed_version_is_not(
    clean_env: pytest.MonkeyPatch, driver: str
) -> None:
    clean_env.setenv("PGSQL_LOUPE_ENABLED", "1")
    example = load_example()
    with TestClient(example.app, client=LOCAL, base_url=LOCAL_URL) as client:
        slow = client.get("/artists/tracks?lens=1")
        fast = client.get("/artists/tracks-fixed?lens=1")
        assert slow.json() == fast.json()  # same answer
        n1 = client.get(f"/__lens/api/requests/{slow.headers['x-lens-id']}").json()
        fixed = client.get(f"/__lens/api/requests/{fast.headers['x-lens-id']}").json()
        listed = {r["path"]: r for r in client.get("/__lens/api/requests").json()["requests"]}

    artists = len(slow.json())
    (shape,) = n1["analysis"]["nplus1"]
    assert shape["count"] == artists
    assert shape["fingerprint"] == (
        "select title from example_tracks where artist_id = ? order by id"
    )
    loop_line = _line_of(f"# N+1 ({driver})")
    assert shape["call_sites"] == [f"{EXAMPLE}:{loop_line}"]
    assert n1["statements"][1]["fingerprint"] == shape["fingerprint"]
    assert fixed["analysis"]["nplus1"] == []
    assert fixed["statement_count"] == 2
    assert (
        listed["/artists/tracks"]["nplus1_count"],
        listed["/artists/tracks-fixed"]["nplus1_count"],
    ) == (1, 0)


def _values(params: list[str] | dict[str, str]) -> list[str]:
    return list(params.values()) if isinstance(params, dict) else params


def _line_of(text: str) -> int:
    for number, line in enumerate(EXAMPLE.read_text(encoding="utf-8").splitlines(), start=1):
        if text in line:
            return number
    raise AssertionError(text)
