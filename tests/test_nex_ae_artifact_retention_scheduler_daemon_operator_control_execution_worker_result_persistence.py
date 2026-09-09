from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

from nex_ae_api.artifact_retention_scheduler_daemon import (
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_RECORD_SCHEMA_VERSION,
    AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE,
    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore,
    SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore,
    build_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record,
    operator_control_execution_worker_result_record_summary_line,
    summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record,
    validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record,
)
from nex_ae_api.artifacts import ArtifactHandoffError, sha256_json
from test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_adapter import (
    FailingSupervisorAdapter,
    run_worker,
)
from test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_contract import (
    worker_command,
)
from test_nex_ae_artifacts import sqlite_artifact_session_factory


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    ROOT
    / "database"
    / "nex-ae-api"
    / "migrations"
    / "0612_ae_worker_result_persistence.sql"
)


def assert_safe_worker_result_record(record: dict[str, object]) -> None:
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)

    assert "operator_control_execution_worker_command\": {" not in serialized
    assert "operator_control_execution_worker_transition_plan\": {" not in serialized
    assert "supervisor_results\": [" not in serialized
    assert "postgresql://" not in serialized
    assert "postgresql+psycopg://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "nuri1004" not in serialized
    assert "ed6@c496em" not in serialized


def worker_result_record(action: str = "start_daemon") -> dict[str, object]:
    result = run_worker(worker_command(action))
    return build_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record(
        result
    )


def test_worker_result_record_projects_safe_summary_and_hashes() -> None:
    result = run_worker()
    record = (
        build_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record(
            result
        )
    )
    summary = (
        summarize_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record(
            record
        )
    )

    assert record[
        "operator_control_execution_worker_result_record_schema_version"
    ] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_RECORD_SCHEMA_VERSION
    )
    assert AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE == (
        "ae_op_exec_worker_results"
    )
    assert len(AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE) == 25
    assert record["worker_status"] == "SUCCEEDED"
    assert record["transition_terminal_status"] == "SUCCEEDED"
    assert record["status_path"] == ["ADMITTED", "EXECUTING", "SUCCEEDED"]
    assert record["supervisor_result_count"] == 1
    assert record["supervisor_result_statuses"] == ["BLOCKED"]
    assert record["supervisor_actions"] == ["start_daemon"]
    assert record["worker_result_hash"] == sha256_json(result)
    assert record["supervisor_results_hash"] == sha256_json(
        result["supervisor_results"]
    )
    assert record["guardrails"]["safe_summary_only"] is True
    assert record["guardrails"]["stores_full_worker_result_payload"] is False
    assert record["metadata"]["database_write_performed"] is True
    assert record["metadata"]["stores_full_supervisor_result_payload"] is False
    assert summary["safe_for_ag_projection"] is True
    assert summary["database_write_performed"] is True
    assert "status=SUCCEEDED" in (
        operator_control_execution_worker_result_record_summary_line(record)
    )
    assert (
        validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record(
            record
        )
        == record
    )
    assert_safe_worker_result_record(record)


def test_worker_result_store_round_trips_records_and_filters() -> None:
    session_factory = sqlite_artifact_session_factory()
    execution_store = SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore(
        session_factory
    )
    result_store = (
        SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore(
            session_factory
        )
    )
    result = run_worker()
    state = result["operator_control_execution_worker_command"][
        "operator_control_execution_worker_plan"
    ]["operator_control_execution_state"]

    execution_store.record_execution_state(state)
    result_store.ensure_schema()
    result_store.ensure_available()
    record = result_store.record_worker_result(result)
    replay = result_store.record_worker_result(result)

    assert replay == record
    assert result_store.get_worker_result(
        record["operator_control_execution_worker_result_id"]
    ) == record
    assert result_store.list_worker_results(
        scheduler_id=record["scheduler_id"],
        action="START_DAEMON",
        worker_status="succeeded",
        operator_control_execution_state_id=record[
            "operator_control_execution_state_id"
        ],
        operator_control_execution_request_id=record[
            "operator_control_execution_request_id"
        ],
        limit="1",
    ) == [record]
    assert result_store.list_worker_results(worker_status="failed") == []
    assert result_store.get_worker_result("missing") is None
    assert result_store.delete_worker_result(
        record["operator_control_execution_worker_result_id"]
    ) == {"operator_control_execution_worker_results": 1}
    assert result_store.delete_worker_result(
        record["operator_control_execution_worker_result_id"]
    ) == {"operator_control_execution_worker_results": 0}


def test_worker_result_store_can_filter_failed_results() -> None:
    session_factory = sqlite_artifact_session_factory()
    store = (
        SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore(
            session_factory
        )
    )
    failed = run_worker(adapter=FailingSupervisorAdapter())
    record = store.record_worker_result(failed)

    assert record["worker_status"] == "FAILED"
    assert record["supervisor_result_statuses"] == ["FAILED"]
    assert store.list_worker_results(worker_status="FAILED") == [record]


@pytest.mark.parametrize(
    ("mutate", "detail"),
    (
        (lambda record: [], "object"),
        (
            lambda record: {
                **record,
                "operator_control_execution_worker_result_record_schema_version": (
                    "wrong"
                ),
            },
            "schema",
        ),
        (lambda record: {**record, "service_id": "nex-ag"}, "service"),
        (lambda record: {**record, "action": "launch_daemon"}, "action"),
        (lambda record: {**record, "execution_mode": "real_subprocess"}, "mode"),
        (lambda record: {**record, "worker_status": "READY"}, "status"),
        (
            lambda record: {
                **record,
                "transition_terminal_status": "FAILED",
            },
            "terminal status",
        ),
        (lambda record: {**record, "status_path": []}, "status path"),
        (
            lambda record: {
                **record,
                "supervisor_result_count": 2,
            },
            "supervisor scope",
        ),
        (
            lambda record: {
                **record,
                "supervisor_result_statuses": ["WAITING"],
            },
            "result status",
        ),
        (
            lambda record: {
                **record,
                "supervisor_actions": ["restart_daemon"],
            },
            "action",
        ),
        (
            lambda record: {
                **record,
                "supervisor_dispatch_performed": "yes",
            },
            "boolean",
        ),
        (lambda record: {**record, "guardrails": []}, "guardrails"),
        (lambda record: {**record, "metadata": []}, "metadata"),
        (
            lambda record: {
                **record,
                "guardrails": {
                    **record["guardrails"],
                    "database_url_included": True,
                },
            },
            "guardrails",
        ),
        (
            lambda record: {
                **record,
                "metadata": {**record["metadata"], "stored_table": "too_long"},
            },
            "metadata",
        ),
        (
            lambda record: {
                **record,
                "worker_result_hash": "0" * 63,
            },
            "hash",
        ),
        (lambda record: {**record, "unexpected": True}, "keys"),
    ),
)
def test_worker_result_record_validation_rejects_invalid_payloads(
    mutate,
    detail: str,
) -> None:
    record = worker_result_record()

    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record(
            mutate(record)
        )

    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_result_record_invalid"
    )
    assert detail in exc_info.value.detail


@pytest.mark.parametrize(
    "kwargs",
    (
        {"action": "purge_daemon"},
        {"worker_status": "READY"},
        {"limit": 0},
        {"limit": 101},
        {"limit": "many"},
    ),
)
def test_worker_result_store_rejects_invalid_filters(kwargs: dict[str, object]) -> None:
    store = (
        SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore(
            sqlite_artifact_session_factory()
        )
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        store.list_worker_results(**kwargs)

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_result_collection_invalid"
    )


@pytest.mark.parametrize(
    "operation",
    (
        "ensure_schema",
        "ensure_available",
        "record_worker_result",
        "get_worker_result",
        "list_worker_results",
        "delete_worker_result",
    ),
)
def test_worker_result_store_maps_database_errors(operation: str) -> None:
    def failing_session_factory() -> object:
        raise SQLAlchemyError("db down")

    store = (
        SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore(
            failing_session_factory
        )
    )
    result = run_worker()
    calls = {
        "ensure_schema": lambda: store.ensure_schema(),
        "ensure_available": lambda: store.ensure_available(),
        "record_worker_result": lambda: store.record_worker_result(result),
        "get_worker_result": lambda: store.get_worker_result("worker-result-0612"),
        "list_worker_results": lambda: store.list_worker_results(limit=1),
        "delete_worker_result": lambda: store.delete_worker_result(
            "worker-result-0612"
        ),
    }

    with pytest.raises(ArtifactHandoffError) as exc_info:
        calls[operation]()

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_operator_control_execution_worker_result_store_unavailable"
    )


def test_worker_result_migration_uses_short_names_and_safe_columns() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ae_op_exec_worker_results" in sql
    assert len(AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE) <= 30
    for name in (
        "idx_ae_op_worker_results_observed",
        "idx_ae_op_worker_results_state",
        "idx_ae_op_worker_results_status",
        "idx_ae_op_worker_results_request",
    ):
        assert name in sql
        assert len(name) < 63
    assert "operator_control_execution_worker_command JSONB" not in sql
    assert "operator_control_execution_worker_transition_plan JSONB" not in sql
    assert "supervisor_results JSONB" not in sql
    assert "worker_result_hash TEXT NOT NULL" in sql
    assert "schema_migrations" in sql
