"""Turn query parameters into short, redacted text before they are stored."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

SENSITIVE = re.compile(r"pass(word|wd)?|pwd|secret|token|key", re.IGNORECASE)
MAX_LENGTH = 200
REDACTED = "<redacted>"


def show(value: Any, max_length: int = MAX_LENGTH) -> str:
    """repr() of one value, truncated. Large binary values are summarised, not copied."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes>"
    text = repr(value)
    if len(text) > max_length:
        return text[:max_length] + f"... ({len(text)} chars)"
    return text


def redact_params(params: Any) -> list[str] | dict[str, str] | None:
    """Named values whose name looks secret are replaced; everything else is shown truncated.

    Positional values have no name, so they can only be truncated (see ADR 0001).
    """
    if params is None:
        return None
    if isinstance(params, Mapping):
        return {
            str(name): REDACTED if SENSITIVE.search(str(name)) else show(value)
            for name, value in params.items()
        }
    if isinstance(params, Sequence) and not isinstance(params, (str, bytes)):
        return [show(value) for value in params]
    return [show(params)]
