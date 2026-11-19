"""Pure ASGI middleware: traces opted-in requests and serves the panel and /__lens/api.

    app.add_middleware(LoupeMiddleware)        # Starlette / FastAPI
    app = LoupeMiddleware(app)                 # any other ASGI app

See docs/adr/0002-asgi-middleware-and-guard.md.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from typing import Any
from urllib.parse import parse_qs

from pgsql_loupe.asgi import panel
from pgsql_loupe.asgi.config import LoupeConfig, Scope
from pgsql_loupe.asgi.serialize import detail, plan_to_dict, summary
from pgsql_loupe.asgi.store import RequestRecord, RequestStore
from pgsql_loupe.core.trace import Trace, trace

Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

MODES = {"1": "trace", "true": "trace", "trace": "trace", "plan": "plan"}


def requested_mode(scope: Scope) -> str | None:
    """'trace' or 'plan' if the request asked to be traced, else None."""
    for name, value in scope.get("headers", []):
        if name.lower() == b"x-lens":
            return MODES.get(value.decode("latin-1").strip().lower())
    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    values = query.get("lens")
    return MODES.get(values[-1].strip().lower()) if values else None


def server_timing(t: Trace) -> str:
    count = len(t.statements)
    noun = "statement" if count == 1 else "statements"
    return f'db;dur={t.total_ms:.3f};desc="{count} {noun}"'


class LoupeMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        config: LoupeConfig | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.app = app
        self.config = config or LoupeConfig()
        self.enabled = self.config.is_enabled(environ)
        if self.enabled:
            self.config.check_not_production(environ)
        self.store = RequestStore(self.config.history)
        self._prefix = self.config.prefix.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        if path == self._prefix or path.startswith(self._prefix + "/"):
            if self.config.authorize(scope):
                await self._serve_api(scope, send)
            else:  # behave as if the routes did not exist
                await self.app(scope, receive, send)
            return
        mode = requested_mode(scope)
        if mode is None or not self.config.authorize(scope):
            await self.app(scope, receive, send)
            return
        await self._traced(scope, receive, send, mode)

    async def _traced(self, scope: Scope, receive: Receive, send: Send, mode: str) -> None:
        started = time.perf_counter_ns()
        with trace(f"{scope['method']} {scope['path']}") as t:
            record = RequestRecord(trace=t, method=scope["method"], path=scope["path"], mode=mode)
            self.store.add(record)

            held: list[Message] = []  # response start + body chunks, when injecting
            chunks: list[bytes] = []

            async def send_with_headers(message: Message) -> None:
                if message["type"] == "http.response.start":
                    record.status = message["status"]
                    headers = list(message.get("headers", []))
                    headers.append((b"x-lens-id", record.id.encode()))
                    headers.append((b"server-timing", server_timing(t).encode()))
                    message = {**message, "headers": headers}
                    if self.config.inject_toggle and _injectable(headers):
                        held.append(message)  # wait for the whole body
                        return
                elif message["type"] == "http.response.body" and held:
                    chunks.append(message.get("body", b""))
                    if message.get("more_body", False):
                        return
                    button = panel.toggle_button(self._prefix, record.id, len(t.statements))
                    body = panel.inject(b"".join(chunks), button)
                    start = held[0]
                    headers = [
                        (k, v) for k, v in start["headers"] if k.lower() != b"content-length"
                    ]
                    headers.append((b"content-length", str(len(body)).encode()))
                    await send({**start, "headers": headers})
                    await send({"type": "http.response.body", "body": body})
                    return
                await send(message)

            try:
                await self.app(scope, receive, send_with_headers)
            except BaseException as exc:
                # An outer error handler (e.g. Starlette's) will send the 500 response, past
                # this middleware, so the headers cannot be added; the stored trace says why.
                record.exception = type(exc).__name__
                if record.status is None:
                    record.status = 500
                raise
            finally:
                record.duration_ms = (time.perf_counter_ns() - started) / 1_000_000
                if mode == "plan":
                    await self._capture_plans(record)

    async def _capture_plans(self, record: RequestRecord) -> None:
        """Runs after the app has returned, so the response has already been sent."""
        options = self.config.explain
        if options is None:
            record.plan_note = "plan capture is not configured (LoupeConfig.explain)"
            return
        capture_plans = _load_capture()
        if capture_plans is None:
            record.plan_note = NO_PSYCOPG
            return
        runs = await asyncio.to_thread(capture_plans, list(record.trace.statements), options)
        record.plan_note = f"{runs} plan(s) captured"

    async def _serve_api(self, scope: Scope, send: Send) -> None:
        rest = scope["path"][len(self._prefix) :].strip("/").split("/")
        if (
            len(rest) == 6
            and rest[:2] == ["api", "requests"]
            and rest[3:] == ["statements", rest[4], "explain"]
        ):
            await self._explain_one(scope, send, rest[2], rest[4])
            return
        if scope["method"] not in {"GET", "HEAD"}:
            await _json(send, 405, {"error": "method not allowed"})
            return
        if await panel.serve(send, self._prefix, rest):
            return
        if rest == ["api", "requests"]:
            listed = [summary(r, self.config.analyzers) for r in self.store.newest_first()]
            await _json(send, 200, {"requests": listed})
            return
        if len(rest) == 3 and rest[:2] == ["api", "requests"]:
            record = self.store.get(rest[2])
            if record is not None:
                await _json(send, 200, detail(record, self.config.analyzers))
                return
        await _json(send, 404, {"error": "not found"})

    async def _explain_one(self, scope: Scope, send: Send, record_id: str, index: str) -> None:
        """POST {prefix}/api/requests/{id}/statements/{n}/explain: replay one statement."""
        if scope["method"] != "POST":
            await _json(send, 405, {"error": "method not allowed"})
            return
        if not any(name.lower() == b"x-lens" for name, _ in scope.get("headers", [])):
            # A cross-site page cannot add this header without a CORS preflight we never allow.
            await _json(send, 403, {"error": "send an X-Lens header with this request"})
            return
        options = self.config.explain
        if options is None:
            await _json(send, 409, {"error": "plan capture is not configured"})
            return
        record = self.store.get(record_id)
        statements = record.trace.statements if record else []
        if not index.isdigit() or int(index) >= len(statements):
            await _json(send, 404, {"error": "not found"})
            return
        capture_plans = _load_capture()
        if capture_plans is None:
            await _json(send, 501, {"error": NO_PSYCOPG})
            return
        statement = statements[int(index)]
        statement.plan = None  # explain again on request
        await asyncio.to_thread(capture_plans, [statement], options)
        assert statement.plan is not None
        await _json(send, 200, plan_to_dict(statement.plan))


NO_PSYCOPG = "plan capture needs psycopg: pip install pgsql-loupe[psycopg]"


def _load_capture() -> Callable[..., int] | None:
    """capture_plans, or None when psycopg is not installed (plans are the only part of the
    middleware that needs it)."""
    try:
        from pgsql_loupe.explain.capture import capture_plans
    except ImportError:
        return None
    return capture_plans


def _injectable(headers: list[tuple[bytes, bytes]]) -> bool:
    """Only uncompressed HTML can have the toggle button added."""
    values = {k.lower(): v.lower() for k, v in headers}
    return b"text/html" in values.get(b"content-type", b"") and b"content-encoding" not in values


async def _json(send: Send, status: int, body: Any) -> None:
    payload = json.dumps(body, default=str).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})
