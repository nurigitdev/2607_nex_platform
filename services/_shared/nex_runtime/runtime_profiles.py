from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from typing import Any

from .topology import RUNTIME_PROFILES, RuntimeModes


PROFILE_MODE_ENV = {
    "persistence": "NEX_PERSISTENCE_MODE",
    "provider": "NEX_MO_PROVIDER_MODE",
    "trust": "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE",
    "ag_projection": "NEX_AG_OPERATIONS_SOURCE_MODE",
}
DATABASE_ENV_NAMES = (
    "NEX_OA_DATABASE_URL",
    "NEX_AG_DATABASE_URL",
    "NEX_AE_DATABASE_URL",
    "NEX_CX_DATABASE_URL",
    "NEX_MO_DATABASE_URL",
)
TEST_DATABASE_ENV_NAMES = tuple(
    name.replace("_DATABASE_URL", "_TEST_DATABASE_URL")
    for name in DATABASE_ENV_NAMES
)
SIGNED_TRUST_ENV_NAMES = (
    "NEX_OA_BASE_URL",
    "NEX_OA_INTROSPECTION_SERVICE_TOKEN",
    "NEX_AE_TO_OA_SERVICE_TOKEN",
    "NEX_AE_TO_CX_SERVICE_TOKEN",
    "NEX_CX_TO_MO_SERVICE_TOKEN",
    "NEX_AG_TO_OA_SERVICE_TOKEN",
    "NEX_AG_TO_AE_SERVICE_TOKEN",
    "NEX_AG_TO_CX_SERVICE_TOKEN",
    "NEX_AG_TO_MO_SERVICE_TOKEN",
)
LIVE_PROVIDER_ENV_NAMES = (
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_API_KEY",
)
PLACEHOLDER_MARKERS = ("<password>", "<secret>", "changeme", "change-me")


class RuntimeProfileError(ValueError):
    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class RuntimeProfileResolution:
    profile: str
    modes: RuntimeModes
    required_environment_names: tuple[str, ...]
    protected: bool


PROFILE_MODES = {
    "local_mock": RuntimeModes("memory", "mock", "test_mock", "memory"),
    "test": RuntimeModes("postgres", "mock", "signed", "api"),
    "local_live": RuntimeModes("postgres", "live", "signed", "api"),
    "staging_live": RuntimeModes("postgres", "live", "signed", "api"),
    "production": RuntimeModes("postgres", "live", "signed", "api"),
}


def resolve_runtime_profile(
    profile: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> RuntimeProfileResolution:
    env = os.environ if environ is None else environ
    selected = (profile or env.get("NEX_PROFILE") or "local_mock").strip()
    if selected not in RUNTIME_PROFILES:
        raise RuntimeProfileError((f"unsupported runtime profile: {selected}",))

    modes = PROFILE_MODES[selected]
    required = _required_environment_names(selected)
    errors = _mode_conflicts(env, modes)
    errors.extend(
        f"required environment is missing or placeholder: {name}"
        for name in required
        if _missing_or_placeholder(env.get(name))
    )
    if selected != "local_mock" and modes.ag_projection != "api":
        errors.append("protected profiles require service API projections")
    if errors:
        raise RuntimeProfileError(tuple(errors))
    return RuntimeProfileResolution(
        profile=selected,
        modes=modes,
        required_environment_names=required,
        protected=selected != "local_mock",
    )


def runtime_profile_environment_overlay(profile: str) -> dict[str, str]:
    try:
        modes = PROFILE_MODES[profile]
    except KeyError as exc:
        raise RuntimeProfileError((f"unsupported runtime profile: {profile}",)) from exc
    return {
        "NEX_PROFILE": profile,
        PROFILE_MODE_ENV["persistence"]: modes.persistence,
        PROFILE_MODE_ENV["provider"]: modes.provider,
        PROFILE_MODE_ENV["trust"]: (
            "TEST_MOCK" if modes.trust == "test_mock" else "SIGNED_ONLY"
        ),
        PROFILE_MODE_ENV["ag_projection"]: modes.ag_projection,
    }


def runtime_profile_public_projection(
    resolution: RuntimeProfileResolution,
) -> dict[str, Any]:
    return {
        "schema_version": "platform_runtime_profile_resolution.v1",
        "profile": resolution.profile,
        "protected": resolution.protected,
        "modes": {
            "persistence": resolution.modes.persistence,
            "provider": resolution.modes.provider,
            "trust": resolution.modes.trust,
            "ag_projection": resolution.modes.ag_projection,
        },
        "required_environment_names": list(resolution.required_environment_names),
        "required_environment_count": len(resolution.required_environment_names),
    }


def _required_environment_names(profile: str) -> tuple[str, ...]:
    if profile == "local_mock":
        return ()
    database_names = TEST_DATABASE_ENV_NAMES if profile == "test" else DATABASE_ENV_NAMES
    provider_names = LIVE_PROVIDER_ENV_NAMES if PROFILE_MODES[profile].provider == "live" else ()
    return (*database_names, *SIGNED_TRUST_ENV_NAMES, *provider_names)


def _mode_conflicts(env: Mapping[str, str], modes: RuntimeModes) -> list[str]:
    expected = {
        PROFILE_MODE_ENV["persistence"]: modes.persistence,
        PROFILE_MODE_ENV["provider"]: modes.provider,
        PROFILE_MODE_ENV["trust"]: (
            "TEST_MOCK" if modes.trust == "test_mock" else "SIGNED_ONLY"
        ),
        PROFILE_MODE_ENV["ag_projection"]: modes.ag_projection,
    }
    errors = []
    for name, value in expected.items():
        configured = env.get(name)
        if configured and configured.strip().upper() != value.upper():
            errors.append(f"runtime profile conflicts with {name}")
    return errors


def _missing_or_placeholder(value: str | None) -> bool:
    if value is None or not value.strip():
        return True
    normalized = value.strip().lower()
    return any(marker in normalized for marker in PLACEHOLDER_MARKERS)
