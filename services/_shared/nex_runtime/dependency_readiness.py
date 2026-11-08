from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .semantic_hashes import semantic_sha256_hash_ref

PLATFORM_DEPENDENCY_READINESS_SCHEMA_VERSION = "platform_dependency_readiness.v1"
PLATFORM_DEPENDENCY_READINESS_AGGREGATE_SCHEMA_VERSION = (
    "platform_dependency_readiness_aggregate.v1"
)
DEPENDENCY_TYPES = ("OPENBAO", "OBJECT_STORAGE", "MODEL_PROVIDER")
DEPENDENCY_READINESS_STATUSES = ("READY", "NOT_READY")

_DEPENDENCY_ID = re.compile(r"^[a-z][a-z0-9._:-]{0,127}$")
_OWNER = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


class DependencyReadinessError(ValueError):
    pass


@dataclass(frozen=True)
class DependencyReadinessRequirement:
    dependency_id: str
    dependency_type: str
    owner: str
    required: bool

    def __post_init__(self) -> None:
        _validate_identity(
            dependency_id=self.dependency_id,
            dependency_type=self.dependency_type,
            owner=self.owner,
        )
        _require_bool(self.required, "required")


@dataclass(frozen=True)
class PlatformDependencyReadiness:
    dependency_id: str
    dependency_type: str
    owner: str
    required: bool
    configured: bool
    provisioned: bool
    reachable: bool
    authorized: bool
    ready: bool
    evidence_hash: str
    checked_at: str

    def __post_init__(self) -> None:
        _validate_identity(
            dependency_id=self.dependency_id,
            dependency_type=self.dependency_type,
            owner=self.owner,
        )
        for field_name in (
            "required",
            "configured",
            "provisioned",
            "reachable",
            "authorized",
            "ready",
        ):
            _require_bool(getattr(self, field_name), field_name)
        expected_ready = all(
            (
                self.configured,
                self.provisioned,
                self.reachable,
                self.authorized,
            )
        )
        if self.ready is not expected_ready:
            raise DependencyReadinessError(
                "ready must equal configured, provisioned, reachable, and authorized"
            )
        canonical_checked_at = _canonical_timestamp(self.checked_at)
        if self.checked_at != canonical_checked_at:
            raise DependencyReadinessError("checked_at must be canonical UTC")
        if self.evidence_hash != _readiness_evidence_hash(self):
            raise DependencyReadinessError("dependency readiness evidence hash mismatch")

    def to_projection(self) -> dict[str, Any]:
        return {
            "schema_version": PLATFORM_DEPENDENCY_READINESS_SCHEMA_VERSION,
            "dependency_id": self.dependency_id,
            "dependency_type": self.dependency_type,
            "owner": self.owner,
            "required": self.required,
            "configured": self.configured,
            "provisioned": self.provisioned,
            "reachable": self.reachable,
            "authorized": self.authorized,
            "ready": self.ready,
            "evidence_hash": self.evidence_hash,
            "checked_at": self.checked_at,
        }


def normalize_dependency_readiness(
    requirement: DependencyReadinessRequirement,
    *,
    configured: bool,
    provisioned: bool,
    reachable: bool,
    authorized: bool,
    checked_at: str,
) -> PlatformDependencyReadiness:
    """Normalize owner-produced signals without retaining owner evidence."""

    for field_name, value in (
        ("configured", configured),
        ("provisioned", provisioned),
        ("reachable", reachable),
        ("authorized", authorized),
    ):
        _require_bool(value, field_name)
    canonical_checked_at = _canonical_timestamp(checked_at)
    ready = all((configured, provisioned, reachable, authorized))
    hash_input = {
        "schema_version": PLATFORM_DEPENDENCY_READINESS_SCHEMA_VERSION,
        "dependency_id": requirement.dependency_id,
        "dependency_type": requirement.dependency_type,
        "owner": requirement.owner,
        "required": requirement.required,
        "configured": configured,
        "provisioned": provisioned,
        "reachable": reachable,
        "authorized": authorized,
        "ready": ready,
    }
    return PlatformDependencyReadiness(
        dependency_id=requirement.dependency_id,
        dependency_type=requirement.dependency_type,
        owner=requirement.owner,
        required=requirement.required,
        configured=configured,
        provisioned=provisioned,
        reachable=reachable,
        authorized=authorized,
        ready=ready,
        evidence_hash=semantic_sha256_hash_ref(hash_input),
        checked_at=canonical_checked_at,
    )


def aggregate_dependency_readiness(
    requirements: Sequence[DependencyReadinessRequirement],
    observations: Sequence[PlatformDependencyReadiness],
) -> dict[str, Any]:
    """Aggregate declared dependencies and fail closed on missing requirements."""

    requirement_by_id = _unique_requirements(requirements)
    observation_by_id = _unique_observations(observations)
    undeclared = sorted(set(observation_by_id) - set(requirement_by_id))
    if undeclared:
        raise DependencyReadinessError(
            f"undeclared dependency readiness observation: {undeclared[0]}"
        )
    for dependency_id, observation in observation_by_id.items():
        requirement = requirement_by_id[dependency_id]
        if (
            observation.dependency_type != requirement.dependency_type
            or observation.owner != requirement.owner
            or observation.required is not requirement.required
        ):
            raise DependencyReadinessError(
                f"dependency readiness identity drift: {dependency_id}"
            )

    missing_required = sorted(
        dependency_id
        for dependency_id, requirement in requirement_by_id.items()
        if requirement.required and dependency_id not in observation_by_id
    )
    missing_optional = sorted(
        dependency_id
        for dependency_id, requirement in requirement_by_id.items()
        if not requirement.required and dependency_id not in observation_by_id
    )
    not_ready_required = sorted(
        dependency_id
        for dependency_id, observation in observation_by_id.items()
        if requirement_by_id[dependency_id].required and not observation.ready
    )
    status = (
        "READY"
        if not missing_required and not not_ready_required
        else "NOT_READY"
    )
    projected = [
        observation_by_id[dependency_id].to_projection()
        for dependency_id in sorted(observation_by_id)
    ]
    hash_input = {
        "schema_version": PLATFORM_DEPENDENCY_READINESS_AGGREGATE_SCHEMA_VERSION,
        "requirements": [
            {
                "dependency_id": item.dependency_id,
                "dependency_type": item.dependency_type,
                "owner": item.owner,
                "required": item.required,
            }
            for item in sorted(
                requirement_by_id.values(), key=lambda item: item.dependency_id
            )
        ],
        "observation_hashes": [
            {
                "dependency_id": item["dependency_id"],
                "evidence_hash": item["evidence_hash"],
            }
            for item in projected
        ],
        "missing_required_dependency_ids": missing_required,
        "missing_optional_dependency_ids": missing_optional,
        "not_ready_required_dependency_ids": not_ready_required,
        "readiness_status": status,
    }
    return {
        "schema_version": PLATFORM_DEPENDENCY_READINESS_AGGREGATE_SCHEMA_VERSION,
        "readiness_status": status,
        "dependency_count": len(requirement_by_id),
        "observed_dependency_count": len(observation_by_id),
        "required_dependency_count": sum(
            requirement.required for requirement in requirement_by_id.values()
        ),
        "missing_required_dependency_ids": missing_required,
        "missing_optional_dependency_ids": missing_optional,
        "not_ready_required_dependency_ids": not_ready_required,
        "dependencies": projected,
        "evidence_hash": semantic_sha256_hash_ref(hash_input),
    }


def _unique_requirements(
    requirements: Sequence[DependencyReadinessRequirement],
) -> dict[str, DependencyReadinessRequirement]:
    if not requirements:
        raise DependencyReadinessError("dependency readiness inventory is empty")
    result: dict[str, DependencyReadinessRequirement] = {}
    for requirement in requirements:
        if not isinstance(requirement, DependencyReadinessRequirement):
            raise DependencyReadinessError("dependency readiness requirement is invalid")
        if requirement.dependency_id in result:
            raise DependencyReadinessError(
                f"duplicate dependency readiness requirement: {requirement.dependency_id}"
            )
        result[requirement.dependency_id] = requirement
    return result


def _unique_observations(
    observations: Sequence[PlatformDependencyReadiness],
) -> dict[str, PlatformDependencyReadiness]:
    result: dict[str, PlatformDependencyReadiness] = {}
    for observation in observations:
        if not isinstance(observation, PlatformDependencyReadiness):
            raise DependencyReadinessError("dependency readiness observation is invalid")
        if observation.dependency_id in result:
            raise DependencyReadinessError(
                f"duplicate dependency readiness observation: {observation.dependency_id}"
            )
        result[observation.dependency_id] = observation
    return result


def _readiness_evidence_hash(readiness: PlatformDependencyReadiness) -> str:
    return semantic_sha256_hash_ref(
        {
            "schema_version": PLATFORM_DEPENDENCY_READINESS_SCHEMA_VERSION,
            "dependency_id": readiness.dependency_id,
            "dependency_type": readiness.dependency_type,
            "owner": readiness.owner,
            "required": readiness.required,
            "configured": readiness.configured,
            "provisioned": readiness.provisioned,
            "reachable": readiness.reachable,
            "authorized": readiness.authorized,
            "ready": readiness.ready,
        }
    )


def _validate_identity(
    *, dependency_id: str, dependency_type: str, owner: str
) -> None:
    if (
        not isinstance(dependency_id, str)
        or _DEPENDENCY_ID.fullmatch(dependency_id) is None
    ):
        raise DependencyReadinessError("dependency_id is invalid")
    if dependency_type not in DEPENDENCY_TYPES:
        raise DependencyReadinessError("dependency_type is unsupported")
    if not isinstance(owner, str) or _OWNER.fullmatch(owner) is None:
        raise DependencyReadinessError("dependency owner is invalid")


def _require_bool(value: object, field_name: str) -> None:
    if type(value) is not bool:
        raise DependencyReadinessError(f"{field_name} must be a boolean")


def _canonical_timestamp(value: str) -> str:
    if not isinstance(value, str):
        raise DependencyReadinessError("checked_at must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise DependencyReadinessError(
            "checked_at must be an ISO 8601 timestamp"
        ) from None
    if parsed.tzinfo is None:
        raise DependencyReadinessError("checked_at must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
