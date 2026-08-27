from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ag_remediation_execution_status_sync_worker_postgres_smoke as smoke
from nex_ag.generation_remediation import GenerationRemediationTaskStore
from nex_cx.remediation_execution import RemediationExecutionStore
from nex_runtime import (
    InMemoryJobQueue,
    InMemoryServiceLogStore,
    InMemoryWorkerHeartbeatStore,
)
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def migration_result(service_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        service_id=service_id,
        profile=smoke.DEFAULT_PROFILE,
        dry_run=False,
        planned=("0377_ag_remediation_execution_status_sync_worker",),
        applied=("0377_ag_remediation_execution_status_sync_worker",),
        skipped=(),
    )


def postgres_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_AG_TEST_DATABASE_URL": (
            "postgresql://nex_ag_user:secret@localhost/nex_ag_test"
        ),
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql://nex_cx_user:secret@localhost/nex_cx_test"
        ),
    }


def ag_task_observations(action_status: str = "COMPLETED") -> dict[str, Any]:
    return {
        "row_count": 1,
        "action_status": action_status,
        "result_ref_id": "cx-worker-repair-run",
        "result_ref_type": "jsonb",
    }


def ag_worker_observations(
    *,
    job_status: str = "SUCCEEDED",
    heartbeat_status: str = "IDLE",
    service_log_row_count: int = 3,
) -> dict[str, Any]:
    return {
        "remediation_action_id": "ag-remediation-status-sync-worker",
        "job_row_count": 1,
        "job_status": job_status,
        "job_attempt_count": 1,
        "job_type": smoke.AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE,
        "job_payload_schema_version": (
            smoke.AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PAYLOAD_SCHEMA_VERSION
        ),
        "heartbeat_row_count": 1,
        "heartbeat_status": heartbeat_status,
        "heartbeat_active_job_id": None,
        "heartbeat_worker_type": smoke.AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_TYPE,
        "service_log_row_count": service_log_row_count,
        "service_log_messages": [
            "Worker completed a job.",
            "Worker claimed a job.",
            "Worker polling started.",
        ],
    }


def cx_observations(execution_status: str = "SUCCEEDED") -> dict[str, Any]:
    return {
        "row_count": 1,
        "execution_status": execution_status,
        "parent_cx_generation_id": "cx-gen-remediation-status-sync-worker",
        "result_ref_id": "cx-worker-repair-run",
        "result_ref_type": "jsonb",
    }


def patch_success_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeEngine, FakeEngine]:
    ag_engine = FakeEngine()
    cx_engine = FakeEngine()
    engines = iter([ag_engine, cx_engine])
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service_id, **kwargs: migration_result(service_id),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda *args, **kwargs: next(engines))
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyGenerationRemediationTaskStore",
        lambda session_factory, **kwargs: GenerationRemediationTaskStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRemediationExecutionStore",
        lambda session_factory, **kwargs: RemediationExecutionStore(),
    )
    monkeypatch.setattr(smoke, "SqlAlchemyJobQueue", lambda session_factory: InMemoryJobQueue())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyWorkerHeartbeatStore",
        lambda session_factory: InMemoryWorkerHeartbeatStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyServiceLogStore",
        lambda session_factory: InMemoryServiceLogStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_ag_db_observations",
        lambda engine, remediation_action_id: ag_task_observations(),
    )
    monkeypatch.setattr(
        smoke,
        "_ag_worker_db_observations",
        lambda engine, remediation_action_id, job_id, worker_id: ag_worker_observations(),
    )
    monkeypatch.setattr(
        smoke,
        "_cx_db_observations",
        lambda engine, remediation_action_id: cx_observations(),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_ag_worker_smoke_rows",
        lambda engine, remediation_action_id, job_id, worker_id, request_id: {
            "service_log_entries": 3,
            "service_worker_heartbeats": 1,
            "service_jobs": 1,
            "ag_generation_remediation_tasks": 1,
        },
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_cx_smoke_rows",
        lambda engine, remediation_action_id: {"cx_remediation_execution_attempts": 1},
    )
    return ag_engine, cx_engine


def test_status_sync_worker_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ag_remediation_execution_status_sync_worker_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ag_remediation_execution_status_sync_worker_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_status_sync_worker_postgres_smoke_rejects_dev_profile() -> None:
    evidence = smoke.run_ag_remediation_execution_status_sync_worker_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_status_sync_worker_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_remediation_execution_status_sync_worker_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AG_TEST_DATABASE_URL" in evidence["detail"]


def test_status_sync_worker_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ag_remediation_execution_status_sync_worker_postgres_smoke(
        postgres_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert evidence["detail"] == "bad migration"


def test_status_sync_worker_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ag_engine, cx_engine = patch_success_runtime(monkeypatch)

    evidence = smoke.run_ag_remediation_execution_status_sync_worker_postgres_smoke(
        postgres_env()
    )

    assert evidence["status"] == "PASS"
    assert evidence["worker"]["status"] == "SUCCEEDED"
    assert evidence["worker"]["sync_status"] == "UPDATED"
    assert evidence["worker"]["final_action_status"] == "COMPLETED"
    assert evidence["cx_status_client"]["call_count"] == 1
    assert evidence["cleanup"][smoke.AG_SERVICE_ID]["service_jobs"] == 1
    assert evidence["cleanup"][smoke.AG_SERVICE_ID]["service_log_entries"] == 3
    assert evidence["cleanup"][smoke.CX_SERVICE_ID][
        "cx_remediation_execution_attempts"
    ] == 1
    assert ag_engine.disposed is True
    assert cx_engine.disposed is True
    assert "secret" not in str(evidence)
    assert smoke.summary_line(evidence).startswith(
        "ag_remediation_execution_status_sync_worker_postgres_smoke=pass"
    )


def test_status_sync_worker_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_success_runtime(monkeypatch)
    monkeypatch.setattr(
        smoke,
        "_ag_worker_db_observations",
        lambda engine, remediation_action_id, job_id, worker_id: ag_worker_observations(
            job_status="RUNNING"
        ),
    )

    evidence = smoke.run_ag_remediation_execution_status_sync_worker_postgres_smoke(
        postgres_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_status_sync_worker_postgres_smoke_disposes_first_engine_when_second_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ag_engine = FakeEngine()
    calls = iter([ag_engine, RuntimeError("cx engine failed")])

    def build_engine(*args: object, **kwargs: object) -> FakeEngine:
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(smoke, "build_engine", build_engine)
    monkeypatch.setattr(
        smoke,
        "_cleanup_ag_worker_smoke_rows",
        lambda engine, remediation_action_id, job_id, worker_id, request_id: {
            "service_log_entries": 0,
            "service_worker_heartbeats": 0,
            "service_jobs": 0,
            "ag_generation_remediation_tasks": 0,
        },
    )

    with pytest.raises(RuntimeError, match="cx engine failed"):
        smoke._execute_status_sync_worker_smoke(
            env=postgres_env(),
            ag_database_env="NEX_AG_TEST_DATABASE_URL",
            ag_database_url="postgresql://ag",
            cx_database_env="NEX_CX_TEST_DATABASE_URL",
            cx_database_url="postgresql://cx",
        )

    assert ag_engine.disposed is True


def test_status_sync_worker_postgres_smoke_handles_first_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ag engine failed")),
    )

    with pytest.raises(RuntimeError, match="ag engine failed"):
        smoke._execute_status_sync_worker_smoke(
            env=postgres_env(),
            ag_database_env="NEX_AG_TEST_DATABASE_URL",
            ag_database_url="postgresql://ag",
            cx_database_env="NEX_CX_TEST_DATABASE_URL",
            cx_database_url="postgresql://cx",
        )


def test_status_sync_worker_postgres_smoke_redaction_guard_rejects_raw_urls() -> None:
    env = postgres_env()

    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(env["NEX_AG_TEST_DATABASE_URL"], env)


def test_ag_worker_db_observations_handle_missing_rows() -> None:
    class FakeResult:
        def mappings(self) -> "FakeResult":
            return self

        def first(self) -> None:
            return None

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, *args: object, **kwargs: object) -> FakeResult:
            return FakeResult()

    class FakeObservationEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

    assert smoke._ag_worker_db_observations(
        FakeObservationEngine(),
        remediation_action_id="missing",
        job_id="missing-job",
        worker_id="missing-worker",
    ) == {
        "remediation_action_id": "missing",
        "job_row_count": 0,
        "job_status": None,
        "job_attempt_count": None,
        "job_type": None,
        "job_payload_schema_version": None,
        "heartbeat_row_count": 0,
        "heartbeat_status": None,
        "heartbeat_active_job_id": None,
        "heartbeat_worker_type": None,
        "service_log_row_count": 0,
        "service_log_messages": [],
    }


def test_ag_worker_cleanup_helpers() -> None:
    class FakeDeleteResult:
        rowcount = 1

    class FakeBegin:
        def __enter__(self) -> "FakeBegin":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, *args: object, **kwargs: object) -> FakeDeleteResult:
            return FakeDeleteResult()

    class FakeCleanupEngine:
        def begin(self) -> FakeBegin:
            return FakeBegin()

    assert smoke._cleanup_ag_worker_smoke_rows(
        FakeCleanupEngine(),
        remediation_action_id="action-id",
        job_id="job-id",
        worker_id="worker-id",
        request_id="request-id",
    ) == {
        "service_log_entries": 1,
        "service_worker_heartbeats": 1,
        "service_jobs": 1,
        "ag_generation_remediation_tasks": 1,
    }
    assert smoke._rowcount(SimpleNamespace(rowcount=-1)) == 0


def test_ag_worker_cleanup_ignores_sqlalchemy_errors() -> None:
    class ExplodingBegin:
        def __enter__(self) -> "ExplodingBegin":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, *args: object, **kwargs: object) -> None:
            raise SQLAlchemyError("delete failed")

    class ExplodingEngine:
        def begin(self) -> ExplodingBegin:
            return ExplodingBegin()

    assert smoke._cleanup_ag_worker_smoke_rows(
        ExplodingEngine(),
        remediation_action_id="action-id",
        job_id="job-id",
        worker_id="worker-id",
        request_id="request-id",
    ) == {
        "service_log_entries": 0,
        "service_worker_heartbeats": 0,
        "service_jobs": 0,
        "ag_generation_remediation_tasks": 0,
    }


def test_ag_worker_postgres_smoke_main_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_ag_remediation_execution_status_sync_worker_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "service_id": smoke.AG_SERVICE_ID,
            "failure_code": "forced",
        },
    )

    assert smoke.main(["--summary"]) == 1
    assert "ag_remediation_execution_status_sync_worker_postgres_smoke=fail" in (
        capsys.readouterr().out
    )
