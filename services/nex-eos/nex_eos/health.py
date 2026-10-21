from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .config import EosSettings


def build_configuration_readiness_check(
    settings: EosSettings,
) -> Callable[[], Mapping[str, Any]]:
    projection = settings.public_projection()

    def check() -> Mapping[str, Any]:
        return {
            "name": "eos_service_configuration",
            "ok": True,
            "service_id": projection["service_id"],
            "profile": projection["profile"],
            "version": projection["version"],
            "build_sha": projection["build_sha"],
        }

    return check
