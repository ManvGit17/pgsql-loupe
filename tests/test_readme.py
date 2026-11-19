"""The README is also the PyPI page, where relative links and images resolve against pypi.org
and break. Every link and image must be absolute."""

from __future__ import annotations

import re
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_links_are_absolute() -> None:
    targets = re.findall(r"\]\(([^)\s]+)\)", README.read_text(encoding="utf-8"))
    assert targets, "no links found: the pattern is wrong"
    relative = [t for t in targets if not t.startswith(("https://", "http://", "#"))]
    assert relative == []
