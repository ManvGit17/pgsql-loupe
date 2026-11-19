"""Run the CI checks locally: lint, pytest for every Python x PostgreSQL pair, the panel
checks (needs Node) and the browser tests (needs `playwright install chromium`).

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


def run_in(cwd: Path, cmd: list[str]) -> bool:
    print(f"$ (in {cwd.name}) " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd).returncode == 0


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
    # Once, not per combination: the panel's own checks and the browser tests.
    panel = ROOT / "panel-src"
    npm, npx = ("npm.cmd", "npx.cmd") if os.name == "nt" else ("npm", "npx")
    results["panel npm ci"] = run_in(panel, [npm, "ci", "--no-audit", "--no-fund"])
    results["panel typecheck"] = run_in(panel, [npm, "run", "typecheck"])
    results["panel unit tests"] = run_in(panel, [npm, "test"])
    results["panel build is committed"] = run_in(panel, [npx, "vite", "build"]) and run(
        ["git", "diff", "--exit-code", "--", "src/pgsql_loupe/panel"]
    )
    env = {**os.environ, "TEST_PG_DSN": f"postgresql://test:test@127.0.0.1:{POSTGRES['18']}/test"}
    env.pop("VIRTUAL_ENV", None)
    results["pytest -m e2e (py3.13, pg18)"] = run(["uv", "run", "pytest", "-q", "-m", "e2e"], env)
    print("\nSummary")
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
