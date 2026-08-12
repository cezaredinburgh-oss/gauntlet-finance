"""Request-scoped tenant id for cache keys, uploads, and locks."""

from __future__ import annotations

from contextvars import ContextVar, Token

_tenant_id: ContextVar[str | None] = ContextVar("gauntlet_tenant_id", default=None)


def get_tenant_id() -> str | None:
    return _tenant_id.get()


def set_tenant_id(tenant_id: str | None) -> Token[str | None]:
    return _tenant_id.set(tenant_id)


def reset_tenant_id(token: Token[str | None]) -> None:
    _tenant_id.reset(token)
