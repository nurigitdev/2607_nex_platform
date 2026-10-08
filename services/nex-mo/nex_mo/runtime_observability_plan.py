from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from nex_mo.provider_catalog import build_model_profile_catalog
from nex_mo.provider_registry import DEFAULT_PROVIDER_ROUTES
from nex_mo.runtime_observability import normalize_dtype

OBSERVABILITY_MODE_ENV = "NEX_MO_RUNTIME_OBSERVABILITY_MODE"
SSH_TARGET_ENV = "NEX_MO_DGX_SSH_TARGET"
CONNECT_TIMEOUT_ENV = "NEX_MO_RUNTIME_CONNECT_TIMEOUT_SECONDS"
COMMAND_TIMEOUT_ENV = "NEX_MO_RUNTIME_COMMAND_TIMEOUT_SECONDS"
SSH_PUBKEY_MODE_ENV = "NEX_MO_DGX_SSH_PUBKEY_MODE"
SSH_PUBKEY_MODES = frozenset({"host-bound", "unbound"})
DEFAULT_OBSERVABILITY_MODE = "mock"
SSH_TARGET_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+$")
CAPABILITY_PORT_ENV = {
    "embedding": "NEX_MO_RUNTIME_EMBEDDING_PORT",
    "reranking": "NEX_MO_RUNTIME_RERANKER_PORT",
    "generation": "NEX_MO_RUNTIME_GENERATION_PORT",
}
DEFAULT_CAPABILITY_PORT = {
    "embedding": 9112,
    "reranking": 9113,
    "generation": 9111,
}


@dataclass(frozen=True)
class ModelRuntimeProbeTarget:
    provider_capability: str
    alias: str
    deployment_id: str
    model_revision: str
    requested_dtype: str
    process_port: int


@dataclass(frozen=True)
class RuntimeObservationPlan:
    mode: str
    configured: bool
    ssh_target: str | None
    ssh_pubkey_mode: str
    collector_protocol: str
    connect_timeout_seconds: int
    command_timeout_seconds: int
    targets: tuple[ModelRuntimeProbeTarget, ...]


def build_runtime_observation_plan(
    environ: Mapping[str, str],
) -> RuntimeObservationPlan:
    mode = environ.get(OBSERVABILITY_MODE_ENV, DEFAULT_OBSERVABILITY_MODE)
    if mode not in {"mock", "live"}:
        raise ValueError("runtime observability mode must be mock or live")

    profiles = {
        profile.provider_capability: profile
        for profile in build_model_profile_catalog(dict(environ))
        if profile.selected
    }
    targets = tuple(
        ModelRuntimeProbeTarget(
            provider_capability=route.provider_capability,
            alias=route.alias,
            deployment_id=route.deployment_id,
            model_revision=profiles[route.provider_capability].model_name,
            requested_dtype=normalize_dtype(
                profiles[route.provider_capability].precision
            ),
            process_port=_capability_port(environ, route.provider_capability),
        )
        for route in DEFAULT_PROVIDER_ROUTES
    )
    ports = [target.process_port for target in targets]
    if len(ports) != len(set(ports)):
        raise ValueError("runtime observability ports must be unique")

    ssh_target = environ.get(SSH_TARGET_ENV) or None
    ssh_pubkey_mode = environ.get(SSH_PUBKEY_MODE_ENV, "host-bound")
    if ssh_pubkey_mode not in SSH_PUBKEY_MODES:
        raise ValueError(
            f"{SSH_PUBKEY_MODE_ENV} must be host-bound or unbound"
        )
    configured = mode == "mock"
    if mode == "live":
        if ssh_target is None or not SSH_TARGET_PATTERN.fullmatch(ssh_target):
            raise ValueError("live runtime observability requires a valid SSH target")
        configured = True

    return RuntimeObservationPlan(
        mode=mode,
        configured=configured,
        ssh_target=ssh_target,
        ssh_pubkey_mode=ssh_pubkey_mode,
        collector_protocol="fixed_python_stdin_v1",
        connect_timeout_seconds=_timeout_seconds(
            environ,
            CONNECT_TIMEOUT_ENV,
            default=5,
            minimum=1,
            maximum=30,
        ),
        command_timeout_seconds=_timeout_seconds(
            environ,
            COMMAND_TIMEOUT_ENV,
            default=15,
            minimum=5,
            maximum=120,
        ),
        targets=targets,
    )


def project_runtime_observation_plan(
    plan: RuntimeObservationPlan,
) -> dict[str, object]:
    return {
        "mode": plan.mode,
        "configured": plan.configured,
        "collector_protocol": plan.collector_protocol,
        "target_count": len(plan.targets),
        "capabilities": [target.provider_capability for target in plan.targets],
        "model_revisions": [target.model_revision for target in plan.targets],
        "requested_dtypes": [target.requested_dtype for target in plan.targets],
    }


def _capability_port(environ: Mapping[str, str], capability: str) -> int:
    key = CAPABILITY_PORT_ENV[capability]
    raw_value = environ.get(key)
    if raw_value is None or raw_value == "":
        return DEFAULT_CAPABILITY_PORT[capability]
    try:
        port = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{key} must be between 1 and 65535")
    return port


def _timeout_seconds(
    environ: Mapping[str, str],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = environ.get(key)
    if raw_value is None or raw_value == "":
        return default
    try:
        timeout = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if not minimum <= timeout <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return timeout
