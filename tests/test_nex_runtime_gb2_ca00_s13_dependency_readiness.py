from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from nex_runtime.dependency_readiness import (
    DEPENDENCY_TYPES,
    DependencyReadinessError,
    DependencyReadinessRequirement,
    PlatformDependencyReadiness,
    aggregate_dependency_readiness,
    normalize_dependency_readiness,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-28T09:00:00Z"


def requirement(
    dependency_id: str = "provider:generation",
    *,
    dependency_type: str = "MODEL_PROVIDER",
    owner: str = "nex-mo",
    required: bool = True,
) -> DependencyReadinessRequirement:
    return DependencyReadinessRequirement(
        dependency_id=dependency_id,
        dependency_type=dependency_type,
        owner=owner,
        required=required,
    )


def readiness(
    item: DependencyReadinessRequirement,
    *,
    configured: bool = True,
    provisioned: bool = True,
    reachable: bool = True,
    authorized: bool = True,
    checked_at: str = NOW,
) -> PlatformDependencyReadiness:
    return normalize_dependency_readiness(
        item,
        configured=configured,
        provisioned=provisioned,
        reachable=reachable,
        authorized=authorized,
        checked_at=checked_at,
    )


def test_normalizes_all_dependency_types_without_owner_evidence() -> None:
    inputs = (
        requirement("openbao", dependency_type="OPENBAO", owner="deployment"),
        requirement(
            "object-storage:ae",
            dependency_type="OBJECT_STORAGE",
            owner="nex-ae-api",
        ),
        requirement(),
    )

    projections = [readiness(item).to_projection() for item in inputs]

    assert {item["dependency_type"] for item in projections} == set(DEPENDENCY_TYPES)
    assert all(item["ready"] is True for item in projections)
    assert all(
        set(item)
        == {
            "schema_version",
            "dependency_id",
            "dependency_type",
            "owner",
            "required",
            "configured",
            "provisioned",
            "reachable",
            "authorized",
            "ready",
            "evidence_hash",
            "checked_at",
        }
        for item in projections
    )


def test_configured_is_not_ready_and_authorization_fails_closed() -> None:
    observed = readiness(requirement(), authorized=False)

    assert observed.configured is True
    assert observed.provisioned is True
    assert observed.reachable is True
    assert observed.authorized is False
    assert observed.ready is False
    aggregate = aggregate_dependency_readiness((requirement(),), (observed,))
    assert aggregate["readiness_status"] == "NOT_READY"
    assert aggregate["not_ready_required_dependency_ids"] == [
        "provider:generation"
    ]


def test_missing_required_blocks_but_missing_optional_does_not() -> None:
    required = requirement()
    optional = requirement(
        "object-storage:cx",
        dependency_type="OBJECT_STORAGE",
        owner="nex-cx",
        required=False,
    )

    missing = aggregate_dependency_readiness((required, optional), ())
    optional_missing = aggregate_dependency_readiness(
        (required, optional), (readiness(required),)
    )

    assert missing["readiness_status"] == "NOT_READY"
    assert missing["missing_required_dependency_ids"] == ["provider:generation"]
    assert optional_missing["readiness_status"] == "READY"
    assert optional_missing["missing_optional_dependency_ids"] == [
        "object-storage:cx"
    ]


def test_hashes_are_order_and_clock_stable_without_secret_material() -> None:
    provider = requirement()
    object_store = requirement(
        "object-storage:ae",
        dependency_type="OBJECT_STORAGE",
        owner="nex-ae-api",
    )
    first = readiness(provider, checked_at="2026-10-28T18:00:00+09:00")
    repeated = readiness(provider, checked_at="2026-10-28T09:05:00Z")
    storage = readiness(object_store)

    aggregate_one = aggregate_dependency_readiness(
        (provider, object_store), (first, storage)
    )
    aggregate_two = aggregate_dependency_readiness(
        (object_store, provider), (storage, repeated)
    )
    serialized = json.dumps(aggregate_one, sort_keys=True)

    assert first.checked_at == NOW
    assert first.evidence_hash == repeated.evidence_hash
    assert aggregate_one["evidence_hash"] == aggregate_two["evidence_hash"]
    assert "provider-secret" not in serialized
    assert "api_key" not in serialized
    assert "endpoint" not in serialized


@pytest.mark.parametrize(
    "factory",
    [
        lambda: requirement("Invalid"),
        lambda: requirement(1),
        lambda: requirement(dependency_type="DATABASE"),
        lambda: requirement(owner="https://private.example"),
        lambda: requirement(owner=1),
        lambda: requirement(required=1),
        lambda: readiness(requirement(), checked_at="2026-10-28T09:00:00"),
        lambda: readiness(requirement(), checked_at="not-a-timestamp"),
        lambda: readiness(requirement(), checked_at=None),
        lambda: readiness(requirement(), configured=1),
    ],
)
def test_invalid_contract_values_fail_closed(factory) -> None:
    with pytest.raises(DependencyReadinessError):
        factory()


def test_readiness_model_rejects_forged_state_and_hash() -> None:
    observed = readiness(requirement())
    payload = observed.__dict__

    with pytest.raises(DependencyReadinessError, match="ready must equal"):
        PlatformDependencyReadiness(**{**payload, "ready": False})
    with pytest.raises(DependencyReadinessError, match="hash mismatch"):
        PlatformDependencyReadiness(
            **{**payload, "evidence_hash": "sha256:" + "0" * 64}
        )
    with pytest.raises(DependencyReadinessError, match="canonical UTC"):
        PlatformDependencyReadiness(
            **{**payload, "checked_at": "2026-10-28T18:00:00+09:00"}
        )


@pytest.mark.parametrize(
    "requirements,observations,match",
    [
        ((), (), "inventory is empty"),
        (
            (requirement(), requirement()),
            (),
            "duplicate dependency readiness requirement",
        ),
        (
            (requirement(),),
            (readiness(requirement()), readiness(requirement())),
            "duplicate dependency readiness observation",
        ),
        (
            (requirement(),),
            (
                readiness(
                    requirement(
                        "object-storage:ae",
                        dependency_type="OBJECT_STORAGE",
                        owner="nex-ae-api",
                    )
                ),
            ),
            "undeclared dependency readiness observation",
        ),
        (
            (requirement(),),
            (readiness(requirement(owner="deployment")),),
            "dependency readiness identity drift",
        ),
        (("bad",), (), "requirement is invalid"),
        ((requirement(),), ("bad",), "observation is invalid"),
    ],
)
def test_aggregate_rejects_inventory_and_observation_drift(
    requirements, observations, match
) -> None:
    with pytest.raises(DependencyReadinessError, match=match):
        aggregate_dependency_readiness(requirements, observations)


def test_contract_examples_enforce_bounded_secret_free_projection() -> None:
    schema = json.loads(
        (
            ROOT
            / "contracts/schemas/common/platform_dependency_readiness.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    positive = json.loads(
        (
            ROOT
            / "contracts/examples/common/platform_dependency_readiness.ready.json"
        ).read_text(encoding="utf-8")
    )
    negative = json.loads(
        (
            ROOT
            / "contracts/tests/negative/common/platform_dependency_readiness.secret_leak.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)

    assert not list(validator.iter_errors(positive))
    assert list(validator.iter_errors(negative))
    assert list(validator.iter_errors({**positive, "ready": False}))
    assert list(
        validator.iter_errors({**positive, "authorized": False, "ready": True})
    )
