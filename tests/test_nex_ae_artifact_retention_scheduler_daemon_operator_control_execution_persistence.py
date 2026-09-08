from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_SCHEMA_VERSION,
    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore,
    build_artifact_retention_scheduler_daemon_operator_control_execution_collection,
    build_artifact_retention_scheduler_daemon_operator_control_execution_detail,
    build_artifact_retention_scheduler_daemon_operator_control_execution_state_transition,
)
from nex_ae_api.artifacts import ArtifactHandoffError
from test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_state import (
    execution_state,
)
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def assert_safe_projection(payload: dict[str, object]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert "postgresql://" not in serialized
    assert "postgresql+psycopg://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized
    assert "ed6@c496em" not in serialized
    assert "raw_execution_payload\": true" not in serialized
    assert "raw_artifact_payload\": true" not in serialized


def test_operator_control_execution_store_round_trips_states_and_transitions() -> None:
    session_factory = sqlite_artifact_session_factory()
    store = SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
        session_factory
    )
    state = execution_state(idempotency_key="idem-0596-store-round-trip")
    replay = execution_state(
        idempotency_key="idem-0596-store-round-trip",
        existing_state=state,
        observed_at="2026-09-08T06:31:00Z",
    )
    transition = (
        build_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            operator_control_execution_state=state,
            target_status="EXECUTING",
            decision_reason="operator_transition_to_executing",
            transitioned_at="2026-09-08T06:31:30Z",
        )
    )

    store.ensure_schema()
    store.ensure_available()
    assert store.record_execution_state(state) == state
    assert store.record_execution_state(replay) == replay
    assert store.record_execution_state_transition(transition) == transition
    assert store.get_execution_state(state["operator_control_execution_state_id"]) == state
    assert store.get_execution_state_by_idempotency_key(
        "idem-0596-store-round-trip"
    ) == replay

    listed = store.list_execution_states(
        scheduler_id=state["scheduler_id"],
        action="start_daemon",
        execution_status="ADMITTED",
        idempotency_status="NEW",
        limit="5",
    )
    transitions = store.list_execution_state_transitions(
        state["operator_control_execution_state_id"]
    )

    assert listed == [state]
    assert transitions == [transition]
    assert store.delete_execution_state(state["operator_control_execution_state_id"]) == {
        "execution_state_transitions": 1,
        "execution_states": 1,
    }
    assert store.get_execution_state(state["operator_control_execution_state_id"]) is None
    assert store.list_execution_state_transitions(
        state["operator_control_execution_state_id"]
    ) == []


def test_operator_control_execution_read_models_are_safe_and_filterable() -> None:
    state = execution_state(idempotency_key="idem-0596-read-model")
    transition = (
        build_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            operator_control_execution_state=state,
            target_status="EXECUTING",
            decision_reason="operator_transition_to_executing",
            transitioned_at="2026-09-08T06:31:30Z",
        )
    )

    collection = (
        build_artifact_retention_scheduler_daemon_operator_control_execution_collection(
            [state],
            scheduler_id=state["scheduler_id"],
            action="start_daemon",
            execution_status="ADMITTED",
            idempotency_status="NEW",
            limit=20,
        )
    )
    detail = build_artifact_retention_scheduler_daemon_operator_control_execution_detail(
        execution_state=state,
        transitions=[transition],
    )

    assert collection["operator_control_execution_collection_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_SCHEMA_VERSION
    )
    assert collection["count"] == 1
    assert collection["filter"]["action"] == "start_daemon"
    assert collection["items"][0]["execution_status"] == "ADMITTED"
    assert collection["guardrails"]["ag_direct_database_write_allowed"] is False
    assert detail["operator_control_execution_detail_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_SCHEMA_VERSION
    )
    assert detail["transition_count"] == 1
    assert detail["metadata"]["transition_statuses"] == ["ADMITTED->EXECUTING"]
    assert_safe_projection(collection)
    assert_safe_projection(detail)


@pytest.mark.parametrize(
    "kwargs",
    (
        {"action": "purge_daemon"},
        {"execution_status": "WAITING"},
        {"idempotency_status": "DUPLICATE"},
        {"limit": 0},
        {"limit": 101},
        {"limit": "many"},
    ),
)
def test_operator_control_execution_collection_rejects_invalid_filters(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ArtifactHandoffError) as exc:
        build_artifact_retention_scheduler_daemon_operator_control_execution_collection(
            [],
            **kwargs,
        )

    assert exc.value.status_code == 422
    assert exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_collection_invalid"
    )


def test_operator_control_execution_detail_rejects_cross_scoped_transition() -> None:
    state = execution_state(idempotency_key="idem-0596-detail-state")
    other = execution_state(idempotency_key="idem-0596-detail-other")
    transition = (
        build_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            operator_control_execution_state=other,
            target_status="EXECUTING",
            decision_reason="operator_transition_to_executing",
            transitioned_at="2026-09-08T06:31:30Z",
        )
    )

    with pytest.raises(ArtifactHandoffError) as exc:
        build_artifact_retention_scheduler_daemon_operator_control_execution_detail(
            execution_state=state,
            transitions=[transition],
        )

    assert exc.value.status_code == 422
    assert exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_detail_invalid"
    )


def test_operator_control_execution_store_detects_state_hash_mismatch() -> None:
    session_factory = sqlite_artifact_session_factory()
    store = SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
        session_factory
    )
    state = execution_state(idempotency_key="idem-0596-state-hash")
    store.record_execution_state(state)

    with session_factory() as session:
        session.execute(
            text(
                """
                UPDATE ae_daemon_operator_control_execution_states
                SET execution_state_hash = :execution_state_hash
                WHERE operator_control_execution_state_id =
                      :operator_control_execution_state_id
                """
            ),
            {
                "execution_state_hash": "0" * 64,
                "operator_control_execution_state_id": state[
                    "operator_control_execution_state_id"
                ],
            },
        )
        session.commit()

    with pytest.raises(ArtifactHandoffError) as exc:
        store.get_execution_state(state["operator_control_execution_state_id"])

    assert exc.value.status_code == 422
    assert exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_invalid"
    )


def test_operator_control_execution_store_detects_transition_hash_mismatch() -> None:
    session_factory = sqlite_artifact_session_factory()
    store = SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
        session_factory
    )
    state = execution_state(idempotency_key="idem-0596-transition-hash")
    transition = (
        build_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            operator_control_execution_state=state,
            target_status="EXECUTING",
            decision_reason="operator_transition_to_executing",
            transitioned_at="2026-09-08T06:31:30Z",
        )
    )
    store.record_execution_state(state)
    store.record_execution_state_transition(transition)

    with session_factory() as session:
        session.execute(
            text(
                """
                UPDATE ae_daemon_operator_control_execution_transitions
                SET transition_hash = :transition_hash
                WHERE operator_control_execution_state_transition_id =
                      :operator_control_execution_state_transition_id
                """
            ),
            {
                "transition_hash": "f" * 64,
                "operator_control_execution_state_transition_id": transition[
                    "operator_control_execution_state_transition_id"
                ],
            },
        )
        session.commit()

    with pytest.raises(ArtifactHandoffError) as exc:
        store.list_execution_state_transitions(
            state["operator_control_execution_state_id"]
        )

    assert exc.value.status_code == 422
    assert exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_state_transition_invalid"
    )


@pytest.mark.parametrize(
    "operation",
    (
        "ensure_schema",
        "ensure_available",
        "record_execution_state",
        "record_execution_state_transition",
        "get_execution_state",
        "get_execution_state_by_idempotency_key",
        "list_execution_states",
        "list_execution_state_transitions",
        "delete_execution_state",
    ),
)
def test_operator_control_execution_store_maps_database_errors(
    operation: str,
) -> None:
    def failing_session_factory() -> object:
        raise SQLAlchemyError("db down")

    store = SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
        failing_session_factory
    )
    state = execution_state(idempotency_key=f"idem-0596-unavailable-{operation}")
    transition = (
        build_artifact_retention_scheduler_daemon_operator_control_execution_state_transition(
            operator_control_execution_state=state,
            target_status="EXECUTING",
            decision_reason="operator_transition_to_executing",
            transitioned_at="2026-09-08T06:31:30Z",
        )
    )
    calls = {
        "ensure_schema": lambda: store.ensure_schema(),
        "ensure_available": lambda: store.ensure_available(),
        "record_execution_state": lambda: store.record_execution_state(state),
        "record_execution_state_transition": lambda: (
            store.record_execution_state_transition(transition)
        ),
        "get_execution_state": lambda: store.get_execution_state(
            state["operator_control_execution_state_id"]
        ),
        "get_execution_state_by_idempotency_key": lambda: (
            store.get_execution_state_by_idempotency_key(state["idempotency_key"])
        ),
        "list_execution_states": lambda: store.list_execution_states(limit=1),
        "list_execution_state_transitions": lambda: (
            store.list_execution_state_transitions(
                state["operator_control_execution_state_id"]
            )
        ),
        "delete_execution_state": lambda: store.delete_execution_state(
            state["operator_control_execution_state_id"]
        ),
    }

    with pytest.raises(ArtifactHandoffError) as exc:
        calls[operation]()

    assert exc.value.status_code == 503
    assert exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_store_unavailable"
    )
