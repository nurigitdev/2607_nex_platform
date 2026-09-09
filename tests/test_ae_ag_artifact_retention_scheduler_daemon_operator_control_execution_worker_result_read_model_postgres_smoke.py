from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0618@127.0.0.1:5432/"
            "nex_ae_test"
        ),
    }


def _passing_migration() -> SimpleNamespace:
    return SimpleNamespace(
        planned=("0596_execution", "0612_result"),
        applied=(),
        skipped=("0596_execution", "0612_result"),
    )


def _passing_observations(
    *,
    states: int = 0,
    transitions: int = 0,
    results: int = 0,
) -> dict[str, Any]:
    scoped = {
        "execution_states": states,
        "execution_transitions": transitions,
        "worker_results": results,
    }
    return {
        "dialect": "sqlite",
        "health_probe": True,
        "tables_present": sorted(smoke.EXPECTED_TABLES),
        "indexes_present": sorted(smoke.EXPECTED_INDEXES),
        "migration_recorded": True,
        "jsonb_columns": {},
        "row_counts": scoped,
        "scoped_row_counts": scoped,
    }


def test_ae_ag_worker_result_read_model_smoke_skips_by_default() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke(
            {}
        )
    )

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_ag_worker_result_read_model_rejects_non_test_profile() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke(
            {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert "AG-to-AE worker-result PostgreSQL smoke" in evidence["detail"]
    assert smoke.summary_line(evidence) == (
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke="
        "fail service=nex-ae-api ag_service=nex-ag reason=profile_not_allowed"
    )


def test_ae_ag_worker_result_read_model_requires_test_database_url() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_ag_worker_result_read_model_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0618")
        ),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0618" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_ae_ag_worker_result_read_model_redacts_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: _passing_migration(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_ag_worker_result_read_model_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("worker-result leaked secret-0618")
        ),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert "secret-0618" not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_ae_ag_worker_result_read_model_passes_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: _passing_migration(),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke(
            smoke_env()
        )
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    summary = smoke.summary_line(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["service_id"] == "nex-ae-api"
    assert evidence["ag_service_id"] == "nex-ag"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["routes"] == {
        "ae_persisted_execution_status": 200,
        "ae_persisted_worker_result_status": 200,
        "ae_worker_result_collection_status": 200,
        "ae_worker_result_detail_status": 200,
        "ae_worker_result_collection_statuses": [200],
        "ae_worker_result_detail_statuses": [200],
        "ag_worker_result_collection_status": 200,
        "ag_worker_result_detail_status": 200,
    }
    assert evidence["persisted"]["stored_table"] == (
        smoke.AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE
    )
    assert evidence["execution"]["execution_status"] == "ADMITTED"
    assert evidence["worker"]["worker_status"] == "SUCCEEDED"
    assert evidence["worker_result_record"]["worker_status"] == "SUCCEEDED"
    assert evidence["worker_result_record"]["hashes_present"] is True
    assert evidence["ae_worker_result_collection"]["schema_version"] == (
        smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_COLLECTION_SCHEMA_VERSION
    )
    assert evidence["ae_worker_result_collection"]["count"] == 1
    assert evidence["ae_worker_result_collection"]["first_item"][
        "hashes_present"
    ] is True
    assert evidence["ae_worker_result_detail"]["schema_version"] == (
        smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_DETAIL_SCHEMA_VERSION
    )
    assert evidence["ae_worker_result_detail"]["record"]["hashes_present"] is True
    assert evidence["ag_worker_result_collection"]["projection_schema_version"] == (
        smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert evidence["ag_worker_result_collection"]["projection_status"] == "READY"
    assert evidence["ag_worker_result_collection"]["count"] == 1
    assert evidence["ag_worker_result_collection"]["summary"]["succeeded_count"] == 1
    assert evidence["ag_worker_result_collection"]["source_status"][
        "worker_result_collection_loaded"
    ] is True
    assert evidence["ag_worker_result_detail"]["projection_schema_version"] == (
        smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert evidence["ag_worker_result_detail"]["projection_status"] == "READY"
    assert evidence["ag_worker_result_detail"]["summary"]["worker_status"] == (
        "SUCCEEDED"
    )
    assert evidence["ag_worker_result_detail"]["source_status"][
        "worker_result_detail_loaded"
    ] is True
    assert evidence["ag_worker_result_detail"]["operator_guidance"][
        "ag_direct_database_write_allowed"
    ] is False
    assert evidence["db_observations"]["after"]["scoped_row_counts"] == {
        "execution_states": 1,
        "execution_transitions": 0,
        "worker_results": 1,
    }
    assert evidence["cleanup"] == {
        "operator_control_execution_worker_results": 1,
        "execution_state_transitions": 0,
        "execution_states": 1,
    }
    assert evidence["post_cleanup"]["scoped_row_counts"] == {
        "execution_states": 0,
        "execution_transitions": 0,
        "worker_results": 0,
    }
    assert all(evidence["checks"].values())
    assert evidence["live_db"] is True
    assert summary.startswith(
        "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke="
        "pass service=nex-ae-api ag_service=nex-ag"
    )
    assert "results=1" in summary
    assert "ae_read=200/200" in summary
    assert "ag_read=200/200" in summary
    assert "cleanup_results=1" in summary
    assert "secret-0618" not in serialized
    assert "slice-0618-worker-result-" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "ed6@c496em" not in serialized


def test_ae_ag_worker_result_read_model_failed_checks_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        [
            _passing_observations(),
            _passing_observations(states=1, transitions=0, results=0),
        ]
    )
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: next(observations),
    )

    with pytest.raises(RuntimeError, match="scoped_rows_written"):
        smoke._execute_ae_ag_worker_result_read_model_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_worker_result_read_model_cleanup_verification_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = iter(
        [
            _passing_observations(),
            _passing_observations(states=1, transitions=0, results=1),
            _passing_observations(states=0, transitions=0, results=1),
        ]
    )
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: next(observations),
    )

    with pytest.raises(RuntimeError, match="cleanup verification failed"):
        smoke._execute_ae_ag_worker_result_read_model_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_worker_result_read_model_bridge_error_payload() -> None:
    class ErrorResponse:
        status_code = 503
        content = b"{}"

        def json(self) -> dict[str, str]:
            return {
                "error_code": "ae.worker_result_unavailable",
                "detail": "worker result read model unavailable",
            }

    class ListJsonResponse:
        status_code = 200
        content = b"[]"

        def json(self) -> list[str]:
            return ["not", "a", "dict"]

    class EmptyResponse:
        status_code = 200
        content = b""

    with pytest.raises(smoke.AeArtifactOperationsError) as exc_info:
        smoke.AeTestClientDaemonOperatorControlExecutionWorkerResultReadModelClient._json_or_error(
            ErrorResponse()
        )

    assert exc_info.value.error_code == "ae.worker_result_unavailable"
    assert (
        smoke.AeTestClientDaemonOperatorControlExecutionWorkerResultReadModelClient._json_or_error(
            ListJsonResponse()
        )
        == {}
    )
    assert (
        smoke.AeTestClientDaemonOperatorControlExecutionWorkerResultReadModelClient._json_or_error(
            EmptyResponse()
        )
        == {}
    )


def test_ae_ag_worker_result_read_model_helpers_and_redaction() -> None:
    env = smoke_env()

    assert smoke._json_payload(object()) == {}
    assert smoke._mapping_value(None) == {}
    assert smoke._list_value(None) == []
    assert smoke._text_or_none("  ") is None
    assert smoke._append_optional_text([], "") is None
    assert smoke._ae_collection_evidence({})["first_item"]["hashes_present"] is False
    assert smoke._ag_detail_evidence({})["summary"]["worker_status"] is None
    assert smoke._metadata_only({"safe": True}, forbidden_fragments=["secret"])
    assert smoke._worker_result_query_params(
        scheduler_id="scheduler",
        action=None,
        worker_status="SUCCEEDED",
        operator_control_execution_state_id=None,
        operator_control_execution_request_id="request",
        limit=None,
    ) == {
        "scheduler_id": "scheduler",
        "worker_status": "SUCCEEDED",
        "operator_control_execution_request_id": "request",
    }
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("leaked secret-0618", env)
    with pytest.raises(ValueError, match="private operator-control request data"):
        smoke.assert_smoke_evidence_redacted("slice-0618-worker-result-leak", env)
    with pytest.raises(ValueError, match="private operator-control request data"):
        smoke.assert_smoke_evidence_redacted(
            "body-slice-0618-worker-result-leak",
            env,
        )


def test_ae_ag_worker_result_read_model_main_outputs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert f"skipped reason={smoke.SMOKE_ENV}" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke",
        lambda: smoke._failure(
            "configuration_invalid",
            "missing NEX_AE_TEST_DATABASE_URL",
            profile=smoke.DEFAULT_PROFILE,
            env={},
        ),
    )

    assert smoke.main([]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FAIL"
    assert payload["failure_code"] == "configuration_invalid"
