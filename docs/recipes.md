# Recipes

## A plain ASGI app

```python
from pgsql_loupe.asgi import LoupeConfig, LoupeMiddleware

app = LoupeMiddleware(app, LoupeConfig())
```

## Allow a teammate's machine

```python
from pgsql_loupe.asgi import LoupeConfig, install


def office_only(scope) -> bool:
    client = scope.get("client")
    return bool(client) and client[0].startswith("10.20.")


install(app, LoupeConfig(authorize=office_only))
```

`authorize` receives the ASGI scope and decides both who may trigger tracing and who may read
the panel and API.

## Behind a reverse proxy on the same machine

The default rule refuses forwarded requests on purpose. Either open the app's own port
directly (for example `http://127.0.0.1:8000`), or write an `authorize` that checks your
proxy's own header for the original client.

## Count queries in a test

```python
def test_order_page(loupe, client):
    with loupe.record() as r:
        client.get("/orders/42")
    r.assert_max_queries(3)
```

See [In tests](testing.md).

## Trace a script or a background job

```python
import pgsql_loupe

with pgsql_loupe.trace("nightly import") as t:
    run_import()

slowest = max(t.statements, key=lambda s: s.duration_ms or 0)
print(f"{slowest.duration_ms:.1f} ms: {slowest.sql} at {slowest.call_site}")
```

`trace()` works with `with` and `async with`; asyncio tasks started inside it record into it.
Plain threads do not inherit it (FastAPI's thread pool for `def` endpoints does).

## A different panel URL

```python
install(app, LoupeConfig(prefix="/_debug/sql"))
```
