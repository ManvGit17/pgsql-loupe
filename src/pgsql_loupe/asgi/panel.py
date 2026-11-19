"""The panel: a page and two static files built from panel-src/ and shipped in the package.

Also the optional toggle button injected into the app's own HTML pages.
"""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable, MutableMapping
from importlib.resources import files
from typing import Any

Message = MutableMapping[str, Any]
Send = Callable[[Message], Awaitable[None]]

STATIC = {"panel.js": b"text/javascript; charset=utf-8", "panel.css": b"text/css; charset=utf-8"}

# Same-origin only: the panel works offline, and nothing injected into it can run.
CSP = (
    b"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    b"img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
SECURITY_HEADERS = [
    (b"content-security-policy", CSP),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-cache"),
]

_cache: dict[str, bytes] = {}


def _asset(name: str) -> bytes | None:
    if name not in _cache:
        path = files("pgsql_loupe").joinpath("panel", name)
        if not path.is_file():
            return None
        _cache[name] = path.read_bytes()
    return _cache[name]


def page(prefix: str) -> bytes:
    p = html.escape(prefix, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pgsql-loupe</title>
<link rel="stylesheet" href="{p}/static/panel.css">
</head>
<body>
<div id="root" data-prefix="{p}"></div>
<script type="module" src="{p}/static/panel.js"></script>
</body>
</html>
""".encode()


async def _send(send: Send, status: int, content_type: bytes, body: bytes) -> None:
    headers = [(b"content-type", content_type), (b"content-length", str(len(body)).encode())]
    await send(
        {"type": "http.response.start", "status": status, "headers": headers + SECURITY_HEADERS}
    )
    await send({"type": "http.response.body", "body": body})


async def serve(send: Send, prefix: str, rest: list[str]) -> bool:
    """Serve the panel page or one of its files. False if `rest` is not a panel path."""
    if rest == [""]:
        if _asset("panel.js") is None:
            message = b"The panel is not built. Run `npm run build` in panel-src/."
            await _send(send, 503, b"text/plain; charset=utf-8", message)
        else:
            await _send(send, 200, b"text/html; charset=utf-8", page(prefix))
        return True
    if len(rest) == 2 and rest[0] == "static" and rest[1] in STATIC:
        body = _asset(rest[1])
        if body is None:
            return False
        await _send(send, 200, STATIC[rest[1]], body)
        return True
    return False


def toggle_button(prefix: str, lens_id: str, statements: int) -> bytes:
    href = html.escape(f"{prefix}/#{lens_id}", quote=True)
    noun = "statement" if statements == 1 else "statements"
    style = (
        "position:fixed;right:12px;bottom:12px;z-index:2147483647;padding:6px 10px;"
        "border-radius:8px;background:#2f5fd0;color:#fff;font:600 12px system-ui,sans-serif;"
        "text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.25)"
    )
    return (
        f'<a href="{href}" target="_blank" rel="noopener" style="{style}" '
        f'data-pgsql-loupe="toggle">SQL: {statements} {noun}</a>'
    ).encode()


def inject(body: bytes, button: bytes) -> bytes:
    """Insert `button` before the last </body>, or append it if there is none."""
    index = body.lower().rfind(b"</body>")
    return body + button if index == -1 else body[:index] + button + body[index:]
