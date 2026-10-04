from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from .runtime_profiles import PROFILE_MODES


MANAGED_PROFILE_ENV = "NEX_PROFILE"


class AgProjectionPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class AgProjectionPolicy:
    mode: str
    managed_profile: str | None
    expected_mode: str | None
    legacy_database_adapter_allowed: bool

    @property
    def protected(self) -> bool:
        return self.managed_profile not in (None, "local_mock")

    def to_public_projection(self) -> dict[str, object]:
        return {
            "schema_version": "ag_projection_policy.v1",
            "mode": self.mode,
            "managed_profile": self.managed_profile,
            "expected_mode": self.expected_mode,
            "protected": self.protected,
            "legacy_database_adapter_allowed": self.legacy_database_adapter_allowed,
        }


def resolve_ag_projection_policy(
    mode: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> AgProjectionPolicy:
    env = os.environ if environ is None else environ
    profile_value = env.get(MANAGED_PROFILE_ENV)
    if profile_value is None or not profile_value.strip():
        return AgProjectionPolicy(
            mode=mode,
            managed_profile=None,
            expected_mode=None,
            legacy_database_adapter_allowed=mode == "postgres",
        )

    profile = profile_value.strip()
    try:
        expected_mode = PROFILE_MODES[profile].ag_projection
    except KeyError as exc:
        raise AgProjectionPolicyError(
            f"unsupported managed runtime profile: {profile}"
        ) from exc
    if mode != expected_mode:
        raise AgProjectionPolicyError(
            f"managed runtime profile {profile} requires AG projection mode "
            f"{expected_mode}; received {mode}"
        )
    return AgProjectionPolicy(
        mode=mode,
        managed_profile=profile,
        expected_mode=expected_mode,
        legacy_database_adapter_allowed=False,
    )
