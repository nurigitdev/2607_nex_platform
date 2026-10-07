from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any

from .production_secret_materialization import ProductionSecretMaterialization


PRODUCTION_SECRET_ROTATION_SCHEMA_VERSION = "production_secret_rotation.v1"
ROTATION_PHASES = ("PREPARE", "ACTIVATE", "VERIFY", "RETIRE")
ROLLBACK_PHASES = ("STOP_CANDIDATE", "RESTORE_PREVIOUS", "VERIFY_PREVIOUS")
OWNER_ORDER = ("nex-oa", "nex-mo", "nex-cx", "nex-ae-api", "nex-ag")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class ProductionSecretRotationError(ValueError):
    pass


@dataclass(frozen=True)
class SecretRotationPlan:
    schema_version: str
    previous_generation: str
    candidate_generation: str
    phases: tuple[str, ...]
    rollback_phases: tuple[str, ...]
    owner_order: tuple[str, ...]
    restart_strategy: str
    plan_digest: str
    previous: ProductionSecretMaterialization = field(repr=False)
    candidate: ProductionSecretMaterialization = field(repr=False)


@dataclass(frozen=True)
class OwnerRotationObservation:
    owner: str
    generation: str
    restart_completed: bool
    readiness_verified: bool
    secret_count: int


@dataclass(frozen=True)
class SecretRotationDecision:
    status: str
    verified_owners: tuple[str, ...]
    pending_owners: tuple[str, ...]
    rollback_owners: tuple[str, ...]
    retire_previous_approved: bool
    candidate_generation_active: bool


def build_secret_rotation_plan(
    previous: ProductionSecretMaterialization,
    candidate: ProductionSecretMaterialization,
) -> SecretRotationPlan:
    previous_targets = _owner_targets(previous)
    candidate_targets = _owner_targets(candidate)
    if previous.status != "MATERIALIZED_FOR_OWNER_PROCESSES":
        raise ProductionSecretRotationError("previous materialization is not active")
    if candidate.status != "MATERIALIZED_FOR_OWNER_PROCESSES":
        raise ProductionSecretRotationError("candidate materialization is not prepared")
    if previous.secret_generation == candidate.secret_generation:
        raise ProductionSecretRotationError("secret rotation generation must change")
    if previous_targets != candidate_targets:
        raise ProductionSecretRotationError("secret rotation owner or target drift")
    if set(previous_targets) != set(OWNER_ORDER):
        raise ProductionSecretRotationError("secret rotation owner coverage drift")
    digest_payload = {
        "previous_generation": previous.secret_generation,
        "candidate_generation": candidate.secret_generation,
        "owners": previous_targets,
        "phases": ROTATION_PHASES,
        "rollback_phases": ROLLBACK_PHASES,
    }
    digest = hashlib.sha256(
        json.dumps(
            digest_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("ascii")
    ).hexdigest()
    return SecretRotationPlan(
        schema_version=PRODUCTION_SECRET_ROTATION_SCHEMA_VERSION,
        previous_generation=previous.secret_generation,
        candidate_generation=candidate.secret_generation,
        phases=ROTATION_PHASES,
        rollback_phases=ROLLBACK_PHASES,
        owner_order=OWNER_ORDER,
        restart_strategy="owner_ordered_rolling_restart",
        plan_digest=f"sha256:{digest}",
        previous=previous,
        candidate=candidate,
    )


def evaluate_secret_rotation(
    plan: SecretRotationPlan,
    observations: Sequence[OwnerRotationObservation],
) -> SecretRotationDecision:
    _validate_plan(plan)
    expected_counts = {
        item.owner: len(item.secrets) for item in plan.candidate.owner_environments
    }
    observed: dict[str, OwnerRotationObservation] = {}
    invalid = False
    for item in observations:
        if item.owner in observed or item.owner not in expected_counts:
            invalid = True
            continue
        observed[item.owner] = item
        if (
            item.generation != plan.candidate_generation
            or item.secret_count != expected_counts[item.owner]
            or not item.restart_completed
            or not item.readiness_verified
        ):
            invalid = True

    verified = tuple(owner for owner in plan.owner_order if owner in observed and not invalid_observation(observed[owner], plan, expected_counts[owner]))
    pending = tuple(owner for owner in plan.owner_order if owner not in observed)
    if invalid:
        status = "ROLLBACK_REQUIRED"
        rollback = tuple(owner for owner in reversed(plan.owner_order) if owner in observed)
    elif not observations:
        status = "PREPARED"
        rollback = ()
    elif pending:
        status = "ACTIVATING"
        rollback = ()
    else:
        status = "VERIFIED"
        rollback = ()
    return SecretRotationDecision(
        status=status,
        verified_owners=verified,
        pending_owners=pending,
        rollback_owners=rollback,
        retire_previous_approved=status == "VERIFIED",
        candidate_generation_active=status == "VERIFIED",
    )


def secret_rotation_projection(
    plan: SecretRotationPlan,
    decision: SecretRotationDecision,
) -> dict[str, Any]:
    _validate_plan(plan)
    if decision.status not in {
        "PREPARED",
        "ACTIVATING",
        "VERIFIED",
        "ROLLBACK_REQUIRED",
    }:
        raise ProductionSecretRotationError("secret rotation decision is invalid")
    return {
        "schema_version": plan.schema_version,
        "previous_generation": plan.previous_generation,
        "candidate_generation": plan.candidate_generation,
        "phases": list(plan.phases),
        "rollback_phases": list(plan.rollback_phases),
        "owner_order": list(plan.owner_order),
        "restart_strategy": plan.restart_strategy,
        "plan_digest": plan.plan_digest,
        "status": decision.status,
        "verified_owners": list(decision.verified_owners),
        "pending_owners": list(decision.pending_owners),
        "rollback_owners": list(decision.rollback_owners),
        "retire_previous_approved": decision.retire_previous_approved,
        "candidate_generation_active": decision.candidate_generation_active,
        "raw_secret_values_included": False,
        "reference_values_included": False,
    }


def invalid_observation(
    observation: OwnerRotationObservation,
    plan: SecretRotationPlan,
    expected_count: int,
) -> bool:
    return (
        observation.generation != plan.candidate_generation
        or observation.secret_count != expected_count
        or not observation.restart_completed
        or not observation.readiness_verified
    )


def _owner_targets(
    materialization: ProductionSecretMaterialization,
) -> dict[str, tuple[str, ...]]:
    return {
        item.owner: tuple(secret.target_environment_name for secret in item.secrets)
        for item in materialization.owner_environments
    }


def _validate_plan(plan: SecretRotationPlan) -> None:
    if (
        plan.schema_version != PRODUCTION_SECRET_ROTATION_SCHEMA_VERSION
        or plan.phases != ROTATION_PHASES
        or plan.rollback_phases != ROLLBACK_PHASES
        or plan.owner_order != OWNER_ORDER
        or plan.restart_strategy != "owner_ordered_rolling_restart"
        or _DIGEST.fullmatch(plan.plan_digest) is None
    ):
        raise ProductionSecretRotationError("secret rotation plan is invalid")
