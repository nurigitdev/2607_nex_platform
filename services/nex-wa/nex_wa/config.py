from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from .job_recovery import (
    DEFAULT_STALE_JOB_SECONDS,
    WaJobRecoveryError,
    normalize_stale_job_seconds,
)

SERVICE_ID = "nex-wa"
DATABASE_ENV = "NEX_WA_DATABASE_URL"
SUPPORTED_PROFILES = frozenset(
    {"local_mock", "test", "local_live", "staging_live", "production"}
)
_IDENTITY_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$")


class WaConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class WaSettings:
    service_id: str
    profile: str
    version: str
    build_sha: str
    stale_job_seconds: int = DEFAULT_STALE_JOB_SECONDS
    database_env: str = DATABASE_ENV

    def public_projection(self) -> dict[str, str | int]:
        return {
            "service_id": self.service_id,
            "profile": self.profile,
            "version": self.version,
            "build_sha": self.build_sha,
            "stale_job_seconds": self.stale_job_seconds,
            "database_env": self.database_env,
        }


def load_wa_settings(environ: Mapping[str, str] | None = None) -> WaSettings:
    env = os.environ if environ is None else environ
    service_id = _value(env.get("NEX_WA_SERVICE_ID", SERVICE_ID), "service id")
    if service_id != SERVICE_ID:
        raise WaConfigurationError("NEX_WA_SERVICE_ID must be nex-wa")

    profile = _value(env.get("NEX_PROFILE", "local_mock"), "runtime profile")
    if profile not in SUPPORTED_PROFILES:
        raise WaConfigurationError(f"unsupported WA runtime profile: {profile}")

    version = _identity_value(env.get("NEX_VERSION", "2.1.0-p9-s01"), "service version")
    build_sha = _identity_value(env.get("NEX_BUILD_SHA", "local"), "build sha")
    stale_job_seconds = _bounded_int(
        env.get("NEX_WA_STALE_JOB_SECONDS", str(DEFAULT_STALE_JOB_SECONDS)),
        "NEX_WA_STALE_JOB_SECONDS",
    )
    return WaSettings(service_id, profile, version, build_sha, stale_job_seconds)


def _value(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WaConfigurationError(f"WA {field} must be a non-empty string")
    if value != value.strip():
        raise WaConfigurationError(f"WA {field} must not contain outer whitespace")
    return value


def _identity_value(value: object, field: str) -> str:
    normalized = _value(value, field)
    if _IDENTITY_VALUE.fullmatch(normalized) is None:
        raise WaConfigurationError(f"WA {field} has an invalid format")
    return normalized


def _bounded_int(value: object, field: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise WaConfigurationError(f"{field} must be an integer") from exc
    try:
        return normalize_stale_job_seconds(parsed)
    except WaJobRecoveryError as exc:
        raise WaConfigurationError(str(exc)) from exc
