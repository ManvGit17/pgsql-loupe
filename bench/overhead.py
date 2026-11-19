"""Measure pgsql-loupe's overhead. The README's overhead numbers come only from this script.

    docker compose up -d --wait
    uv run python bench/overhead.py            # writes bench/results/<date>-<os>.md

Two measurements, both designed so that changes in machine speed during the run (which on a
laptop can exceed the effect being measured) cannot bias the comparison:

1. Tracer cost per statement: the psycopg collector's real recording path (`_record_sync` on
   a real cursor) wrapped around a no-op instead of a database call. Pure CPU work, so it is
   stable; it is exactly what tracing adds to each statement.
2. Per request, interleaved: the example app (psycopg driver, `GET /artists/tracks`, 6
   statements) on two servers (lens disabled, lens enabled). One request at a time, rotating
   through the four setups, each on its own connection: every setup is measured at the same
   moments, and no request waits behind another (no queueing to magnify differences).
"""

from __future__ import annotations

import argparse
import os
import platform
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import httpx
import psycopg

import pgsql_loupe
from pgsql_loupe.collectors.psycopg import _record_sync, instrument

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "fastapi"
BATCH = 1000  # statements per trace, as in a (large) request


# --- 1. tracer cost per statement ---------------------------------------------------------


def _noop() -> None:
    return None


def tracer_cost(dsn: str, n: int, rounds: int) -> dict[str, list[float]]:
    """Microseconds per statement: bare call, recording path without and with a trace."""
    with psycopg.connect(dsn) as conn:
        instrument(conn)
        cursor = conn.cursor()
        params = (1,)

        def bare() -> float:
            start = time.perf_counter_ns()
            for _ in range(n):
                _noop()
            return (time.perf_counter_ns() - start) / n / 1000

        def recorded(traced: bool) -> float:
            start = time.perf_counter_ns()
            for _ in range(n // BATCH):
                block = pgsql_loupe.trace() if traced else None
                if block:
                    block.__enter__()
                for _ in range(BATCH):
                    _record_sync(cursor, "execute", "SELECT %s", params, _noop)
                if block:
                    block.__exit__(None, None, None)
            return (time.perf_counter_ns() - start) / n / 1000

        recorded(True)  # warm up caches (call-site lookup, imports)
        runs: dict[str, list[float]] = {"bare": [], "untraced": [], "traced": []}
        for _ in range(rounds):
            runs["bare"].append(bare())
            runs["untraced"].append(recorded(False))
            runs["traced"].append(recorded(True))
        cursor.close()
    return runs


def select1_wall(dsn: str, n: int) -> tuple[float, float]:
    """Median wall µs of one `SELECT 1`, plain vs traced, interleaved statement by statement."""
    with (
        psycopg.connect(dsn, autocommit=True) as plain,
        psycopg.connect(dsn, autocommit=True) as inst,
    ):
        instrument(inst)
        plain_times: list[int] = []
        traced_times: list[int] = []
        with pgsql_loupe.trace():
            for _ in range(n):
                start = time.perf_counter_ns()
                plain.execute("SELECT 1")
                plain_times.append(time.perf_counter_ns() - start)
                start = time.perf_counter_ns()
                inst.execute("SELECT 1")
                traced_times.append(time.perf_counter_ns() - start)
    return statistics.median(plain_times) / 1000, statistics.median(traced_times) / 1000


# --- 2. per request, paired --------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def serve(dsn: str, enabled: bool) -> tuple[subprocess.Popen[bytes], str]:
    port = free_port()
    env = {**os.environ, "DATABASE_URL": dsn, "EXAMPLE_DRIVER": "psycopg"}
    for name in ("PGSQL_LOUPE_ENABLED", "APP_ENV", "ENVIRONMENT", "ENV", "PGSQL_LOUPE_ENV"):
        env.pop(name, None)
    if enabled:
        env["PGSQL_LOUPE_ENABLED"] = "1"
    command = [sys.executable, "-m", "uvicorn", "app:app", "--port", str(port)]
    command += ["--log-level", "warning"]
    proc = subprocess.Popen(
        command, cwd=EXAMPLE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(150):
        try:
            urllib.request.urlopen(f"{base}/artists", timeout=1).close()
            return proc, base
        except OSError:
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("uvicorn did not start")


def per_request(dsn: str, requests: int) -> dict[str, list[float]]:
    """Latency in ms per setup, requests interleaved one at a time."""
    off_proc, off = serve(dsn, enabled=False)
    on_proc, on = serve(dsn, enabled=True)
    urls = {
        "lens disabled": f"{off}/artists/tracks",
        "enabled, not requested": f"{on}/artists/tracks",
        "?lens=1": f"{on}/artists/tracks?lens=1",
        "?lens=plan": f"{on}/artists/tracks?lens=plan",
    }
    clients = {name: httpx.Client(timeout=30) for name in urls}
    latencies: dict[str, list[float]] = {name: [] for name in urls}
    try:
        for warm_up in (True, False):
            for _ in range(requests // 10 if warm_up else requests):
                for name, url in urls.items():
                    started = time.perf_counter()
                    clients[name].get(url).raise_for_status()
                    if not warm_up:
                        latencies[name].append((time.perf_counter() - started) * 1000)
    finally:
        for client in clients.values():
            client.close()
        for proc in (off_proc, on_proc):
            proc.terminate()
            proc.wait(timeout=10)
    return latencies


# --- report ------------------------------------------------------------------------------


def environment(dsn: str) -> list[str]:
    with psycopg.connect(dsn) as c:
        row = c.execute("SHOW server_version").fetchone()
    pg = row[0] if row else "?"
    packages = ("pgsql-loupe", "psycopg", "fastapi", "starlette", "uvicorn", "httpx")
    return [
        f"- Date: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        f"- OS: {platform.system()} {platform.release()} ({platform.machine()})",
        f"- CPU: {platform.processor() or 'unknown'}, {os.cpu_count()} logical cores",
        f"- Python {platform.python_version()}, PostgreSQL {pg} (Docker, same machine)",
        "- " + ", ".join(f"{p} {version(p)}" for p in packages),
    ]


def pct(values: list[float], q: int) -> float:
    return statistics.quantiles(values, n=100)[q - 1]


def report(
    dsn: str,
    cost: dict[str, list[float]],
    wall: tuple[float, float],
    request: dict[str, list[float]],
    args: argparse.Namespace,
) -> str:
    bare = statistics.median(cost["bare"])
    untraced = [u - b for u, b in zip(cost["untraced"], cost["bare"], strict=True)]
    traced = [t - b for t, b in zip(cost["traced"], cost["bare"], strict=True)]
    base_p50 = statistics.median(request["lens disabled"])
    base_p95 = pct(request["lens disabled"], 95)
    lines = [
        "# pgsql-loupe overhead",
        "",
        f"Produced by `uv run python bench/overhead.py --statements {args.statements} "
        f"--rounds {args.rounds} --requests {args.requests}`.",
        "",
        *environment(dsn),
        "",
        "## Tracer cost per statement",
        "",
        "The psycopg collector's recording path around a no-op instead of a database call, "
        f"{args.statements:,} statements per round, {args.rounds} rounds (median; each round "
        "in brackets).",
        "",
        "| Path | Added per statement |",
        "|---|---:|",
        f"| instrumented, no active trace | {statistics.median(untraced):.2f} µs "
        f"({', '.join(f'{v:.2f}' for v in untraced)}) |",
        f"| instrumented and traced | {statistics.median(traced):.2f} µs "
        f"({', '.join(f'{v:.2f}' for v in traced)}) |",
        "",
        f"For scale: one `SELECT 1` against this PostgreSQL took {wall[0]:.0f} µs (median of "
        f"{min(args.statements, 5000):,}, plain psycopg) and {wall[1]:.0f} µs traced. The bare "
        f"call loop itself costs {bare:.3f} µs.",
        "",
        f"## Per request (`GET /artists/tracks`, 6 statements; {args.requests:,} requests per "
        "setup, one at a time, setups interleaved)",
        "",
        "| Setup | p50 ms | p95 ms | p50 vs disabled | p95 vs disabled |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, values in request.items():
        p50, p95 = statistics.median(values), pct(values, 95)
        lines.append(
            f"| {name} | {p50:.2f} | {p95:.2f} | {p50 - base_p50:+.2f} ms "
            f"| {p95 - base_p95:+.2f} ms |"
        )
    lines += [
        "",
        'The three "enabled" rows run on the same server process and compare most precisely',
        'with each other; "lens disabled" is a second process, and the two processes can differ',
        "by a few tenths of a millisecond on their own.",
        "",
        "Latency is measured by the client and ends when the response arrives. `?lens=plan`",
        "replays each statement under EXPLAIN after the response has been sent, so that work",
        "is not in its latency, but it does use the enabled server's CPU while the next",
        "requests run.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    default_dsn = os.environ.get("TEST_PG_DSN", "postgresql://test:test@127.0.0.1:54318/test")
    parser.add_argument("--dsn", default=default_dsn)
    parser.add_argument("--statements", type=int, default=100_000)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    print("Tracer cost...", flush=True)
    cost = tracer_cost(args.dsn, args.statements, args.rounds)
    wall = select1_wall(args.dsn, min(args.statements, 5000))
    print("Per request...", flush=True)
    request = per_request(args.dsn, args.requests)
    text = report(args.dsn, cost, wall, request, args)
    name = f"{datetime.now(UTC):%Y-%m-%d}-{platform.system().lower()}.md"
    out = args.out or ROOT / "bench" / "results" / name
    out.write_text(text, encoding="utf-8")
    sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
    print(f"Written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
