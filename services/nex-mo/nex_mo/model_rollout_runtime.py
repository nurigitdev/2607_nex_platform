from __future__ import annotations

from typing import Any

from nex_mo.model_rollout_repository import (
    InMemoryModelRolloutRepository,
    SqlAlchemyModelRolloutRepository,
)
from nex_mo.model_rollout_service import ModelRolloutService


class ModelRolloutRuntimeError(RuntimeError):
    pass


def build_model_rollout_service(runtime: Any) -> ModelRolloutService:
    mode = getattr(runtime, "mode", None)
    if mode == "memory":
        repository = InMemoryModelRolloutRepository()
    elif mode == "postgres":
        session_factory = getattr(runtime, "api_session_factory", None)
        if session_factory is None:
            raise ModelRolloutRuntimeError(
                "postgres model rollout requires an API session factory"
            )
        repository = SqlAlchemyModelRolloutRepository(session_factory)
    else:
        raise ModelRolloutRuntimeError(
            "model rollout requires memory or postgres persistence mode"
        )
    return ModelRolloutService(repository)
