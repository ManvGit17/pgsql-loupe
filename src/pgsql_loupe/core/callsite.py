"""Find the line of user code that caused a statement."""

from __future__ import annotations

import os
import sys
import sysconfig
from dataclasses import dataclass
from types import FrameType


@dataclass(frozen=True)
class CallSite:
    file: str
    line: int
    function: str


def _library_prefixes() -> tuple[str, ...]:
    """Folders whose frames are never "user code": this package, the stdlib, site-packages."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = {here}
    for name in ("stdlib", "platstdlib", "purelib", "platlib"):
        path = sysconfig.get_paths().get(name)
        if path:
            paths.add(path)
    paths.update(p for p in sys.path if p.endswith("site-packages"))
    return tuple(os.path.normcase(os.path.abspath(p)) + os.sep for p in paths)


_PREFIXES = _library_prefixes()


# Whether a file is library code never changes while the process runs; caching it keeps the
# per-statement cost to one dictionary lookup per stack frame (measured in bench/overhead.py).
_IS_LIBRARY: dict[str, bool] = {}


def _is_library(filename: str) -> bool:
    known = _IS_LIBRARY.get(filename)
    if known is None:
        known = filename.startswith("<") or os.path.normcase(os.path.abspath(filename)).startswith(
            _PREFIXES
        )
        _IS_LIBRARY[filename] = known
    return known


def _walk(frame: FrameType | None) -> CallSite | None:
    while frame is not None:
        if not _is_library(frame.f_code.co_filename):
            return CallSite(frame.f_code.co_filename, frame.f_lineno, frame.f_code.co_name)
        frame = frame.f_back
    return None


def find_call_site(start: FrameType | None = None) -> CallSite | None:
    """First frame, walking outwards, whose file is not library code.

    SQLAlchemy's async engines run the driver call in a child greenlet, whose stack ends
    inside SQLAlchemy; the user's code is in the parent greenlet's (suspended) frames.
    """
    site = _walk(start if start is not None else sys._getframe(1))
    if site is not None:
        return site
    greenlet_module = sys.modules.get("greenlet")
    if greenlet_module is None:
        return None
    current = greenlet_module.getcurrent()
    while site is None and current.parent is not None:
        current = current.parent
        site = _walk(current.gr_frame)
    return site
