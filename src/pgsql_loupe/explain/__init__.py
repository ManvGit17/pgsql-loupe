"""Plan capture: safety rules, replay under EXPLAIN, plan parsing and flags."""

from pgsql_loupe.explain.capture import ExplainOptions, capture_plans, explain_statement
from pgsql_loupe.explain.flags import FlagThresholds
from pgsql_loupe.explain.plan import Flag, PlanNode, PlanResult, TriggerRun
from pgsql_loupe.explain.safety import classify

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
