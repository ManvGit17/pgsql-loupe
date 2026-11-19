"""Browser test: the example app under uvicorn, read through the panel with Playwright.

Run with `pytest -m e2e` (needs `playwright install chromium`).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples" / "fastapi-psycopg"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def server(pg_dsn: str) -> Iterator[str]:
    port = free_port()
    env = {**os.environ, "PGSQL_LOUPE_ENABLED": "1", "DATABASE_URL": pg_dsn}
    for name in ("APP_ENV", "ENVIRONMENT", "ENV", "PGSQL_LOUPE_ENV"):
        env.pop(name, None)
    # Output goes to a file, not a pipe: a full pipe that nobody reads would block uvicorn.
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=EXAMPLE_DIR,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(f"{base}/artists", timeout=1).close()
                    break
                except OSError:
                    if proc.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(f"uvicorn exited: {log.read().decode()}") from None
                    time.sleep(0.2)
            else:
                raise RuntimeError("uvicorn did not start")
            yield base
        finally:
            proc.terminate()
            proc.wait(timeout=10)


def test_panel_shows_the_plan_of_a_statement(server: str, page: Page) -> None:
    # Make a request with plan capture, as a developer would from the browser.
    response = page.request.get(f"{server}/artists/tracks?lens=plan")
    assert response.ok
    lens_id = response.headers["x-lens-id"]

    page.goto(f"{server}/__lens/#{lens_id}")
    detail = page.get_by_role("article", name="GET /artists/tracks")
    expect(detail).to_be_visible()
    expect(detail.get_by_role("list", name="Warnings")).to_contain_text("N+1")

    first = detail.get_by_role("button", name="SELECT id, name FROM example_artists", exact=False)
    first.first.click()
    plan = detail.get_by_role("list", name="Query plan").first
    expect(plan).to_be_visible()
    expect(plan).to_contain_text("example_artists")
    expect(detail).to_contain_text("EXPLAIN ANALYZE")


def test_explain_button_and_keyboard_navigation(server: str, page: Page) -> None:
    a = page.request.get(f"{server}/artists?lens=1").headers["x-lens-id"]
    b = page.request.get(f"{server}/artists/tracks-fixed?lens=1").headers["x-lens-id"]

    page.goto(f"{server}/__lens/#{a}")
    detail = page.get_by_role("article", name="GET /artists")
    detail.get_by_role("button", name="SELECT id, name", exact=False).first.click()
    detail.get_by_role("button", name="Explain analyze").click()
    expect(detail.get_by_role("list", name="Query plan")).to_be_visible()

    # Arrow keys move through the request list: newest (b) is first, then a.
    requests = page.get_by_role("list", name="Traced requests")
    requests.get_by_role("button").filter(has_text="/artists").nth(1).focus()
    page.keyboard.press("ArrowUp")
    expect(page.get_by_role("article", name="GET /artists/tracks-fixed")).to_be_visible()
    assert b in page.url


def test_theme_toggle(server: str, page: Page) -> None:
    page.goto(f"{server}/__lens/")
    html = page.locator("html")
    before = html.get_attribute("data-theme")
    page.get_by_role("button", name="Switch to", exact=False).click()
    after = html.get_attribute("data-theme")
    assert {before, after} == {"light", "dark"}
