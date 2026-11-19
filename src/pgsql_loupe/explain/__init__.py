"""Plan capture: safety rules, replay under EXPLAIN, plan parsing and flags.

`capture_plans` and `explain_statement` need psycopg and are imported on first use, so that
`import pgsql_loupe.explain` (and the middleware) works without it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pgsql_loupe.explain.flags import FlagThresholds
from pgsql_loupe.explain.options import ExplainOptions
from pgsql_loupe.explain.plan import Flag, PlanNode, PlanResult, TriggerRun
from pgsql_loupe.explain.safety import classify

if TYPE_CHECKING:
    from pgsql_loupe.explain.capture import capture_plans, explain_statement

__all__ = [
    "ExplainOptions",
    "Flag",
    "FlagThresholds",
    "PlanNode",
    "PlanResult",
    "TriggerRun",
    "capture_plans",
    "classify",
    "explain_statement",
]


def __getattr__(name: str) -> Any:
    if name in {"capture_plans", "explain_statement"}:
        from pgsql_loupe.explain import capture

        return getattr(capture, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
