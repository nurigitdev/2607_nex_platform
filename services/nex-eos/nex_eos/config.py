from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

SERVICE_ID = "nex-eos"
DATABASE_ENV = "NEX_EOS_DATABASE_URL"
SUPPORTED_PROFILES = frozenset(
    {"local_mock", "test", "local_live", "staging_live", "production"}
)
_IDENTITY_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$")


class EosConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class EosSettings:
    service_id: str
    profile: str
    version: str
    build_sha: str
    database_env: str = DATABASE_ENV

    def public_projection(self) -> dict[str, str]:
        return {
            "service_id": self.service_id,
            "profile": self.profile,
            "version": self.version,
            "build_sha": self.build_sha,
            "database_env": self.database_env,
        }


def load_eos_settings(
    environ: Mapping[str, str] | None = None,
) -> EosSettings:
    env = os.environ if environ is None else environ
    service_id = _value(env.get("NEX_EOS_SERVICE_ID", SERVICE_ID), "service id")
    if service_id != SERVICE_ID:
        raise EosConfigurationError("NEX_EOS_SERVICE_ID must be nex-eos")

    profile = _value(env.get("NEX_PROFILE", "local_mock"), "runtime profile")
    if profile not in SUPPORTED_PROFILES:
        raise EosConfigurationError(f"unsupported EOS runtime profile: {profile}")

    version = _identity_value(
        env.get("NEX_VERSION", "2.1.0-p8-s07"),
        "service version",
    )
    build_sha = _identity_value(env.get("NEX_BUILD_SHA", "local"), "build sha")
    return EosSettings(
        service_id=service_id,
        profile=profile,
        version=version,
        build_sha=build_sha,
    )


def _value(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EosConfigurationError(f"EOS {field} must be a non-empty string")
    if value != value.strip():
        raise EosConfigurationError(f"EOS {field} must not contain outer whitespace")
    return value


def _identity_value(value: object, field: str) -> str:
    normalized = _value(value, field)
    if _IDENTITY_VALUE.fullmatch(normalized) is None:
        raise EosConfigurationError(f"EOS {field} has an invalid format")
    return normalized
