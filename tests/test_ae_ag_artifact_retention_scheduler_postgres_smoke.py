from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_ag_artifact_retention_scheduler_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0499@127.0.0.1:5432/" "nex_ae_test"
        ),
    }


def good_observations() -> dict[str, int]:
    return {
        "artifact_rows": 3,
        "deleted_rows": 3,
        "candidate_rows": 2,
        "file_rows": 6,
        "link_rows": 12,
    }


def test_ae_ag_artifact_retention_scheduler_postgres_smoke_skips_when_disabled() -> (
    None
):
    evidence = smoke.run_ae_ag_artifact_retention_scheduler_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_ag_artifact_retention_scheduler_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ae_ag_artifact_retention_scheduler_postgres_smoke_rejects_non_test_profile() -> (
    None
):
    evidence = smoke.run_ae_ag_artifact_retention_scheduler_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_ag_artifact_retention_scheduler_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_ag_artifact_retention_scheduler_postgres_smoke_reports_missing_database_url() -> (
    None
):
    evidence = smoke.run_ae_ag_artifact_retention_scheduler_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_ag_artifact_retention_scheduler_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_ag_artifact_retention_scheduler_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0499" not in evidence["detail"]


def test_ae_ag_artifact_retention_scheduler_postgres_smoke_passes_with_sqlite_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=("0083_service_job_queue_foundation",),
            applied=(),
            skipped=("0083_service_job_queue_foundation",),
        ),
    )

    evidence = smoke.run_ae_ag_artifact_retention_scheduler_postgres_smoke(smoke_env())
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["scheduler_config"] == {
        "schema_version": "ae_artifact_retention_scheduler_config.v1",
        "scheduler_status": "DISABLED",
        "job_queue_backend": "SqlAlchemyJobQueue",
        "scheduled_job_route": "/api/v1/artifact-retention/scheduled-jobs",
        "admission_route": "/api/v1/artifact-retention/scheduled-jobs/admission",
    }
    assert evidence["ag_dispatch"] == {
        "projection_schema_version": (
            smoke.AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_DISPATCH_SCHEMA_VERSION
        ),
        "projection_status": "READY",
        "enqueue_status": "ENQUEUED",
        "job_enqueued": True,
        "job_status": "QUEUED",
        "trigger_type": "operator_dispatch",
    }
    assert evidence["ag_scheduled_jobs"] == {
        "projection_schema_version": (
            smoke.AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_JOB_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "READY",
        "count": 1,
        "queued_count": 1,
    }
    assert evidence["ag_automation"] == {
        "projection_schema_version": (
            smoke.AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "READY",
        "safety_status": "OPERATOR_ATTENTION",
        "dispatch_available": True,
        "scheduled_job_count": 1,
        "queued_job_count": 1,
        "history_count": 0,
        "physical_delete_automation_enabled": False,
    }
    assert evidence["db_job"]["row_count"] == 1
    assert (
        evidence["db_job"]["job_type"] == smoke.AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE
    )
    assert evidence["db_job"]["status"] == "QUEUED"
    assert evidence["db_job"]["attempt_count"] == 0
    assert evidence["db_job"]["payload_command_status"] == "READY"
    assert evidence["db_before"] == good_observations()
    assert evidence["db_after_dispatch"] == good_observations()
    assert evidence["materialized_file_count"] == {
        "before": 6,
        "after_dispatch": 6,
    }
    assert all(evidence["checks"].values())
    assert evidence["cleanup"] == {
        "artifacts": 3,
        "handoffs": 3,
        "job_rows": 1,
        "heartbeat_rows": 0,
    }
    assert evidence["live_db"] is True
    assert smoke.summary_line(evidence).startswith(
        "ae_ag_artifact_retention_scheduler_postgres_smoke=pass "
        "service=nex-ae-api ag_service=nex-ag"
    )
    assert "secret-0499" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "storage_ref" not in serialized


def test_ae_ag_artifact_retention_scheduler_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke.candidate_pg, "_count_files", lambda _root: 0)

    with pytest.raises(RuntimeError, match="storage_files_retained"):
        smoke._execute_ae_ag_artifact_retention_scheduler_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_artifact_retention_scheduler_postgres_smoke_wraps_execute_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(
        smoke,
        "build_session_factory",
        lambda _engine: (_ for _ in ()).throw(ValueError("bad session")),
    )

    with pytest.raises(RuntimeError, match="bad session"):
        smoke._execute_ae_ag_artifact_retention_scheduler_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_ag_artifact_retention_scheduler_postgres_smoke_reports_execution_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_ag_artifact_retention_scheduler_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = smoke.run_ae_ag_artifact_retention_scheduler_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_ae_ag_artifact_retention_scheduler_postgres_smoke_helpers_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"

    assert smoke._ag_auth_headers(
        request_id="request-0499",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )["Authorization"].startswith("Bearer ")
    assert (
        smoke._database_url_password(
            "postgresql+psycopg://user:sensitive-pass@127.0.0.1:5432/nex_ae_test"
        )
        == "sensitive-pass"
    )
    assert smoke._database_url_password(None) is None
    assert smoke._database_url_password("postgresql://user@127.0.0.1/db") is None
    assert smoke._database_url_password("http://[::1") is None
    assert smoke._metadata_only({"safe": "ok"}, forbidden_fragments=["secret"])
    assert not smoke._metadata_only(
        {"leak": "storage_ref"},
        forbidden_fragments=["storage_ref"],
    )
    assert "secret-0499" not in smoke._safe_detail(
        env["NEX_AE_TEST_DATABASE_URL"],
        env,
    )
    checks = smoke._scheduler_checks(
        database_url=env["NEX_AE_TEST_DATABASE_URL"],
        database_env="NEX_AE_TEST_DATABASE_URL",
        storage_root=__import__("pathlib").Path("/tmp/safe-storage"),
        scheduler_config_response=503,
        scheduler_config={},
        dispatch_response=503,
        dispatch_projection={},
        scheduled_jobs_response=503,
        scheduled_jobs_projection={},
        automation_response=503,
        automation_projection={},
        db_job={},
        before={"artifact_rows": 1},
        after={"artifact_rows": 0},
        materialized_before=0,
        materialized_after=1,
    )
    assert not all(checks.values())
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="NEX_AE_ARTIFACT_STORAGE_ROOT"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_ARTIFACT_STORAGE_ROOT"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("password=secret-0499", env)
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/ae/artifacts", {})

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_ag_artifact_retention_scheduler_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_ag_artifact_retention_scheduler_postgres_smoke=skipped"
        in capsys.readouterr().out
    )
