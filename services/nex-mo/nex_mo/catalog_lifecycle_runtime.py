from __future__ import annotations

from typing import Any

from nex_mo.catalog_lifecycle_repository import (
    InMemoryCatalogLifecycleRepository,
    SqlAlchemyCatalogLifecycleRepository,
)
from nex_mo.catalog_lifecycle_service import CatalogLifecycleService


class CatalogLifecycleRuntimeError(RuntimeError):
    pass


def build_catalog_lifecycle_service(runtime: Any) -> CatalogLifecycleService:
    mode = getattr(runtime, "mode", None)
    if mode == "memory":
        repository = InMemoryCatalogLifecycleRepository()
    elif mode == "postgres":
        session_factory = getattr(runtime, "api_session_factory", None)
        if session_factory is None:
            raise CatalogLifecycleRuntimeError(
                "postgres catalog lifecycle requires an API session factory"
            )
        repository = SqlAlchemyCatalogLifecycleRepository(session_factory)
    else:
        raise CatalogLifecycleRuntimeError(
            "catalog lifecycle requires memory or postgres persistence mode"
        )
    service = CatalogLifecycleService(repository)
    service.ensure_bootstrap()
    return service
