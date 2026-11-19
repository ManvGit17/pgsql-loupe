"""Plan capture settings. Kept apart from capture.py so that configuring the middleware
never imports psycopg: SQLAlchemy and asyncpg users may not have it installed."""

from __future__ import annotations

from dataclasses import dataclass, field

from pgsql_loupe.explain.flags import FlagThresholds


@dataclass(frozen=True)
class ExplainOptions:
    dsn: str
    """Connection used for replays. Never the application's own connection."""
    analyze_reads: bool = True
    """Run reads under EXPLAIN ANALYZE (read-only transaction). False: plain EXPLAIN only."""
    analyze_writes: bool = False
    """Run INSERT/UPDATE/DELETE under EXPLAIN ANALYZE (in a rolled-back transaction)."""
    timeout_ms: int = 5_000
    lock_timeout_ms: int = 1_000
    max_plans: int = 25
    """At most this many replays per request in ?lens=plan mode."""
    thresholds: FlagThresholds = field(default_factory=FlagThresholds)
