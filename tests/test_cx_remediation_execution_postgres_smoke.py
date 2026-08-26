from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_cx_remediation_execution_postgres_smoke as smoke
from nex_cx.remediation_execution import (
    RemediationExecutionError,
    RemediationExecutionStore,
)
from nex_runtime import InMemoryJobQueue
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def migration_result(
    *,
    applied: tuple[str, ...] = ("0355_cx_repair_attempt_lineage_persistence_foundation",),
) -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        profile=smoke.DEFAULT_PROFILE,
        dry_run=False,
        planned=("0083_service_job_queue_foundation", *applied),
        applied=applied,
        skipped=(),
    )


def successful_observations() -> dict[str, Any]:
    return {
        "remediation_execution_attempt": {
            "row_count": 1,
            "execution_status": "SUCCEEDED",
            "attempt_no": 1,
            "repair_cx_generation_id": "repair-id",
            "jsonb_columns": dict(smoke.EXPECTED_EXECUTION_JSONB_COLUMNS),
            "index_names": sorted(smoke.EXPECTED_EXECUTION_INDEXES),
        },
        "service_job": {
            "row_count": 1,
            "status": "SUCCEEDED",
            "job_type": smoke.CX_REMEDIATION_EXECUTION_JOB_TYPE,
            "subject_type": "cx.remediation_execution",
            "subject_id": "action-id",
            "attempt_count": 1,
            "max_attempts": 1,
            "completed_at_present": True,
            "lock_released": True,
            "payload_type": "jsonb",
            "payload_action_id": "action-id",
            "index_names": sorted(smoke.EXPECTED_SERVICE_JOB_INDEXES),
        },
    }


def test_cx_remediation_execution_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_cx_remediation_execution_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "cx_remediation_execution_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_cx_remediation_execution_postgres_smoke_rejects_dev_profile() -> None:
    evidence = smoke.run_cx_remediation_execution_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.SMOKE_PROFILE_ENV: "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert evidence["profile"] == "dev"
    assert smoke.summary_line(evidence) == (
        "cx_remediation_execution_postgres_smoke=fail "
        "service=nex-cx reason=profile_not_allowed"
    )


def test_cx_remediation_execution_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_cx_remediation_execution_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_CX_TEST_DATABASE_URL" in evidence["detail"]


def test_cx_remediation_execution_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_cx_remediation_execution_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert evidence["detail"] == "bad migration"


def test_cx_remediation_execution_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    execution_store = RemediationExecutionStore()
    job_queue = InMemoryJobQueue()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: migration_result(),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRemediationExecutionStore",
        lambda session_factory, **kwargs: execution_store,
    )
    monkeypatch.setattr(smoke, "SqlAlchemyJobQueue", lambda session_factory: job_queue)
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda engine, remediation_action_id, job_id: successful_observations(),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda engine, remediation_action_id, job_id, trace_id, request_id: {
            "service_jobs": 1,
            "cx_remediation_execution_attempts": 1,
        },
    )
    raw_url = "postgresql://nex_cx_user:secret@localhost/nex_cx_test"

    evidence = smoke.run_cx_remediation_execution_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": raw_url,
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_CX_TEST_DATABASE_URL"
    assert evidence["redacted_database_url"] == (
        "postgresql://nex_cx_user:***@localhost/nex_cx_test"
    )
    assert evidence["checks"]["worker_succeeded"] is True
    assert evidence["checks"]["final_job_succeeded"] is True
    assert evidence["checks"]["execution_jsonb_columns"] is True
    assert evidence["cleanup"]["service_jobs"] == 1
    assert fake_engine.disposed is True
    assert raw_url not in str(evidence)
    assert "secret" not in evidence["redacted_database_url"]
    assert smoke.summary_line(evidence).startswith(
        "cx_remediation_execution_postgres_smoke=pass"
    )


def test_cx_remediation_execution_postgres_smoke_reports_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    cleanup_calls: list[str] = []
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: migration_result(applied=()),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())

    class FailingExecutionStore(RemediationExecutionStore):
        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            raise RemediationExecutionError(
                status_code=503,
                error_code="cx.remediation_execution_store_unavailable",
                detail="store down",
                retryable=True,
            )

    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRemediationExecutionStore",
        lambda session_factory, **kwargs: FailingExecutionStore(),
    )
    monkeypatch.setattr(smoke, "SqlAlchemyJobQueue", lambda session_factory: InMemoryJobQueue())

    def fake_cleanup(
        engine: object,
        *,
        remediation_action_id: str,
        job_id: str,
        trace_id: str,
        request_id: str,
    ) -> dict[str, int]:
        cleanup_calls.append(remediation_action_id)
        return {"service_jobs": 0, "cx_remediation_execution_attempts": 0}

    monkeypatch.setattr(smoke, "_cleanup_smoke_rows", fake_cleanup)

    evidence = smoke.run_cx_remediation_execution_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert evidence["detail"] == "RuntimeError"
    assert cleanup_calls
    assert fake_engine.disposed is True


def test_cx_remediation_execution_postgres_smoke_fails_when_saved_row_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: migration_result(),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: FakeEngine())
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())

    class MissingLoadStore(RemediationExecutionStore):
        def get(self, remediation_action_id: str) -> dict[str, Any] | None:
            return None

    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRemediationExecutionStore",
        lambda session_factory, **kwargs: MissingLoadStore(),
    )
    monkeypatch.setattr(smoke, "SqlAlchemyJobQueue", lambda session_factory: InMemoryJobQueue())
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda engine, remediation_action_id, job_id, trace_id, request_id: {
            "service_jobs": 0,
            "cx_remediation_execution_attempts": 1,
        },
    )

    evidence = smoke.run_cx_remediation_execution_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_cx_remediation_execution_postgres_smoke_fails_when_checks_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_observations = successful_observations()
    bad_observations["service_job"]["payload_type"] = "text"
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: migration_result(),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: FakeEngine())
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRemediationExecutionStore",
        lambda session_factory, **kwargs: RemediationExecutionStore(),
    )
    monkeypatch.setattr(smoke, "SqlAlchemyJobQueue", lambda session_factory: InMemoryJobQueue())
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda engine, remediation_action_id, job_id: bad_observations,
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda engine, remediation_action_id, job_id, trace_id, request_id: {
            "service_jobs": 1,
            "cx_remediation_execution_attempts": 1,
        },
    )

    evidence = smoke.run_cx_remediation_execution_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_cx_remediation_execution_smoke_redaction_guard_rejects_raw_url() -> None:
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
            {
                "NEX_CX_TEST_DATABASE_URL": (
                    "postgresql://nex_cx_user:secret@localhost/nex_cx_test"
                )
            },
        )


def test_cx_remediation_execution_observation_helpers_handle_missing_rows() -> None:
    assert smoke._execution_observation(None) == {
        "row_count": 0,
        "execution_status": None,
        "attempt_no": None,
        "repair_cx_generation_id": None,
        "jsonb_columns": {
            "result_ref": None,
            "failure": None,
            "redaction_summary": None,
            "metadata": None,
        },
    }
    assert smoke._service_job_observation(None) == {
        "row_count": 0,
        "status": None,
        "job_type": None,
        "subject_type": None,
        "subject_id": None,
        "attempt_count": None,
        "max_attempts": None,
        "completed_at_present": False,
        "lock_released": False,
        "payload_type": None,
        "payload_action_id": None,
    }


def test_cx_remediation_execution_db_observations_reads_rows() -> None:
    class FakeResult:
        def __init__(self, row: dict[str, Any] | None = None) -> None:
            self.row = row

        def mappings(self) -> "FakeResult":
            return self

        def first(self) -> dict[str, Any] | None:
            return self.row

        def all(self) -> list[dict[str, str]]:
            return [
                {"indexname": "idx_b"},
                {"indexname": "idx_a"},
            ]

    class FakeConnection:
        def __init__(self) -> None:
            self.calls = 0

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, params: object | None = None) -> FakeResult:
            self.calls += 1
            if self.calls == 1:
                return FakeResult(
                    {
                        "row_count": 1,
                        "execution_status": "SUCCEEDED",
                        "attempt_no": 1,
                        "repair_cx_generation_id": "repair-id",
                        "result_ref_type": "jsonb",
                        "failure_type": "jsonb",
                        "redaction_summary_type": "jsonb",
                        "metadata_type": "jsonb",
                    }
                )
            if self.calls == 3:
                return FakeResult(
                    {
                        "row_count": 1,
                        "status": "SUCCEEDED",
                        "job_type": smoke.CX_REMEDIATION_EXECUTION_JOB_TYPE,
                        "subject_type": "cx.remediation_execution",
                        "subject_id": "action-id",
                        "attempt_count": 1,
                        "max_attempts": 1,
                        "completed_at_present": True,
                        "lock_released": True,
                        "payload_type": "jsonb",
                        "payload_action_id": "action-id",
                    }
                )
            return FakeResult()

    class FakeObservationEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

    observations = smoke._db_observations(
        FakeObservationEngine(),
        remediation_action_id="action-id",
        job_id="job-id",
    )

    assert observations["remediation_execution_attempt"]["execution_status"] == "SUCCEEDED"
    assert observations["remediation_execution_attempt"]["index_names"] == [
        "idx_a",
        "idx_b",
    ]
    assert observations["service_job"]["status"] == "SUCCEEDED"
    assert observations["service_job"]["index_names"] == ["idx_a", "idx_b"]


def test_cx_remediation_execution_cleanup_reports_rowcounts() -> None:
    class FakeDeleteResult:
        def __init__(self, rowcount: int) -> None:
            self.rowcount = rowcount

    class FakeBegin:
        def __init__(self) -> None:
            self.calls = 0

        def __enter__(self) -> "FakeBegin":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, *args: object, **kwargs: object) -> FakeDeleteResult:
            self.calls += 1
            return FakeDeleteResult(self.calls)

    class FakeCleanupEngine:
        def begin(self) -> FakeBegin:
            return FakeBegin()

    assert smoke._cleanup_smoke_rows(
        FakeCleanupEngine(),
        remediation_action_id="action-id",
        job_id="job-id",
        trace_id=smoke.TRACE_ID,
        request_id="request-id",
    ) == {
        "service_jobs": 1,
        "cx_remediation_execution_attempts": 2,
    }
    assert smoke._rowcount(SimpleNamespace(rowcount=-1)) == 0


def test_cx_remediation_execution_cleanup_ignores_sqlalchemy_errors() -> None:
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

    assert smoke._cleanup_smoke_rows(
        ExplodingEngine(),
        remediation_action_id="action-id",
        job_id="job-id",
        trace_id=smoke.TRACE_ID,
        request_id="request-id",
    ) == {
        "service_jobs": 0,
        "cx_remediation_execution_attempts": 0,
    }


def test_cx_remediation_execution_postgres_smoke_main_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_cx_remediation_execution_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "service_id": smoke.SERVICE_ID,
            "failure_code": "forced",
        },
    )

    assert smoke.main(["--summary"]) == 1
    assert "cx_remediation_execution_postgres_smoke=fail" in capsys.readouterr().out
