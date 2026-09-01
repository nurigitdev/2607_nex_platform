from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_artifact_retention_scheduler_tick_postgres_smoke as smoke
from run_migrations import MigrationError
from test_nex_ae_artifacts import sqlite_artifact_session_factory


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0505@127.0.0.1:5432/"
            "nex_ae_test"
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


def test_ae_artifact_retention_scheduler_tick_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_artifact_retention_scheduler_tick_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
    }
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduler_tick_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ae_artifact_retention_scheduler_tick_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_artifact_retention_scheduler_tick_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_artifact_retention_scheduler_tick_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_ae_artifact_retention_scheduler_tick_postgres_smoke_reports_missing_database_url() -> None:
    evidence = smoke.run_ae_artifact_retention_scheduler_tick_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_ae_artifact_retention_scheduler_tick_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_artifact_retention_scheduler_tick_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "secret-0505" not in evidence["detail"]


def test_ae_artifact_retention_scheduler_tick_postgres_smoke_passes_with_sqlite_harness(
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

    evidence = smoke.run_ae_artifact_retention_scheduler_tick_postgres_smoke(
        smoke_env()
    )
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["batch_plan"] == {
        "plan_status": "READY",
        "scheduler_status": "DISABLED",
        "candidate_count": 2,
        "selected_count": 1,
        "selected_artifact_ids": evidence["batch_plan"]["selected_artifact_ids"],
    }
    assert evidence["scheduler_tick"]["tick_schema_version"] == (
        smoke.AE_ARTIFACT_RETENTION_SCHEDULER_TICK_PLAN_SCHEMA_VERSION
    )
    assert evidence["scheduler_tick"]["tick_enqueue_schema_version"] == (
        smoke.AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ENQUEUE_RESULT_SCHEMA_VERSION
    )
    assert evidence["scheduler_tick"]["tick_status"] == "READY"
    assert evidence["scheduler_tick"]["skip_reason"] is None
    assert evidence["scheduler_tick"]["in_batch_window"] is True
    assert evidence["scheduler_tick"]["enqueue_status"] == "ENQUEUED"
    assert evidence["scheduler_tick"]["job_enqueued"] is True
    assert evidence["scheduler_tick"]["admission_performed"] is True
    assert evidence["scheduler_tick"]["duplicate_job_id"] == evidence["job"]["job_id"]
    assert evidence["job"]["job_type"] == smoke.AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE
    assert evidence["job"]["status"] == "QUEUED"
    assert evidence["job"]["attempt_count"] == 0
    assert evidence["job"]["payload_trigger_type"] == "scheduler_tick"
    assert evidence["job"]["payload_command_status"] == "READY"
    assert evidence["scheduled_jobs"] == {
        "schema_version": smoke.AE_ARTIFACT_RETENTION_SCHEDULED_JOB_COLLECTION_SCHEMA_VERSION,
        "count": 1,
        "queued_count": 1,
        "job_ids": [evidence["job"]["job_id"]],
    }
    assert evidence["db_before"] == good_observations()
    assert evidence["db_after_enqueue"] == good_observations()
    assert evidence["materialized_file_count"] == {
        "before": 6,
        "after_enqueue": 6,
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
        "ae_artifact_retention_scheduler_tick_postgres_smoke=pass "
        "service=nex-ae-api"
    )
    assert "secret-0505" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "storage_ref" not in serialized


def test_ae_artifact_retention_scheduler_tick_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)
    monkeypatch.setattr(smoke.candidate_pg, "_count_files", lambda _root: 0)

    with pytest.raises(RuntimeError, match="storage_files_retained"):
        smoke._execute_ae_artifact_retention_scheduler_tick_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_scheduler_tick_smoke_reports_missing_scheduled_enqueue_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sqlite_artifact_session_factory().kw["bind"]
    monkeypatch.setattr(smoke, "build_engine", lambda _database_url: engine)

    def fake_enqueue(*args, **kwargs) -> dict[str, object]:
        return {
            "artifact_retention_scheduler_tick_enqueue_result_schema_version": (
                smoke.AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ENQUEUE_RESULT_SCHEMA_VERSION
            ),
            "enqueue_status": "ENQUEUED",
            "job_enqueued": True,
            "admission_performed": True,
            "queue_admission": {
                "job_enqueued": True,
                "scheduler_daemon_started": False,
                "worker_execution_performed": False,
                "physical_delete_automation_enabled": False,
            },
            "scheduled_job_enqueue_result": None,
        }

    monkeypatch.setattr(
        smoke,
        "enqueue_artifact_retention_scheduler_tick_job",
        fake_enqueue,
    )

    with pytest.raises(RuntimeError, match="scheduled_job_enqueue_result"):
        smoke._execute_ae_artifact_retention_scheduler_tick_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_scheduler_tick_postgres_smoke_wraps_execute_value_error(
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
        smoke._execute_ae_artifact_retention_scheduler_tick_smoke(
            database_url=smoke_env()["NEX_AE_TEST_DATABASE_URL"],
            database_env="NEX_AE_TEST_DATABASE_URL",
        )


def test_ae_artifact_retention_scheduler_tick_postgres_smoke_reports_execution_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(planned=(), applied=(), skipped=()),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_artifact_retention_scheduler_tick_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )

    evidence = smoke.run_ae_artifact_retention_scheduler_tick_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_ae_artifact_retention_scheduler_tick_postgres_smoke_helpers_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = smoke_env()
    env["NEX_AE_ARTIFACT_STORAGE_ROOT"] = "/data/nex-platform/private"

    assert smoke._database_url_password(
        "postgresql+psycopg://user:sensitive-pass@127.0.0.1:5432/nex_ae_test"
    ) == "sensitive-pass"
    assert smoke._database_url_password(None) is None
    assert smoke._database_url_password("postgresql://user@127.0.0.1/db") is None
    assert smoke._database_url_password("http://[::1") is None
    assert smoke._metadata_only({"safe": "ok"}, forbidden_fragments=["secret"])
    assert not smoke._metadata_only(
        {"leak": "content_base64"},
        forbidden_fragments=["content_base64"],
    )
    assert smoke._scheduled_job_ids(
        {"items": [{"job_id": "job-001"}, {"ignored": True}, []]}
    ) == ["job-001"]
    assert smoke._scheduled_job_ids({"items": "not-a-list"}) == []
    assert smoke._safe_detail(env["NEX_AE_TEST_DATABASE_URL"], env) == (
        "<redacted:NEX_AE_TEST_DATABASE_URL>"
    )
    checks = smoke._scheduler_tick_checks(
        database_url=env["NEX_AE_TEST_DATABASE_URL"],
        database_env="NEX_AE_TEST_DATABASE_URL",
        storage_root=__import__("pathlib").Path("/tmp/safe-storage"),
        scheduler_config_response=503,
        scheduler_config={},
        plan_response=503,
        batch_plan={},
        tick_plan={},
        enqueue_result={},
        duplicate_result={},
        scheduled_jobs_response=503,
        scheduled_jobs={},
        db_job={},
        before={"artifact_rows": 1},
        after={"artifact_rows": 0},
        materialized_before=0,
        materialized_after=1,
    )
    assert not all(checks.values())
    assert "secret-0505" not in checks
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)
    with pytest.raises(ValueError, match="NEX_AE_ARTIFACT_STORAGE_ROOT"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_ARTIFACT_STORAGE_ROOT"], env)
    with pytest.raises(ValueError, match="database password"):
        smoke.assert_smoke_evidence_redacted("password=secret-0505", env)
    with pytest.raises(ValueError, match="local data path"):
        smoke.assert_smoke_evidence_redacted("/data/nex-platform/ae/artifacts", {})

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_artifact_retention_scheduler_tick_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": "disabled",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ae_artifact_retention_scheduler_tick_postgres_smoke=skipped"
        in capsys.readouterr().out
    )


def test_scheduler_tick_job_observation_handles_missing_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke.worker_pg,
        "_job_observation",
        lambda *args, **kwargs: {"row_count": 0, "status": None},
    )

    observation = smoke._scheduler_tick_job_observation(
        object(),
        job_id="missing-job",
        idempotency_key="missing-key",
    )

    assert observation["row_count"] == 0
    assert observation["payload_trigger_type"] is None
    assert observation["payload_execution_mode"] is None
    assert observation["idempotency_key_matches"] is False


def test_scheduler_tick_job_observation_handles_missing_scheduled_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMappings:
        def one(self) -> dict[str, object]:
            return {
                "trace_id": "trace",
                "request_id": "request",
                "idempotency_key": "expected-key",
                "subject_type": "subject",
                "subject_id": "subject-001",
                "payload": "{}",
            }

    class FakeResult:
        def mappings(self) -> FakeMappings:
            return FakeMappings()

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, *args: object, **kwargs: object) -> FakeResult:
            return FakeResult()

    class FakeEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

    monkeypatch.setattr(
        smoke.worker_pg,
        "_job_observation",
        lambda *args, **kwargs: {
            "row_count": 1,
            "status": "QUEUED",
            "attempt_count": 0,
            "payload_command_status": "READY",
        },
    )

    observation = smoke._scheduler_tick_job_observation(
        FakeEngine(),
        job_id="job-001",
        idempotency_key="expected-key",
    )

    assert observation["payload_trigger_type"] is None
    assert observation["payload_execution_mode"] is None
    assert observation["subject_type"] == "subject"
    assert observation["idempotency_key_matches"] is True
