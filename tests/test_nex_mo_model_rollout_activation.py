from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest
from nex_mo.catalog_lifecycle_repository import InMemoryCatalogLifecycleRepository
from nex_mo.catalog_lifecycle_service import (
    CatalogLifecycleService,
    RegisterCatalogEntry,
)
from nex_mo.model_capacity_scheduler import CapacityReservation
from nex_mo.model_rollout import ModelRevisionIdentity, ModelRolloutError
from nex_mo.model_rollout_activation import (
    activate_rollout_alias,
    rollback_rollout_alias,
)
from nex_mo.model_rollout_state import (
    CanaryMetrics,
    CanaryPolicy,
    begin_validation,
    evaluate_canary,
    mark_rollout_active,
    mark_rollout_ready,
    mark_rollout_rolled_back,
    register_rollout,
    start_canary,
)

DIGESTS = ["sha256:" + char * 64 for char in "abcdef"]
NOW = "2026-10-08T00:00:00Z"


def prepared():
    identifiers = iter(("candidate", "activation", "rollback", "drift"))
    service = CatalogLifecycleService(
        InMemoryCatalogLifecycleRepository(),
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )
    service.ensure_bootstrap()
    stable_binding = next(
        item
        for item in service.list_alias_bindings(state="ACTIVE")
        if item.provider_capability == "generation"
    )
    stable_entry = service.get_catalog_entry(stable_binding.catalog_id)
    stable_identity = ModelRevisionIdentity(
        provider_capability="generation",
        alias=stable_binding.alias,
        catalog_id=stable_entry.catalog_id,
        model_revision=stable_entry.model_revision,
        deployment_id=stable_entry.deployment_id,
        artifact_digest=DIGESTS[0],
        runtime_engine="openai-compatible",
        precision=stable_entry.precision,
        request_shape_hash=DIGESTS[1],
    )
    candidate = service.register_catalog_entry(
        RegisterCatalogEntry(
            provider_capability="generation",
            model_name="Candidate",
            model_revision="candidate-v2",
            deployment_id="candidate-generation-v2",
            runtime_profile="generation-candidate",
            precision="bfloat16",
            provider_type="openai-compatible",
            supports_response_formats=("text", "json_object"),
            max_input_tokens=8192,
            max_output_tokens=1024,
        )
    )
    candidate = service.transition_catalog_entry(
        candidate.catalog_id,
        expected_revision=1,
        target_state="ACTIVE",
    )
    candidate_identity = ModelRevisionIdentity(
        provider_capability="generation",
        alias=stable_binding.alias,
        catalog_id=candidate.catalog_id,
        model_revision=candidate.model_revision,
        deployment_id=candidate.deployment_id,
        artifact_digest=DIGESTS[2],
        runtime_engine="openai-compatible",
        precision="bfloat16",
        request_shape_hash=DIGESTS[1],
    )
    record = register_rollout(
        candidate_identity,
        rollout_id="rollout:generation:2",
        last_known_good_binding_id=stable_binding.binding_id,
        last_known_good_identity_fingerprint=stable_identity.fingerprint,
        created_at=NOW,
    )
    record = begin_validation(record, changed_at="2026-10-08T00:01:00Z")
    reservation = CapacityReservation(
        reservation_id="reservation:generation:2",
        rollout_id=record.rollout_id,
        identity_fingerprint=candidate_identity.fingerprint,
        node_id="node:one",
        gpu_count=1,
        memory_mib=20_000,
        concurrency=2,
        exclusive=False,
    )
    record = mark_rollout_ready(
        record,
        {
            "status": "READY",
            "identity_fingerprint": candidate_identity.fingerprint,
            "evidence_digest": DIGESTS[3],
        },
        {
            "status": "CALIBRATED",
            "identity_fingerprint": candidate_identity.fingerprint,
            "profile_id": "calibration:generation:2",
            "profile_hash": DIGESTS[4],
        },
        reservation,
        changed_at="2026-10-08T00:02:00Z",
    )
    policy = CanaryPolicy(10, 300, 100, 0.02, 0.85, 2_000)
    record = start_canary(record, policy, changed_at="2026-10-08T00:03:00Z")
    record, decision = evaluate_canary(
        record,
        policy,
        CanaryMetrics(
            identity_fingerprint=candidate_identity.fingerprint,
            sample_count=120,
            error_rate=0.01,
            quality_score=0.9,
            p95_latency_ms=1_500,
            observed_seconds=360,
            measured_at="2026-10-08T00:09:00Z",
        ),
        changed_at="2026-10-08T00:09:00Z",
    )
    return service, stable_identity, reservation, record, decision


def activate(context=None):
    service, stable, reservation, record, decision = context or prepared()
    result = activate_rollout_alias(
        record,
        decision,
        reservation,
        stable,
        service,
        changed_by="operator:test",
        changed_at="2026-10-08T00:10:00Z",
    )
    return service, stable, reservation, result


def test_activation_and_exact_rollback_preserve_lineage_and_release_capacity() -> None:
    service, stable, reservation, activated = activate()

    assert activated.operation == "ACTIVATED"
    assert activated.record.state == "ACTIVE"
    assert activated.record.activated_binding_id == activated.binding.binding_id
    assert activated.binding.previous_binding_id == activated.record.last_known_good_binding_id
    assert activated.reservation.state == "RESERVED"
    wire = activated.to_wire()
    assert wire["decision_digest"].startswith("sha256:")
    assert "model_name" not in wire and "endpoint" not in wire

    rolled_back = rollback_rollout_alias(
        activated.record,
        reservation,
        stable,
        {
            "status": "READY",
            "identity_fingerprint": stable.fingerprint,
            "evidence_digest": DIGESTS[5],
        },
        service,
        failure_code="quality_regression",
        changed_by="operator:test",
        changed_at="2026-10-08T00:11:00Z",
    )

    assert rolled_back.operation == "ROLLED_BACK"
    assert rolled_back.record.state == "ROLLED_BACK"
    assert rolled_back.record.failure_code == "quality_regression"
    assert rolled_back.binding.catalog_id == stable.catalog_id
    assert rolled_back.reservation.state == "RELEASED"
    assert reservation.state == "RESERVED"


@pytest.mark.parametrize(
    ("record_change", "decision_change", "reservation_change", "code"),
    [
        ({"canary_status": "RUNNING"}, {}, {}, "mo.rollout_promotion_not_admitted"),
        ({}, {"promotable": False}, {}, "mo.rollout_canary_decision_invalid"),
        ({}, {"identity_fingerprint": DIGESTS[5]}, {}, "mo.rollout_canary_decision_invalid"),
        ({}, {}, {"state": "RELEASED"}, "mo.rollout_reservation_drift"),
        ({}, {}, {"reservation_id": "reservation:other"}, "mo.rollout_reservation_drift"),
    ],
)
def test_activation_fails_closed_on_admission_drift(
    record_change,
    decision_change,
    reservation_change,
    code: str,
) -> None:
    service, stable, reservation, record, decision = prepared()
    with pytest.raises(ModelRolloutError) as exc:
        activate_rollout_alias(
            replace(record, **record_change),
            {**decision, **decision_change},
            replace(reservation, **reservation_change),
            stable,
            service,
            changed_by="operator:test",
            changed_at="2026-10-08T00:10:00Z",
        )
    assert exc.value.error_code == code


def test_activation_rejects_last_known_good_and_catalog_identity_drift() -> None:
    service, stable, reservation, record, decision = prepared()
    with pytest.raises(ModelRolloutError) as exc:
        activate_rollout_alias(
            record,
            decision,
            reservation,
            replace(stable, artifact_digest=DIGESTS[5]),
            service,
            changed_by="operator:test",
            changed_at="2026-10-08T00:10:00Z",
        )
    assert exc.value.error_code == "mo.rollout_last_known_good_drift"

    changed_identity = replace(record.identity, model_revision="candidate-v3")
    changed_record = replace(record, identity=changed_identity)
    changed_reservation = replace(
        reservation,
        identity_fingerprint=changed_identity.fingerprint,
    )
    changed_decision = {
        **decision,
        "identity_fingerprint": changed_identity.fingerprint,
    }
    with pytest.raises(ModelRolloutError) as exc:
        activate_rollout_alias(
            changed_record,
            changed_decision,
            changed_reservation,
            stable,
            service,
            changed_by="operator:test",
            changed_at="2026-10-08T00:10:00Z",
        )
    assert exc.value.error_code == "mo.rollout_catalog_identity_drift"


def test_activation_requires_exactly_one_active_binding() -> None:
    service, stable, reservation, record, decision = prepared()
    repository = service._repository
    repository._bindings.pop(record.last_known_good_binding_id)
    with pytest.raises(ModelRolloutError) as exc:
        activate_rollout_alias(
            record,
            decision,
            reservation,
            stable,
            service,
            changed_by="operator:test",
            changed_at="2026-10-08T00:10:00Z",
        )
    assert exc.value.error_code == "mo.rollout_active_binding_invalid"


def test_rollback_guards_active_binding_readiness_and_lineage() -> None:
    service, stable, reservation, activated = activate()
    base_readiness = {
        "status": "READY",
        "identity_fingerprint": stable.fingerprint,
        "evidence_digest": DIGESTS[5],
    }
    with pytest.raises(ModelRolloutError) as exc:
        rollback_rollout_alias(
            replace(activated.record, state="CANARY"),
            reservation,
            stable,
            base_readiness,
            service,
            failure_code="quality_regression",
            changed_by="operator:test",
            changed_at="2026-10-08T00:11:00Z",
        )
    assert exc.value.error_code == "mo.rollout_rollback_not_available"

    with pytest.raises(ModelRolloutError) as exc:
        rollback_rollout_alias(
            activated.record,
            replace(reservation, state="RELEASED"),
            stable,
            base_readiness,
            service,
            failure_code="quality_regression",
            changed_by="operator:test",
            changed_at="2026-10-08T00:11:00Z",
        )
    assert exc.value.error_code == "mo.rollout_reservation_drift"

    with pytest.raises(ModelRolloutError) as exc:
        rollback_rollout_alias(
            activated.record,
            reservation,
            stable,
            {**base_readiness, "status": "STALE"},
            service,
            failure_code="quality_regression",
            changed_by="operator:test",
            changed_at="2026-10-08T00:11:00Z",
        )
    assert exc.value.error_code == "mo.rollout_last_known_good_not_ready"

    service._repository._bindings.pop(activated.record.last_known_good_binding_id)
    with pytest.raises(ModelRolloutError) as exc:
        rollback_rollout_alias(
            activated.record,
            reservation,
            stable,
            base_readiness,
            service,
            failure_code="quality_regression",
            changed_by="operator:test",
            changed_at="2026-10-08T00:11:00Z",
        )
    assert exc.value.error_code == "mo.rollout_last_known_good_missing"


def test_rollback_rejects_active_alias_and_restored_target_drift() -> None:
    service, stable, reservation, activated = activate()
    readiness = {
        "status": "READY",
        "identity_fingerprint": stable.fingerprint,
        "evidence_digest": DIGESTS[5],
    }
    service.rollback_alias(
        alias=activated.record.identity.alias,
        capability="generation",
        expected_binding_revision=activated.binding.binding_revision,
        change_reason="external rollback",
        changed_by="operator:test",
    )
    with pytest.raises(ModelRolloutError) as exc:
        rollback_rollout_alias(
            activated.record,
            reservation,
            stable,
            readiness,
            service,
            failure_code="quality_regression",
            changed_by="operator:test",
            changed_at="2026-10-08T00:11:00Z",
        )
    assert exc.value.error_code == "mo.rollout_active_binding_drift"

    service, stable, reservation, activated = activate()
    proxy = Mock(spec=CatalogLifecycleService, wraps=service)
    proxy.rollback_alias.return_value = replace(
        activated.binding,
        binding_id="binding:wrong-target",
        binding_revision=activated.binding.binding_revision + 1,
        previous_binding_id=activated.binding.binding_id,
    )
    with pytest.raises(ModelRolloutError) as exc:
        rollback_rollout_alias(
            activated.record,
            reservation,
            stable,
            readiness,
            proxy,
            failure_code="quality_regression",
            changed_by="operator:test",
            changed_at="2026-10-08T00:11:00Z",
        )
    assert exc.value.error_code == "mo.rollout_rollback_target_drift"


def test_state_rollback_helper_requires_active_binding() -> None:
    _, _, _, record, _ = prepared()
    with pytest.raises(ModelRolloutError) as exc:
        mark_rollout_active(
            replace(record, canary_status="RUNNING"),
            activated_binding_id="binding:candidate",
            changed_at="2026-10-08T00:10:00Z",
        )
    assert exc.value.error_code == "mo.rollout_promotion_not_admitted"

    with pytest.raises(ModelRolloutError) as exc:
        mark_rollout_rolled_back(
            record,
            failure_code="quality_regression",
            changed_at="2026-10-08T00:10:00Z",
        )
    assert exc.value.error_code == "mo.rollout_rollback_not_available"
