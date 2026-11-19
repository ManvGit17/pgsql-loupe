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


def find_call_site(start: FrameType | None = None) -> CallSite | None:
    """First frame, walking outwards, whose file is not library code."""
    frame: FrameType | None = start if start is not None else sys._getframe(1)
    while frame is not None:
        filename = frame.f_code.co_filename
        if not filename.startswith("<"):
            normalised = os.path.normcase(os.path.abspath(filename))
            if not normalised.startswith(_PREFIXES):
                return CallSite(filename, frame.f_lineno, frame.f_code.co_name)
        frame = frame.f_back
    return None
