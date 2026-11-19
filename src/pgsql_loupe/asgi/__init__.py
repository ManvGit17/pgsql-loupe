"""ASGI integration: middleware, JSON API and the two-line FastAPI setup."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pgsql_loupe.asgi.config import LoupeConfig, ProductionGuardError, localhost_only
from pgsql_loupe.asgi.middleware import LoupeMiddleware

__all__ = ["LoupeConfig", "LoupeMiddleware", "ProductionGuardError", "install", "localhost_only"]


def install(
    app: Any, config: LoupeConfig | None = None, *, environ: Mapping[str, str] | None = None
) -> bool:
    """Add LoupeMiddleware to a Starlette or FastAPI app. Returns True if it was added.

    Checks the production guard now, so a misconfigured app fails at start-up rather
    than on its first request. When disabled, the app is left untouched.
    """
    cfg = config or LoupeConfig()
    if not cfg.is_enabled(environ):
        return False
    cfg.check_not_production(environ)
    app.add_middleware(LoupeMiddleware, config=cfg, environ=environ)
    return True
