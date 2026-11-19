"""Per-request warnings: N+1 shapes, exact duplicates, slow statements and a summary."""

from pgsql_loupe.analyzers.fingerprint import fingerprint
from pgsql_loupe.analyzers.report import (
    Analysis,
    AnalyzerOptions,
    Duplicate,
    RepeatedShape,
    RequestSummary,
    analyze,
)

__all__ = [
    "Analysis",
    "AnalyzerOptions",
    "Duplicate",
    "RepeatedShape",
    "RequestSummary",
    "analyze",
    "fingerprint",
]
