from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0559@127.0.0.1:5432/"
            "nex_ae_test"
        ),
    }


def test_ae_ag_daemon_run_read_model_postgres_smoke_skips_by_default() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke(
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
        "ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke="
        f"skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_ag_daemon_run_read_model_postgres_smoke_rejects_non_test_profile() -> (
    None
):
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke(
            {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke="
        "fail service=nex-ae-api ag_service=nex-ag reason=profile_not_allowed"
    )


def test_ae_ag_daemon_run_read_model_postgres_smoke_requires_database_url() -> None:
    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke(
            {smoke.SMOKE_ENV: "1"}
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_ag_daemon_run_read_model_postgres_smoke_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError("bad secret-0559")
        ),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0559" not in evidence["detail"]


def test_ae_ag_daemon_run_read_model_postgres_smoke_passes_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=("0557_ae_artifact_retention_scheduler_daemon_runs",),
            applied=(),
            skipped=("0557_ae_artifact_retention_scheduler_daemon_runs",),
        ),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke(
            smoke_env()
        )
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["daemon_run"]["result_status"] == "SUCCEEDED"
    assert evidence["daemon_run"]["run_status"] == "SUCCEEDED"
    assert evidence["daemon_run"]["job_enqueued"] is True
    assert evidence["daemon_run"]["worker_executed"] is False
    assert evidence["db"] == {
        "direct_run_records": 1,
        "direct_collection_schema_version": (
            smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_COLLECTION_SCHEMA_VERSION
        ),
        "direct_detail_schema_version": (
            smoke.AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_DETAIL_SCHEMA_VERSION
        ),
        "lifecycle_event_count": 2,
        "lifecycle_event_types": ["RUN_STARTED", "RUN_COMPLETED"],
        "job_rows": 2,
        "job_statuses": ["QUEUED", "QUEUED"],
        "lease_status": "RELEASED",
        "lease_rows": 1,
    }
    assert evidence["routes"] == {
        "ae_run_collection_statuses": [200],
        "ae_run_detail_statuses": [200],
        "ag_run_collection_status": 200,
        "ag_run_detail_status": 200,
    }
    assert evidence["ag_run_collection"]["projection_schema_version"] == (
        smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_COLLECTION_PROJECTION_SCHEMA_VERSION
    )
    assert evidence["ag_run_collection"]["projection_status"] == "READY"
    assert evidence["ag_run_collection"]["count"] == 1
    assert evidence["ag_run_collection"]["summary"]["succeeded_count"] == 1
    assert evidence["ag_run_collection"]["source_status"]["source_kind"] == (
        "ae_test_client"
    )
    assert evidence["ag_run_collection"]["operator_guidance"][
        "ag_direct_database_write_allowed"
    ] is False
    assert evidence["ag_run_detail"]["projection_schema_version"] == (
        smoke.AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert evidence["ag_run_detail"]["projection_status"] == "READY"
    assert evidence["ag_run_detail"]["daemon_run_record_id"] == (
        evidence["daemon_run"]["daemon_run_record_id"]
    )
    assert evidence["ag_run_detail"]["lifecycle_event_count"] == 2
    assert evidence["ag_run_detail"]["source_status"]["run_detail_loaded"] is True
    assert all(evidence["checks"].values())
    assert evidence["cleanup"] == {
        "job_rows": 2,
        "worker_heartbeat_rows": 0,
        "daemon_heartbeat_rows": 0,
        "lease_rows": 1,
        "daemon_lifecycle_events": 2,
        "daemon_run_records": 1,
    }
    assert evidence["live_db"] is True
    assert smoke.summary_line(evidence).startswith(
        "ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke="
        "pass service=nex-ae-api ag_service=nex-ag"
    )
    assert "secret-0559" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "storage_ref" not in serialized


def test_ae_ag_daemon_run_read_model_postgres_smoke_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke.bounded_pg,
        "_bounded_loop_job_observations",
        lambda *args, **kwargs: {
            "row_count": 1,
            "job_ids": ["job-0559"],
            "statuses": ["FAILED"],
            "attempt_counts": [1],
            "idempotency_keys": ["idempotency-0559"],
            "payload_command_statuses": ["READY"],
        },
    )

    with pytest.raises(RuntimeError, match="db_job_and_lease_written"):
        smoke._execute_ae_ag_artifact_retention_scheduler_daemon_run_read_model_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_daemon_run_read_model_postgres_smoke_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_ag_artifact_retention_scheduler_daemon_run_read_model_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = (
        smoke.run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke(
            smoke_env()
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_ae_ag_daemon_run_read_model_postgres_smoke_helpers_and_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"

    assert smoke._ae_auth_headers(
        request_id="request-0559",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )["Authorization"].startswith("Bearer ")
    assert smoke._ag_auth_headers(
        request_id="request-0559",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )["Authorization"].startswith("Bearer ")
    assert smoke._database_url_password(
        "postgresql+psycopg://user:sensitive-pass@127.0.0.1:5432/nex_ae_test"
    ) == "sensitive-pass"
    assert smoke._database_url_password(None) is None
    assert smoke._database_url_password("postgresql://user@127.0.0.1/db") is None
    assert smoke._database_url_password("http://[::1") is None
    assert smoke._mapping_value({"ok": True}) == {"ok": True}
    assert smoke._mapping_value([]) == {}
    assert smoke._metadata_only({"safe": "ok"}, forbidden_fragments=["secret"])
    assert not smoke._metadata_only(
        {"leak": "content_base64"},
        forbidden_fragments=["content_base64"],
    )
    assert "secret-0559" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_ARTIFACT_STORAGE_ROOT"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("password=secret-0559", env)
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/ae/artifacts", {})

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )
    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke="
        "skipped"
    ) in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "service_id": "nex-ae-api",
            "ag_service_id": "nex-ag",
            "failure_code": "execution_failed",
        },
    )
    assert smoke.main(["--summary"]) == 1
    assert "reason=execution_failed" in capsys.readouterr().out
