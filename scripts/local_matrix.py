"""Run the CI checks locally: lint once, then pytest for every Python x PostgreSQL pair.

Usage: uv run python scripts/local_matrix.py   (Docker must be running)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHONS = ["3.11", "3.12", "3.13", "3.14", "3.15"]
POSTGRES = {"16": 54316, "17": 54317, "18": 54318}


def run(cmd: list[str], env: dict[str, str] | None = None) -> bool:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, env=env).returncode == 0


def find_python(version: str) -> str:
    """Full path of a Python interpreter for `version`, installing one with uv if needed.

    Passing the full path avoids uv's Windows "minor version" link (cpython-3.X-...),
    which could not be created on the development machine.
    """
    find = ["uv", "python", "find", version]
    found = subprocess.run(find, cwd=ROOT, capture_output=True, text=True)
    if found.returncode != 0:
        # The install may report an error about that link and still leave a usable interpreter.
        subprocess.run(["uv", "python", "install", version], cwd=ROOT)
        found = subprocess.run(find, cwd=ROOT, capture_output=True, text=True, check=True)
    return found.stdout.strip()


def main() -> int:
    results: dict[str, bool] = {}
    if not run(["docker", "compose", "up", "-d", "--wait"]):
        return 1
    results["ruff check"] = run(["uv", "run", "ruff", "check", "."])
    results["ruff format"] = run(["uv", "run", "ruff", "format", "--check", "."])
    results["mypy"] = run(["uv", "run", "mypy"])
    for py in PYTHONS:
        env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(ROOT / ".venv-matrix" / f"py{py}")}
        env.pop("VIRTUAL_ENV", None)
        interpreter = find_python(py)
        for major, port in POSTGRES.items():
            env["TEST_PG_DSN"] = f"postgresql://test:test@127.0.0.1:{port}/test"
            env["EXPECT_PG_MAJOR"] = major
            ok = run(["uv", "run", "--python", interpreter, "pytest", "-q"], env)
            results[f"pytest py{py} pg{major}"] = ok
    print("\nSummary")
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
