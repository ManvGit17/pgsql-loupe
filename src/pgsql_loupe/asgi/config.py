"""Configuration, the production guard and the default authorisation rule."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

Scope = MutableMapping[str, Any]

ENABLED_VAR = "PGSQL_LOUPE_ENABLED"
ALLOW_PRODUCTION_VAR = "PGSQL_LOUPE_ALLOW_PRODUCTION"
ENVIRONMENT_VARS = ("PGSQL_LOUPE_ENV", "APP_ENV", "ENVIRONMENT", "ENV")
PRODUCTION_VALUES = frozenset({"prod", "production", "live"})
LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
FORWARDED_HEADERS = frozenset({b"forwarded", b"x-forwarded-for", b"x-real-ip"})


class ProductionGuardError(RuntimeError):
    """Raised when pgsql-loupe is enabled in an environment marked as production."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def localhost_only(scope: Scope) -> bool:
    """Allow direct requests from this machine only.

    A request with a forwarding header is refused: behind a reverse proxy running on the
    same machine, every client would otherwise appear to come from 127.0.0.1.
    """
    client = scope.get("client")
    if not client or client[0] not in LOCAL_HOSTS:
        return False
    return not any(name.lower() in FORWARDED_HEADERS for name, _ in scope.get("headers", []))


@dataclass(frozen=True)
class LoupeConfig:
    enabled: bool | None = None
    """None: read PGSQL_LOUPE_ENABLED."""
    history: int = 100
    """How many traced requests to keep in memory."""
    prefix: str = "/__lens"
    authorize: Callable[[Scope], bool] = localhost_only
    """Who may trigger tracing and read the API. Receives the ASGI scope."""
    environment_vars: tuple[str, ...] = ENVIRONMENT_VARS
    allow_production: bool | None = None
    """None: read PGSQL_LOUPE_ALLOW_PRODUCTION."""

    def is_enabled(self, environ: Mapping[str, str] | None = None) -> bool:
        env = os.environ if environ is None else environ
        return self.enabled if self.enabled is not None else _truthy(env.get(ENABLED_VAR))

    def check_not_production(self, environ: Mapping[str, str] | None = None) -> None:
        env = os.environ if environ is None else environ
        allowed = self.allow_production
        if allowed is None:
            allowed = _truthy(env.get(ALLOW_PRODUCTION_VAR))
        if allowed:
            return
        for name in self.environment_vars:
            value = env.get(name, "").strip().lower()
            if value in PRODUCTION_VALUES:
                raise ProductionGuardError(
                    f"pgsql-loupe is enabled but {name}={value!r} marks this as production. "
                    f"It records SQL parameters, so it refuses to run here. "
                    f"Set {ALLOW_PRODUCTION_VAR}=1 only if you are sure."
                )
