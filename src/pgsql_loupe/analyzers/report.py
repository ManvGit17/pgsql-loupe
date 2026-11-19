"""Warnings and a summary for one request's statements."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from pgsql_loupe.analyzers.fingerprint import fingerprint
from pgsql_loupe.core.trace import Statement

# executemany is already the batched form, so it never counts towards an N+1.
_SINGLE_KINDS = frozenset({"execute", "stream", "declare"})


@dataclass(frozen=True)
class AnalyzerOptions:
    nplus1_threshold: int = 3
    """Same fingerprint, run at least this many times with different values: N+1."""
    slow_ms: float = 100.0
    """Statements at least this slow are listed as slow."""


@dataclass
class RepeatedShape:
    """An N+1 suspect: one statement shape run many times with different values."""

    fingerprint: str
    count: int
    distinct_values: int
    total_ms: float
    statements: list[int]
    call_sites: list[str]


@dataclass
class Duplicate:
    """The same SQL with the same values, run more than once."""

    sql: str
    count: int
    total_ms: float
    statements: list[int]


@dataclass
class RequestSummary:
    statement_count: int
    db_ms: float
    request_ms: float | None
    db_share: float | None
    """Fraction of the request's time spent waiting on statements (0..1)."""
    error_count: int
    slow_statements: list[int]


@dataclass
class Analysis:
    summary: RequestSummary
    nplus1: list[RepeatedShape] = field(default_factory=list)
    duplicates: list[Duplicate] = field(default_factory=list)


def _values_key(statement: Statement) -> str:
    """Raw values when known: redacted text would make two different secrets look equal."""
    if statement.replay is not None:
        return repr(statement.replay.params)
    return repr(statement.params)


def _site(statement: Statement) -> str | None:
    site = statement.call_site
    return f"{site.file}:{site.line}" if site else None


def analyze(
    statements: Sequence[Statement],
    request_ms: float | None = None,
    options: AnalyzerOptions | None = None,
) -> Analysis:
    opts = options or AnalyzerOptions()
    db_ms = sum(s.duration_ms or 0.0 for s in statements)
    summary = RequestSummary(
        statement_count=len(statements),
        db_ms=db_ms,
        request_ms=request_ms,
        db_share=min(db_ms / request_ms, 1.0) if request_ms else None,
        error_count=sum(1 for s in statements if s.error),
        slow_statements=[
            i for i, s in enumerate(statements) if (s.duration_ms or 0.0) >= opts.slow_ms
        ],
    )

    shapes: dict[str, list[int]] = defaultdict(list)
    exact: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, statement in enumerate(statements):
        if statement.kind in _SINGLE_KINDS:
            shapes[fingerprint(statement.sql)].append(index)
        exact[(statement.sql, _values_key(statement))].append(index)

    def total(indexes: list[int]) -> float:
        return sum(statements[i].duration_ms or 0.0 for i in indexes)

    nplus1: list[RepeatedShape] = []
    for shape, indexes in shapes.items():
        distinct = len({_values_key(statements[i]) for i in indexes})
        if len(indexes) >= opts.nplus1_threshold and distinct >= 2:
            sites = [site for i in indexes if (site := _site(statements[i]))]
            nplus1.append(
                RepeatedShape(
                    fingerprint=shape,
                    count=len(indexes),
                    distinct_values=distinct,
                    total_ms=total(indexes),
                    statements=indexes,
                    call_sites=list(dict.fromkeys(sites)),
                )
            )
    duplicates = [
        Duplicate(sql=sql, count=len(indexes), total_ms=total(indexes), statements=indexes)
        for (sql, _), indexes in exact.items()
        if len(indexes) >= 2
    ]
    nplus1.sort(key=lambda r: (-r.count, -r.total_ms))
    duplicates.sort(key=lambda d: (-d.count, -d.total_ms))
    return Analysis(summary=summary, nplus1=nplus1, duplicates=duplicates)
