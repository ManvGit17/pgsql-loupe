"""JSON shapes served by /__lens/api.

Fields are listed explicitly: `Statement.replay` holds unredacted parameter values and must
never be served.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any

from pgsql_loupe.asgi.store import RequestRecord
from pgsql_loupe.core.trace import Statement
from pgsql_loupe.explain.plan import PlanResult
from pgsql_loupe.explain.safety import classify

_PRIVATE = {"replay", "plan", "call_site"}
_PUBLIC_FIELDS = [f.name for f in fields(Statement) if f.name not in _PRIVATE]


def _ms(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def plan_to_dict(plan: PlanResult) -> dict[str, Any]:
    return asdict(plan)


def statement_to_dict(index: int, statement: Statement) -> dict[str, Any]:
    data: dict[str, Any] = {name: getattr(statement, name) for name in _PUBLIC_FIELDS}
    data["index"] = index
    data["start_ms"] = _ms(statement.start_ms)
    data["duration_ms"] = _ms(statement.duration_ms)
    data["call_site"] = asdict(statement.call_site) if statement.call_site else None
    data["explain"] = "none" if statement.kind == "copy" else classify(statement.sql)
    data["plan"] = plan_to_dict(statement.plan) if statement.plan else None
    return data


def summary(record: RequestRecord) -> dict[str, Any]:
    statements = record.trace.statements
    return {
        "id": record.id,
        "method": record.method,
        "path": record.path,
        "mode": record.mode,
        "status": record.status,
        "started_at": record.started_at.isoformat(),
        "duration_ms": _ms(record.duration_ms),
        "statement_count": len(statements),
        "db_ms": _ms(record.trace.total_ms),
        "error_count": sum(1 for s in statements if s.error),
        "exception": record.exception,
        "plan_note": record.plan_note,
    }


def detail(record: RequestRecord) -> dict[str, Any]:
    return summary(record) | {
        "statements": [statement_to_dict(i, s) for i, s in enumerate(record.trace.statements)]
    }
