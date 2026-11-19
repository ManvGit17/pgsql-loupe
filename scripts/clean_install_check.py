"""Follow the README on a clean machine: a fresh python:3.13-slim container.

    docker compose up -d --wait
    uv run python scripts/clean_install_check.py

Builds the wheel, takes the `pip install` line and `app.py` from the README's "Try it"
section (with the local wheel in place of the PyPI package), installs and starts the app in
the container, and checks that a traced request and the panel work. Requests are made from
inside the container because the panel only answers this machine (localhost).
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE = "python:3.13-slim"
CONTAINER = "pgsql-loupe-clean-install"
DSN = "postgresql://test:test@host.docker.internal:54318/test"


def readme_steps() -> tuple[str, str]:
    """(pip arguments, app.py source) from the README's "Try it" section."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    section = text.split("## Try it", 1)[1].split("\n## ", 1)[0]
    pip_line = re.search(r"```bash\n(pip install [^\n]+)\n```", section)
    app = re.search(r"```python\n(.*?)```", section, re.DOTALL)
    if not pip_line or not app:
        raise SystemExit("README 'Try it' section must have a pip line and a python block")
    return pip_line.group(1), app.group(1)


def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", **kwargs)  # type: ignore[call-overload,no-any-return]


PROBE = r"""
import json, sys, urllib.request
base = "http://127.0.0.1:8000"
out = {}
with urllib.request.urlopen(base + "/tables?lens=plan") as r:
    out["status"] = r.status
    out["lens_id"] = r.headers.get("x-lens-id")
    out["body"] = json.loads(r.read())
with urllib.request.urlopen(base + "/__lens/") as r:
    out["panel_html"] = r.read().decode()
with urllib.request.urlopen(base + "/__lens/static/panel.js") as r:
    out["panel_js_bytes"] = len(r.read())
import time
for _ in range(50):  # plans are captured after the response has been sent
    with urllib.request.urlopen(base + "/__lens/api/requests/" + out["lens_id"]) as r:
        out["trace"] = json.loads(r.read())
    if out["trace"]["plan_note"]:
        break
    time.sleep(0.1)
print(json.dumps(out))
"""


def main() -> int:
    pip_line, app_source = readme_steps()
    dist = ROOT / "dist"
    for old in dist.glob("pgsql_loupe-*"):
        old.unlink()
    if run(["uv", "build", "--wheel", "--out-dir", str(dist)], cwd=ROOT).returncode != 0:
        raise SystemExit("uv build failed")
    wheel = next(dist.glob("pgsql_loupe-*.whl")).name
    args = shlex.split(pip_line)[2:]
    args = [f"/dist/{wheel}[psycopg]" if a == "pgsql-loupe[psycopg]" else a for a in args]
    if f"/dist/{wheel}[psycopg]" not in args:
        raise SystemExit("README pip line must install pgsql-loupe[psycopg]")

    with tempfile.TemporaryDirectory() as work:
        Path(work, "app.py").write_text(app_source, encoding="utf-8")
        run(["docker", "rm", "-f", CONTAINER])
        script = (
            f"pip install --quiet --no-cache-dir {shlex.join(args)} && cd /app && "
            "exec uvicorn app:app --host 127.0.0.1 --port 8000"
        )
        started = run([
            "docker", "run", "-d", "--name", CONTAINER,
            "--add-host=host.docker.internal:host-gateway",
            "-v", f"{dist}:/dist:ro", "-v", f"{work}:/app:ro",
            "-e", f"DATABASE_URL={DSN}", "-e", "PGSQL_LOUPE_ENABLED=1",
            IMAGE, "sh", "-c", script,
        ])  # fmt: skip
        if started.returncode != 0:
            raise SystemExit(started.stderr)
        try:
            result = None
            for _ in range(180):
                probe = run(["docker", "exec", CONTAINER, "python", "-c", PROBE])
                if probe.returncode == 0:
                    result = json.loads(probe.stdout)
                    break
                state = run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER])
                if state.stdout.strip() != "true":
                    break
                time.sleep(1)
            logs = run(["docker", "logs", CONTAINER])
        finally:
            run(["docker", "rm", "-f", CONTAINER])

    print(f"README pip line: pip install {shlex.join(args)}")
    if result is None:
        print("FAIL  the app did not start\n" + logs.stdout[-3000:] + logs.stderr[-3000:])
        return 1
    statements = result["trace"]["statements"]
    checks = {
        "traced request returns 200 with X-Lens-Id": result["status"] == 200
        and bool(result["lens_id"]),
        "the app's own answer is intact": isinstance(result["body"], list),
        "panel page is served": 'data-prefix="/__lens"' in result["panel_html"],
        "panel script is served": result["panel_js_bytes"] > 100_000,
        "trace has the statement": [s["sql"] for s in statements]
        == ["SELECT tablename FROM pg_tables ORDER BY 1 LIMIT %s"],
        "statement has a call site in app.py": (statements[0]["call_site"] or {})
        .get("file", "")
        .endswith("app.py"),
        "plan was captured (EXPLAIN ANALYZE)": (statements[0]["plan"] or {}).get("mode")
        == "analyze",
    }
    print(f"      plan note: {result['trace']['plan_note']}; plan: {statements[0]['plan']}"[:300])
    warnings = [line for line in (logs.stdout + logs.stderr).splitlines() if "Warning" in line]
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"{'PASS' if not warnings else 'FAIL'}  no warnings in the app's output")
    for line in warnings:
        print("      " + line)
    return 0 if all(checks.values()) and not warnings else 1


if __name__ == "__main__":
    sys.exit(main())
