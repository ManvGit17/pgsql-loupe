"""JSON shapes served by /__lens/api."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pgsql_loupe.asgi.store import RequestRecord
from pgsql_loupe.core.trace import Statement


def _ms(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def statement_to_dict(index: int, statement: Statement) -> dict[str, Any]:
    data = asdict(statement)
    data["index"] = index
    for key in ("start_ms", "duration_ms"):
        data[key] = _ms(data[key])
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
    }


def detail(record: RequestRecord) -> dict[str, Any]:
    return summary(record) | {
        "statements": [statement_to_dict(i, s) for i, s in enumerate(record.trace.statements)]
    }
