"""Re-run every prior-art probe and write its output to results/.

Usage (from this folder, with Docker running):
    docker compose up -d --wait
    uv run --python 3.13 run_all.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

LAB = ["sqlalchemy==2.1.9", "psycopg[binary]==3.3.9", "asyncpg==0.32.0", "httpx==0.28.1", "greenlet==3.5.6"]


def with_deps(*deps: str) -> list[str]:
    """Plain `python` (ignores the script header) with an explicit dependency set."""
    out = ["uv", "run", "--no-project", "--python", "3.13"]
    for dep in deps:
        out += ["--with", dep]
    return [*out, "python"]


# Pinned headers in each probe are the "works best" setup; the *_current runs show
# what happens with today's latest FastAPI / SQLAlchemy.
PROBES = {
    "litestar_debug_toolbar.txt": ["uv", "run", "--script", "probes/litestar_debug_toolbar.py"],
    "fastapi_debug_toolbar.txt": ["uv", "run", "--script", "probes/fastapi_debug_toolbar.py"],
    "fastapi_debug_toolbar_current.txt": [
        *with_deps(*LAB, "fastapi==0.164.0", "fastapi-debug-toolbar==0.6.3"),
        "probes/fastapi_debug_toolbar.py",
    ],
    "queryspy.txt": ["uv", "run", "--script", "probes/queryspy_probe.py"],
    "nplusone.txt": ["uv", "run", "--script", "probes/nplusone_probe.py"],
    "nplusone_current.txt": [
        *with_deps("sqlalchemy==2.1.9", "psycopg[binary]==3.3.9", "nplusone==1.0.0"),
        "probes/nplusone_probe.py",
    ],
}


def scrub(text: str) -> str:
    """Drop local absolute paths (home folder, checkout location) from committed output."""
    for path, label in ((HERE, "."), (Path.home(), "~")):
        for form in (str(path), str(path).replace("\\", "/")):
            text = text.replace(form, label)
    return text


def main() -> int:
    RESULTS.mkdir(exist_ok=True)
    for out, cmd in PROBES.items():
        proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, encoding="utf-8")
        text = proc.stdout + (f"\n[exit {proc.returncode}]\n{proc.stderr[-600:]}" if proc.returncode else "")
        (RESULTS / out).write_text(scrub(text), encoding="utf-8")
        print(f"{out}: exit {proc.returncode}")
    sql = (HERE / "probes/auto_explain.sql").read_text(encoding="utf-8")
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "lab", "-d", "lab", "-q", "-f", "-"],
        cwd=HERE, input=sql, capture_output=True, text=True, encoding="utf-8",
    )
    (RESULTS / "auto_explain.txt").write_text(scrub(proc.stdout + proc.stderr), encoding="utf-8")
    print(f"auto_explain.txt: exit {proc.returncode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
