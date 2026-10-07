from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nex_runtime.production_secret_materialization import materialize_production_secrets
from nex_runtime.production_secret_rotation import (
    OWNER_ORDER,
    OwnerRotationObservation,
    ProductionSecretRotationError,
    build_secret_rotation_plan,
    evaluate_secret_rotation,
    secret_rotation_projection,
)
from run_platform_production_secret_materialization import _DeterministicSecretResolver
from run_platform_production_secret_rotation import (
    _candidate_environment,
    _observations,
)
from run_platform_production_startup_admission import _synthetic_environment


ROOT = Path(__file__).resolve().parents[1]


def materializations():
    first_env = _synthetic_environment(ROOT)
    second_env = _candidate_environment(first_env)
    return (
        materialize_production_secrets(
            first_env, _DeterministicSecretResolver(), root=ROOT
        ),
        materialize_production_secrets(
            second_env, _DeterministicSecretResolver(), root=ROOT
        ),
    )


def test_rotation_lifecycle_requires_every_owner_before_retirement() -> None:
    plan = build_secret_rotation_plan(*materializations())
    observations = _observations(plan)
    assert evaluate_secret_rotation(plan, ()).status == "PREPARED"
    partial = evaluate_secret_rotation(plan, observations[:3])
    assert partial.status == "ACTIVATING"
    assert partial.pending_owners == OWNER_ORDER[3:]
    assert partial.retire_previous_approved is False
    verified = evaluate_secret_rotation(plan, observations)
    assert verified.status == "VERIFIED"
    assert verified.candidate_generation_active is True
    assert verified.retire_previous_approved is True
    projection = secret_rotation_projection(plan, verified)
    assert projection["raw_secret_values_included"] is False
    assert projection["reference_values_included"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: replace(value, generation="secret:old"),
        lambda value: replace(value, secret_count=value.secret_count + 1),
        lambda value: replace(value, restart_completed=False),
        lambda value: replace(value, readiness_verified=False),
    ],
)
def test_invalid_owner_observation_requires_reverse_rollback(mutation) -> None:
    plan = build_secret_rotation_plan(*materializations())
    values = list(_observations(plan))
    values[1] = mutation(values[1])
    decision = evaluate_secret_rotation(plan, values)
    assert decision.status == "ROLLBACK_REQUIRED"
    assert decision.rollback_owners == tuple(reversed(OWNER_ORDER))
    assert decision.retire_previous_approved is False


def test_duplicate_or_unknown_owner_requires_rollback() -> None:
    plan = build_secret_rotation_plan(*materializations())
    values = _observations(plan)
    duplicate = evaluate_secret_rotation(plan, (*values, values[0]))
    assert duplicate.status == "ROLLBACK_REQUIRED"
    unknown = replace(values[0], owner="unknown")
    assert evaluate_secret_rotation(plan, (unknown,)).status == "ROLLBACK_REQUIRED"


def test_plan_rejects_generation_status_target_and_owner_drift() -> None:
    previous, candidate = materializations()
    with pytest.raises(ProductionSecretRotationError, match="must change"):
        build_secret_rotation_plan(previous, replace(candidate, secret_generation=previous.secret_generation))
    with pytest.raises(ProductionSecretRotationError, match="not active"):
        build_secret_rotation_plan(replace(previous, status="OTHER"), candidate)
    with pytest.raises(ProductionSecretRotationError, match="not prepared"):
        build_secret_rotation_plan(previous, replace(candidate, status="OTHER"))
    reduced = replace(candidate, owner_environments=candidate.owner_environments[:-1])
    with pytest.raises(ProductionSecretRotationError, match="target drift"):
        build_secret_rotation_plan(previous, reduced)
    reduced_previous = replace(
        previous, owner_environments=previous.owner_environments[:-1]
    )
    with pytest.raises(ProductionSecretRotationError, match="coverage drift"):
        build_secret_rotation_plan(reduced_previous, reduced)


def test_projection_and_evaluation_reject_invalid_plan_or_decision() -> None:
    plan = build_secret_rotation_plan(*materializations())
    broken = replace(plan, plan_digest="bad")
    with pytest.raises(ProductionSecretRotationError, match="plan is invalid"):
        evaluate_secret_rotation(broken, ())
    decision = evaluate_secret_rotation(plan, ())
    with pytest.raises(ProductionSecretRotationError, match="decision is invalid"):
        secret_rotation_projection(plan, replace(decision, status="OTHER"))
