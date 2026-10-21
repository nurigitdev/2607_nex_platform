from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from nex_runtime import build_service_token_admission_runtime
from nex_runtime.service_token_admission import ServiceTokenAdmissionRuntime

from .config import EosSettings
from .health import build_configuration_readiness_check


@dataclass(frozen=True)
class EosDependencies:
    service_token_admission: ServiceTokenAdmissionRuntime
    readiness_checks: tuple[Callable[[], Mapping[str, Any]], ...]


def build_eos_dependencies(
    settings: EosSettings,
    *,
    environ: Mapping[str, str],
) -> EosDependencies:
    return EosDependencies(
        service_token_admission=build_service_token_admission_runtime(
            expected_audience=settings.service_id,
            environ=environ,
        ),
        readiness_checks=(build_configuration_readiness_check(settings),),
    )
