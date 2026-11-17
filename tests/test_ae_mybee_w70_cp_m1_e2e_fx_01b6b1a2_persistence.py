from __future__ import annotations

import pytest
from nex_ae_api.product_preparation_persistence import (
    ProductPreparationPersistenceError,
    SqlAlchemyGeneralizedWaitEventRepository,
    SqlAlchemyProductPreparationCheckpointRepository,
    product_preparation_wait_envelope,
    seal_product_preparation_checkpoint,
    seal_product_preparation_event,
    seal_product_preparation_event_binding,
    seal_product_preparation_wait_binding,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TENANT = "tenant-6b1a2"
EXECUTION_ID = "11111111-1111-4111-8111-111111116b12"
WORK_INTENT_ID = "22222222-2222-4222-8222-222222226b12"
CONTEXT_ID = "33333333-3333-4333-8333-333333336b12"
CHECKPOINT_ID = "44444444-4444-4444-8444-444444446b12"
WAIT_ID = "55555555-5555-4555-8555-555555556b12"
STEP_ID = "66666666-6666-4666-8666-666666666b12"
EVENT_ID = "event-6b1a2"
NOW = "2026-11-17T06:00:00Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
COORDINATOR_ID = "MYBEE.M1.TRANSACTION_PREPARATION"
COORDINATOR_VERSION = "1.0.0"


@pytest.fixture
def sessions():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in _SCHEMA:
            connection.execute(text(statement))
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def _checkpoint_base(**changes):
    value = {
        "tenant_id": TENANT,
        "checkpoint_id": CHECKPOINT_ID,
        "checkpoint_schema_version": "ae.product_preparation_checkpoint.v1",
        "checkpoint_version": 1,
        "previous_checkpoint_id": None,
        "previous_checkpoint_hash": None,
        "agent_execution_id": EXECUTION_ID,
        "requester_ref": "employee-6b1a2",
        "work_intent_id": WORK_INTENT_ID,
        "work_intent_revision": 1,
        "work_intent_hash": HASH_A,
        "agent_context_id": CONTEXT_ID,
        "context_generation": 1,
        "context_hash": HASH_B,
        "business_context_hash": HASH_C,
        "capability_id": "FINANCE.VOUCHER.APPROVE_AND_POST",
        "capability_version": "1.0.0",
        "capability_release_ref": "release://mybee/d04/v1",
        "capability_registration_hash": HASH_D,
        "coordinator_id": COORDINATOR_ID,
        "coordinator_version": COORDINATOR_VERSION,
        "coordinator_registration_hash": HASH_A,
        "preparation_adapter_source_identity": "nex-ae:m1-preparation-adapter:v1",
        "materializer_source_identity": "nex-ae:m1-plan-materializer:v1",
        "stage": "WAITING_BUSINESS_APPROVAL",
        "stage_kind": "WAITING",
        "authority_refs": [
            {
                "authority_kind": "BUSINESS_FORMAL",
                "authority_ref": "wc://approval/case-6b1a2",
            }
        ],
        "idempotency_key": "product-preparation:6b1a2:v1",
        "correlation_id": "correlation-6b1a2",
        "causation_id": None,
        "created_at": NOW,
    }
    value.update(changes)
    return value


def _checkpoint(**changes):
    return seal_product_preparation_checkpoint(_checkpoint_base(**changes))


def _wait(**changes):
    value = {
        "tenant_id": TENANT,
        "wait_id": WAIT_ID,
        "agent_execution_id": EXECUTION_ID,
        "external_ref": "wc://approval/case-6b1a2",
        "wait_contract_ref": "contract://nex/ae/product-preparation-wait/v1",
        "created_at": NOW,
    }
    value.update(changes)
    return product_preparation_wait_envelope(value)


def _wait_binding(checkpoint=None, **changes):
    checkpoint = checkpoint or _checkpoint()
    value = {
        "tenant_id": TENANT,
        "wait_id": WAIT_ID,
        "checkpoint_id": checkpoint["checkpoint_id"],
        "checkpoint_hash": checkpoint["checkpoint_hash"],
        "coordinator_id": COORDINATOR_ID,
        "coordinator_version": COORDINATOR_VERSION,
        "coordinator_registration_hash": HASH_A,
        "expected_event_type": "BUSINESS_APPROVAL_CHANGED",
        "authority_kind": "BUSINESS_FORMAL",
        "authority_ref": "wc://approval/case-6b1a2",
        "agent_execution_id": EXECUTION_ID,
        "work_intent_id": WORK_INTENT_ID,
        "created_at": NOW,
    }
    value.update(changes)
    return seal_product_preparation_wait_binding(value)


def _event(**changes):
    value = {
        "tenant_id": TENANT,
        "event_id": EVENT_ID,
        "event_type": "BUSINESS_APPROVAL_CHANGED",
        "external_ref": "wc://approval/case-6b1a2",
        "event_payload": {
            "schema_version": "ae.product_preparation_notification.v1",
            "notification_ref": "wc-event://decision/6b1a2",
        },
        "received_at": NOW,
    }
    value.update(changes)
    return seal_product_preparation_event(value)


def _event_binding(checkpoint=None, **changes):
    checkpoint = checkpoint or _checkpoint()
    value = {
        "tenant_id": TENANT,
        "event_id": EVENT_ID,
        "wait_id": WAIT_ID,
        "checkpoint_id": checkpoint["checkpoint_id"],
        "checkpoint_hash": checkpoint["checkpoint_hash"],
        "coordinator_id": COORDINATOR_ID,
        "coordinator_version": COORDINATOR_VERSION,
        "coordinator_registration_hash": HASH_A,
        "authority_kind": "BUSINESS_FORMAL",
        "notification_ref": "wc-event://decision/6b1a2",
        "agent_execution_id": EXECUTION_ID,
        "work_intent_id": WORK_INTENT_ID,
        "created_at": NOW,
    }
    value.update(changes)
    return seal_product_preparation_event_binding(value)


def _legacy_wait(**changes):
    value = {
        "tenant_id": TENANT,
        "wait_id": WAIT_ID,
        "agent_execution_id": EXECUTION_ID,
        "executable_step_id": STEP_ID,
        "wait_type": "WORK_RESULT",
        "external_ref": "wc://work-item/6b1a2",
        "result_contract_ref": "contract://work-result/v1",
        "wait_contract_ref": "contract://work-result/v1",
        "resume_target_kind": "EXECUTABLE_STEP",
        "nsl_execution_id": None,
        "business_operation_id": None,
        "approval_request_id": None,
        "checkpoint_version": None,
        "created_at": NOW,
    }
    value.update(changes)
    return value


def _legacy_event(**changes):
    payload = {"schema_version": "wc.work_result.v1", "status": "SUCCEEDED"}
    value = {
        "tenant_id": TENANT,
        "event_id": EVENT_ID,
        "event_family": "WORK_RESULT",
        "event_type": "WORK_RESULT_SUBMITTED",
        "event_semantic_hash": semantic_sha256_hash_ref(payload),
        "external_ref": "wc://work-item/6b1a2",
        "event_payload": payload,
        "received_at": NOW,
        "result_id": "result-6b1a2",
        "result_contract_ref": "contract://work-result/v1",
        "approval_request_id": None,
        "approval_work_item_ref": None,
        "approval_evidence_ref": None,
        "evidence_integrity": None,
        "nsl_execution_id": None,
        "business_operation_id": None,
    }
    value.update(changes)
    return value


def test_checkpoint_seal_is_deterministic_and_time_independent() -> None:
    first = _checkpoint()
    replay = _checkpoint(created_at="2026-11-17T15:01:00+09:00")

    assert first["checkpoint_hash"] == replay["checkpoint_hash"]
    assert first["checkpoint_projection"]["checkpoint_hash"] == first[
        "checkpoint_hash"
    ]
    assert first["created_at"] == NOW
    assert replay["created_at"] == "2026-11-17T06:01:00Z"


@pytest.mark.parametrize(
    ("changes", "detail"),
    [
        ({"stage_kind": "OTHER"}, "stage_kind"),
        ({"checkpoint_version": 2}, "chain"),
        ({"previous_checkpoint_id": WAIT_ID}, "chain"),
        ({"work_intent_hash": "not-a-hash"}, "work_intent_hash"),
        ({"created_at": "2026-11-17"}, "timezone"),
        ({"authority_refs": {}}, "array"),
    ],
)
def test_checkpoint_seal_rejects_invalid_contract(changes, detail) -> None:
    with pytest.raises(ProductPreparationPersistenceError) as exc_info:
        _checkpoint(**changes)

    assert detail in exc_info.value.detail


def test_checkpoint_repository_appends_replays_and_loads_latest(sessions) -> None:
    repository = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    first = _checkpoint()

    saved = repository.append(first)
    replay = repository.append(
        _checkpoint(created_at="2026-11-17T06:05:00Z")
    )

    assert replay == saved
    assert repository.get(tenant_id=TENANT, checkpoint_id=CHECKPOINT_ID) == saved
    assert repository.latest(
        tenant_id=TENANT,
        agent_execution_id=EXECUTION_ID,
        coordinator_id=COORDINATOR_ID,
        coordinator_version=COORDINATOR_VERSION,
    ) == saved
    assert repository.get(tenant_id=TENANT, checkpoint_id=WAIT_ID) is None


def test_checkpoint_repository_rejects_changed_idempotent_replay(sessions) -> None:
    repository = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    repository.append(_checkpoint())

    with pytest.raises(ProductPreparationPersistenceError) as exc_info:
        repository.append(
            _checkpoint(stage="WAITING_ACCOUNTING_APPROVAL")
        )

    assert exc_info.value.error_code.endswith("_conflict")
    assert repository.latest(
        tenant_id=TENANT,
        agent_execution_id=EXECUTION_ID,
        coordinator_id=COORDINATOR_ID,
        coordinator_version=COORDINATOR_VERSION,
    )["stage"] == "WAITING_BUSINESS_APPROVAL"


def test_product_wait_registration_is_atomic_and_exactly_replayable(sessions) -> None:
    checkpoints = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)
    checkpoint = checkpoints.append(_checkpoint())
    binding = _wait_binding(checkpoint)

    first = repository.register_wait(_wait(), product_binding=binding)
    replay_binding = _wait_binding(
        checkpoint,
        created_at="2026-11-17T06:03:00Z",
    )
    replay = repository.register_wait(
        _wait(created_at="2026-11-17T06:03:00Z"),
        product_binding=replay_binding,
    )

    assert replay == first
    assert first["wait"]["resume_target_kind"] == "PRODUCT_COORDINATOR"
    assert first["product_binding"]["binding_hash"] == binding["binding_hash"]
    context = repository.load_product_wait_context(
        tenant_id=TENANT, wait_id=WAIT_ID
    )
    assert context["checkpoint"]["checkpoint_hash"] == checkpoint["checkpoint_hash"]
    assert context["product_binding"]["authority_kind"] == "BUSINESS_FORMAL"


def test_product_wait_requires_matching_typed_binding(sessions) -> None:
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)

    with pytest.raises(ProductPreparationPersistenceError, match="typed binding"):
        repository.register_wait(_wait())
    with pytest.raises(ProductPreparationPersistenceError, match="lineage differs"):
        repository.register_wait(
            _wait(),
            product_binding=_wait_binding(agent_execution_id=STEP_ID),
        )
    with pytest.raises(ProductPreparationPersistenceError, match="seal differs"):
        changed = _wait_binding()
        changed["binding_hash"] = HASH_D
        repository.register_wait(_wait(), product_binding=changed)


def test_product_wait_conflict_has_zero_mutation(sessions) -> None:
    checkpoints = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)
    checkpoint = checkpoints.append(_checkpoint())
    repository.register_wait(_wait(), product_binding=_wait_binding(checkpoint))

    conflicting = _wait()
    conflicting["wait_contract_ref"] = "contract://different"
    with pytest.raises(ProductPreparationPersistenceError) as exc_info:
        repository.register_wait(
            conflicting,
            product_binding=_wait_binding(checkpoint),
        )

    assert exc_info.value.error_code.endswith("_conflict")
    assert repository.get_wait(tenant_id=TENANT, wait_id=WAIT_ID)[
        "wait_contract_ref"
    ] == "contract://nex/ae/product-preparation-wait/v1"


def test_product_event_acceptance_is_atomic_and_exactly_replayable(sessions) -> None:
    checkpoints = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)
    checkpoint = checkpoints.append(_checkpoint())
    repository.register_wait(_wait(), product_binding=_wait_binding(checkpoint))

    first = repository.accept_event(
        _event(), product_binding=_event_binding(checkpoint)
    )
    replay = repository.accept_event(
        _event(received_at="2026-11-17T06:10:00Z"),
        product_binding=_event_binding(
            checkpoint, created_at="2026-11-17T06:10:00Z"
        ),
    )

    assert replay == first
    assert first["event"]["event_family"] == "PRODUCT_PREPARATION"
    assert repository.get_event(tenant_id=TENANT, event_id=EVENT_ID) == first["event"]
    context = repository.load_product_event_context(
        tenant_id=TENANT, event_id=EVENT_ID
    )
    assert context["wait_binding"]["wait_id"] == WAIT_ID
    assert context["checkpoint"]["checkpoint_hash"] == checkpoint["checkpoint_hash"]


def test_product_event_conflict_and_binding_drift_are_denied(sessions) -> None:
    checkpoints = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)
    checkpoint = checkpoints.append(_checkpoint())
    repository.register_wait(_wait(), product_binding=_wait_binding(checkpoint))
    repository.accept_event(_event(), product_binding=_event_binding(checkpoint))

    with pytest.raises(ProductPreparationPersistenceError) as conflict:
        repository.accept_event(
            _event(event_payload={"notification_ref": "changed"}),
            product_binding=_event_binding(
                checkpoint, notification_ref="changed"
            ),
        )
    assert conflict.value.error_code.endswith("_conflict")

    with pytest.raises(ProductPreparationPersistenceError, match="typed binding"):
        repository.accept_event(
            _event(event_id="event-without-binding"),
        )
    with pytest.raises(ProductPreparationPersistenceError, match="notification"):
        repository.accept_event(
            _event(event_id="event-notification-drift"),
            product_binding=_event_binding(
                checkpoint,
                event_id="event-notification-drift",
                notification_ref="wc-event://decision/other",
            ),
        )


def test_typed_binding_replay_drift_is_denied(sessions) -> None:
    checkpoints = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)
    checkpoint = checkpoints.append(_checkpoint())
    repository.register_wait(_wait(), product_binding=_wait_binding(checkpoint))
    repository.accept_event(_event(), product_binding=_event_binding(checkpoint))

    with pytest.raises(ProductPreparationPersistenceError, match="wait binding"):
        repository.register_wait(
            _wait(),
            product_binding=_wait_binding(checkpoint, checkpoint_id=STEP_ID),
        )
    with pytest.raises(ProductPreparationPersistenceError, match="event binding"):
        repository.accept_event(
            _event(),
            product_binding=_event_binding(checkpoint, wait_id=STEP_ID),
        )


def test_product_binding_cannot_be_mixed_with_legacy_envelopes(sessions) -> None:
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)

    with pytest.raises(ProductPreparationPersistenceError, match="Legacy wait"):
        repository.register_wait(
            _legacy_wait(),
            product_binding=_wait_binding(),
        )
    with pytest.raises(ProductPreparationPersistenceError, match="Legacy event"):
        repository.accept_event(
            _legacy_event(),
            product_binding=_event_binding(),
        )


def test_product_binding_authority_and_lineage_are_fail_closed(sessions) -> None:
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)

    with pytest.raises(ProductPreparationPersistenceError, match="authority reference"):
        repository.register_wait(
            _wait(),
            product_binding=_wait_binding(authority_ref="wc://approval/other"),
        )
    with pytest.raises(ProductPreparationPersistenceError, match="lineage differs"):
        repository.accept_event(
            _event(),
            product_binding=_event_binding(event_id="different-event"),
        )
    drifted = _event_binding()
    drifted["binding_hash"] = HASH_B
    with pytest.raises(ProductPreparationPersistenceError, match="seal differs"):
        repository.accept_event(_event(), product_binding=drifted)


def test_product_resume_context_rejects_legacy_or_incomplete_lineage(sessions) -> None:
    checkpoints = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)
    checkpoint = checkpoints.append(_checkpoint())
    repository.register_wait(_wait(), product_binding=_wait_binding(checkpoint))
    repository.accept_event(_event(), product_binding=_event_binding(checkpoint))

    repository.accept_event(_legacy_event(event_id="legacy-event"))
    with pytest.raises(ProductPreparationPersistenceError, match="not a Product"):
        repository.load_product_event_context(
            tenant_id=TENANT,
            event_id="legacy-event",
        )

    with sessions.begin() as session:
        session.execute(
            text(
                "DELETE FROM ae_product_prep_event_binding "
                "WHERE tenant_id = :tenant_id AND event_id = :event_id"
            ),
            {"tenant_id": TENANT, "event_id": EVENT_ID},
        )
    with pytest.raises(ProductPreparationPersistenceError, match="binding is missing"):
        repository.load_product_event_context(tenant_id=TENANT, event_id=EVENT_ID)

    repository.accept_event(
        _event(event_id="incomplete-event"),
        product_binding=_event_binding(checkpoint, event_id="incomplete-event"),
    )
    with sessions.begin() as session:
        session.execute(
            text(
                "DELETE FROM ae_product_prep_wait_binding "
                "WHERE tenant_id = :tenant_id AND wait_id = :wait_id"
            ),
            {"tenant_id": TENANT, "wait_id": WAIT_ID},
        )
    with pytest.raises(ProductPreparationPersistenceError, match="lineage is incomplete"):
        repository.load_product_event_context(
            tenant_id=TENANT,
            event_id="incomplete-event",
        )


@pytest.mark.parametrize(
    ("value", "detail"),
    [
        (_checkpoint_base(checkpoint_id="not-a-uuid"), "UUID"),
        (_checkpoint_base(work_intent_revision=False), "positive integer"),
        (_checkpoint_base(requester_ref=" "), "non-empty string"),
        (_checkpoint_base(created_at="not-a-time"), "RFC3339"),
    ],
)
def test_checkpoint_scalar_validation_is_fail_closed(value, detail) -> None:
    with pytest.raises(ProductPreparationPersistenceError, match=detail):
        seal_product_preparation_checkpoint(value)


def test_malformed_json_and_unsealed_envelopes_are_domain_errors(sessions) -> None:
    checkpoints = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)

    with pytest.raises(ProductPreparationPersistenceError, match="valid JSON"):
        seal_product_preparation_event(
            {
                "tenant_id": TENANT,
                "event_id": EVENT_ID,
                "event_type": "BUSINESS_APPROVAL_CHANGED",
                "external_ref": "wc://approval/case-6b1a2",
                "event_payload": "{invalid",
                "received_at": NOW,
            }
        )
    with pytest.raises(ProductPreparationPersistenceError, match="must be an object"):
        seal_product_preparation_event(
            {
                "tenant_id": TENANT,
                "event_id": EVENT_ID,
                "event_type": "BUSINESS_APPROVAL_CHANGED",
                "external_ref": "wc://approval/case-6b1a2",
                "event_payload": [],
                "received_at": NOW,
            }
        )
    with pytest.raises(ProductPreparationPersistenceError, match="fields are invalid"):
        checkpoints.append(_checkpoint_base())
    with pytest.raises(ProductPreparationPersistenceError, match="fields are invalid"):
        repository.register_wait({**_wait(), "unexpected": True})


def test_wait_and_event_family_shapes_reject_semantic_drift(sessions) -> None:
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)

    invalid_wait = _wait()
    invalid_wait["resume_target_kind"] = "EXECUTABLE_STEP"
    with pytest.raises(ProductPreparationPersistenceError, match="wait envelope"):
        repository.register_wait(invalid_wait, product_binding=_wait_binding())

    invalid_event = _event()
    invalid_event["event_semantic_hash"] = HASH_D
    with pytest.raises(ProductPreparationPersistenceError, match="event envelope"):
        repository.accept_event(invalid_event, product_binding=_event_binding())
    with pytest.raises(ProductPreparationPersistenceError, match="family and type"):
        repository.accept_event(_legacy_event(event_type="OTHER"))
    with pytest.raises(ProductPreparationPersistenceError, match="WorkResult event"):
        repository.accept_event(
            _legacy_event(approval_request_id="unexpected-approval")
        )


def test_generalized_repository_preserves_legacy_wait_and_event_envelopes(
    sessions,
) -> None:
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)
    saved_wait = repository.register_wait(_legacy_wait())
    saved_event = repository.accept_event(_legacy_event())

    assert saved_wait["product_binding"] is None
    assert saved_wait["wait"]["resume_target_kind"] == "EXECUTABLE_STEP"
    assert saved_event["product_binding"] is None
    assert saved_event["event"]["event_family"] == "WORK_RESULT"


def test_generalized_repository_preserves_nsl_wait_and_event_shape(sessions) -> None:
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)
    request_id = "approval-request-6b1a2"
    wait_id = "77777777-7777-4777-8777-777777776b12"
    nsl_wait = {
        "tenant_id": TENANT,
        "wait_id": wait_id,
        "agent_execution_id": EXECUTION_ID,
        "executable_step_id": STEP_ID,
        "wait_type": "NSL_APPROVAL",
        "external_ref": request_id,
        "result_contract_ref": "contract://nsl-approval/v1",
        "wait_contract_ref": "contract://nsl-approval/v1",
        "resume_target_kind": "EXECUTABLE_STEP",
        "nsl_execution_id": "nsl-execution-6b1a2",
        "business_operation_id": "business-operation-6b1a2",
        "approval_request_id": request_id,
        "checkpoint_version": 1,
        "created_at": NOW,
    }
    nsl_event = {
        "tenant_id": TENANT,
        "event_id": "nsl-event-6b1a2",
        "event_family": "NSL_APPROVAL",
        "event_type": "NSL_APPROVAL_DECIDED",
        "event_semantic_hash": HASH_A,
        "external_ref": request_id,
        "event_payload": {"decision": "APPROVED"},
        "received_at": NOW,
        "result_id": None,
        "result_contract_ref": None,
        "approval_request_id": request_id,
        "approval_work_item_ref": "approval-work-item-6b1a2",
        "approval_evidence_ref": "evidence://approval/6b1a2",
        "evidence_integrity": HASH_D,
        "nsl_execution_id": "nsl-execution-6b1a2",
        "business_operation_id": "business-operation-6b1a2",
    }

    assert repository.register_wait(nsl_wait)["wait"]["wait_type"] == "NSL_APPROVAL"
    assert repository.accept_event(nsl_event)["event"][
        "event_family"
    ] == "NSL_APPROVAL"

    changed = dict(nsl_event)
    changed["event_id"] = "nsl-event-invalid"
    changed["external_ref"] = "different-request"
    with pytest.raises(ProductPreparationPersistenceError, match="NSL approval"):
        repository.accept_event(changed)


@pytest.mark.parametrize(
    "mutation",
    [
        {"resume_target_kind": "PRODUCT_COORDINATOR"},
        {"result_contract_ref": "contract://other"},
        {"nsl_execution_id": "unexpected"},
    ],
)
def test_generalized_legacy_wait_shape_is_fail_closed(sessions, mutation) -> None:
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)
    with pytest.raises(ProductPreparationPersistenceError):
        repository.register_wait(_legacy_wait(**mutation))


def test_sealed_records_reject_hash_or_authority_drift() -> None:
    wait_binding = _wait_binding()
    wait_binding.pop("binding_hash")
    with pytest.raises(ProductPreparationPersistenceError, match="event type"):
        seal_product_preparation_wait_binding(
            {
                **wait_binding,
                "expected_event_type": "ACCOUNTING_APPROVAL_CHANGED",
            }
        )
    with pytest.raises(ProductPreparationPersistenceError, match="not admitted"):
        seal_product_preparation_event(
            {
                "tenant_id": TENANT,
                "event_id": EVENT_ID,
                "event_type": "UNSUPPORTED",
                "external_ref": "wc://approval/case-6b1a2",
                "event_payload": {},
                "received_at": NOW,
            }
        )


def test_repository_maps_missing_schema_to_retryable_unavailable() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    repository = SqlAlchemyGeneralizedWaitEventRepository(
        sessionmaker(bind=engine, expire_on_commit=False)
    )

    with pytest.raises(ProductPreparationPersistenceError) as exc_info:
        repository.get_wait(tenant_id=TENANT, wait_id=WAIT_ID)

    assert exc_info.value.error_code.endswith("_unavailable")
    assert exc_info.value.retryable is True
    engine.dispose()


def test_getters_return_none_for_unknown_product_records(sessions) -> None:
    checkpoints = SqlAlchemyProductPreparationCheckpointRepository(sessions)
    repository = SqlAlchemyGeneralizedWaitEventRepository(sessions)

    assert checkpoints.latest(
        tenant_id=TENANT,
        agent_execution_id=EXECUTION_ID,
        coordinator_id=COORDINATOR_ID,
        coordinator_version=COORDINATOR_VERSION,
    ) is None
    assert repository.get_wait(tenant_id=TENANT, wait_id=WAIT_ID) is None
    assert repository.get_event(tenant_id=TENANT, event_id=EVENT_ID) is None
    assert repository.load_product_wait_context(
        tenant_id=TENANT, wait_id=WAIT_ID
    ) is None
    assert repository.load_product_event_context(
        tenant_id=TENANT, event_id=EVENT_ID
    ) is None


_SCHEMA = (
    """
    CREATE TABLE ae_product_prep_checkpoint (
        tenant_id TEXT NOT NULL, checkpoint_id TEXT NOT NULL,
        checkpoint_schema_version TEXT NOT NULL, checkpoint_version INTEGER NOT NULL,
        previous_checkpoint_id TEXT, previous_checkpoint_hash TEXT,
        agent_execution_id TEXT NOT NULL, requester_ref TEXT NOT NULL,
        work_intent_id TEXT NOT NULL, work_intent_revision INTEGER NOT NULL,
        work_intent_hash TEXT NOT NULL, agent_context_id TEXT NOT NULL,
        context_generation INTEGER NOT NULL, context_hash TEXT NOT NULL,
        business_context_hash TEXT NOT NULL, capability_id TEXT NOT NULL,
        capability_version TEXT NOT NULL, capability_release_ref TEXT NOT NULL,
        capability_registration_hash TEXT NOT NULL, coordinator_id TEXT NOT NULL,
        coordinator_version TEXT NOT NULL, coordinator_registration_hash TEXT NOT NULL,
        preparation_adapter_source_identity TEXT NOT NULL,
        materializer_source_identity TEXT NOT NULL, stage TEXT NOT NULL,
        stage_kind TEXT NOT NULL, authority_refs TEXT NOT NULL,
        idempotency_key TEXT NOT NULL, correlation_id TEXT NOT NULL,
        causation_id TEXT, checkpoint_projection TEXT NOT NULL,
        checkpoint_hash TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, checkpoint_id),
        UNIQUE (tenant_id, idempotency_key),
        UNIQUE (tenant_id, agent_execution_id, coordinator_id,
                coordinator_version, checkpoint_version)
    )
    """,
    """
    CREATE TABLE ae_wait_registration (
        wait_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
        agent_execution_id TEXT NOT NULL, executable_step_id TEXT,
        wait_type TEXT NOT NULL, external_ref TEXT NOT NULL,
        result_contract_ref TEXT, wait_contract_ref TEXT NOT NULL,
        resume_target_kind TEXT NOT NULL, state TEXT NOT NULL,
        version INTEGER NOT NULL, created_at TEXT NOT NULL, satisfied_at TEXT,
        matched_event_id TEXT, resume_runtime_job_id TEXT, updated_at TEXT,
        nsl_execution_id TEXT, business_operation_id TEXT,
        approval_request_id TEXT, checkpoint_version INTEGER,
        PRIMARY KEY (tenant_id, wait_id),
        UNIQUE (tenant_id, agent_execution_id, external_ref, wait_type)
    )
    """,
    """
    CREATE TABLE ae_product_prep_wait_binding (
        tenant_id TEXT NOT NULL, wait_id TEXT NOT NULL, checkpoint_id TEXT NOT NULL,
        checkpoint_hash TEXT NOT NULL, coordinator_id TEXT NOT NULL,
        coordinator_version TEXT NOT NULL, coordinator_registration_hash TEXT NOT NULL,
        expected_event_type TEXT NOT NULL, authority_kind TEXT NOT NULL,
        authority_ref TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
        work_intent_id TEXT NOT NULL, binding_hash TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY (tenant_id, wait_id)
    )
    """,
    """
    CREATE TABLE ae_external_event_inbox (
        tenant_id TEXT NOT NULL, event_id TEXT NOT NULL, event_family TEXT NOT NULL,
        event_type TEXT NOT NULL, event_semantic_hash TEXT NOT NULL,
        external_ref TEXT NOT NULL, result_id TEXT, result_contract_ref TEXT,
        event_payload TEXT NOT NULL, state TEXT NOT NULL, rejection_reason TEXT,
        received_at TEXT NOT NULL, processed_at TEXT, approval_request_id TEXT,
        approval_work_item_ref TEXT, approval_evidence_ref TEXT,
        evidence_integrity TEXT, nsl_execution_id TEXT, business_operation_id TEXT,
        PRIMARY KEY (tenant_id, event_id)
    )
    """,
    """
    CREATE TABLE ae_product_prep_event_binding (
        tenant_id TEXT NOT NULL, event_id TEXT NOT NULL, wait_id TEXT NOT NULL,
        checkpoint_id TEXT NOT NULL, checkpoint_hash TEXT NOT NULL,
        coordinator_id TEXT NOT NULL, coordinator_version TEXT NOT NULL,
        coordinator_registration_hash TEXT NOT NULL, authority_kind TEXT NOT NULL,
        notification_ref TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
        work_intent_id TEXT NOT NULL, binding_hash TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY (tenant_id, event_id)
    )
    """,
)
