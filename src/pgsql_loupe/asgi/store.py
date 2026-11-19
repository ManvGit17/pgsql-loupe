"""In-memory ring buffer of traced requests."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pgsql_loupe.core.trace import Trace


@dataclass
class RequestRecord:
    """One traced HTTP request and its statements."""

    trace: Trace
    method: str
    path: str
    mode: str
    """'trace' (statements only) or 'plan' (also captures query plans)."""
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: int | None = None
    duration_ms: float | None = None
    exception: str | None = None
    """Class name of an exception that escaped the app, if any."""

    @property
    def id(self) -> str:
        return self.trace.id


class RequestStore:
    """Keeps the most recent `size` records. Safe to use from several threads."""

    def __init__(self, size: int) -> None:
        if size < 1:
            raise ValueError("history must be at least 1")
        self._size = size
        self._records: OrderedDict[str, RequestRecord] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, record: RequestRecord) -> None:
        with self._lock:
            self._records[record.id] = record
            while len(self._records) > self._size:
                self._records.popitem(last=False)

    def get(self, record_id: str) -> RequestRecord | None:
        with self._lock:
            return self._records.get(record_id)

    def newest_first(self) -> list[RequestRecord]:
        with self._lock:
            return list(reversed(self._records.values()))
