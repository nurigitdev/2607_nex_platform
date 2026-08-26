from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ag_remediation_execution_status_sync_postgres_smoke as smoke
from nex_ag.generation_remediation import GenerationRemediationTaskStore
from nex_ag.generation_remediation_handoff import CxRemediationExecutionClientError
from nex_cx.remediation_execution import RemediationExecutionStore
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
        planned=("0369_ag_remediation_execution_status_sync",),
        applied=("0369_ag_remediation_execution_status_sync",),
        skipped=(),
    )


def ag_observations(action_status: str = "COMPLETED") -> dict[str, Any]:
    return {
        "row_count": 1,
        "action_status": action_status,
        "result_ref_id": "cx-repair-run",
        "result_ref_type": "jsonb",
    }


def cx_observations(execution_status: str = "SUCCEEDED") -> dict[str, Any]:
    return {
        "row_count": 1,
        "execution_status": execution_status,
        "parent_cx_generation_id": "cx-gen-remediation-status-sync",
        "result_ref_id": "cx-repair-run",
        "result_ref_type": "jsonb",
    }


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


def test_ag_remediation_execution_status_sync_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ag_remediation_execution_status_sync_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ag_remediation_execution_status_sync_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ag_remediation_execution_status_sync_postgres_smoke_rejects_dev_profile() -> None:
    evidence = smoke.run_ag_remediation_execution_status_sync_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.SMOKE_PROFILE_ENV: "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_ag_remediation_execution_status_sync_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_remediation_execution_status_sync_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AG_TEST_DATABASE_URL" in evidence["detail"]


def test_ag_remediation_execution_status_sync_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ag_remediation_execution_status_sync_postgres_smoke(
        postgres_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert evidence["detail"] == "bad migration"


def test_ag_remediation_execution_status_sync_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ag_engine = FakeEngine()
    cx_engine = FakeEngine()
    engines = iter([ag_engine, cx_engine])
    ag_store = GenerationRemediationTaskStore()
    cx_store = RemediationExecutionStore()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service_id, **kwargs: migration_result(service_id),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: next(engines))
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyGenerationRemediationTaskStore",
        lambda session_factory, **kwargs: ag_store,
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRemediationExecutionStore",
        lambda session_factory, **kwargs: cx_store,
    )
    monkeypatch.setattr(
        smoke,
        "_ag_db_observations",
        lambda engine, remediation_action_id: ag_observations(),
    )
    monkeypatch.setattr(
        smoke,
        "_cx_db_observations",
        lambda engine, remediation_action_id: cx_observations(),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_ag_smoke_rows",
        lambda engine, remediation_action_id: {"ag_generation_remediation_tasks": 1},
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_cx_smoke_rows",
        lambda engine, remediation_action_id: {"cx_remediation_execution_attempts": 1},
    )
    env = postgres_env()

    evidence = smoke.run_ag_remediation_execution_status_sync_postgres_smoke(env)

    assert evidence["status"] == "PASS"
    assert evidence["sync"]["sync_status"] == "UPDATED"
    assert evidence["sync"]["final_action_status"] == "COMPLETED"
    assert evidence["sync"]["cx_execution_status"] == "SUCCEEDED"
    assert evidence["cx_status_client"]["call_count"] == 1
    assert evidence["cleanup"][smoke.AG_SERVICE_ID][
        "ag_generation_remediation_tasks"
    ] == 1
    assert evidence["cleanup"][smoke.CX_SERVICE_ID][
        "cx_remediation_execution_attempts"
    ] == 1
    assert ag_engine.disposed is True
    assert cx_engine.disposed is True
    assert "secret" not in str(evidence)
    assert smoke.summary_line(evidence).startswith(
        "ag_remediation_execution_status_sync_postgres_smoke=pass"
    )


def test_ag_remediation_execution_status_sync_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engines = iter([FakeEngine(), FakeEngine()])
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service_id, **kwargs: migration_result(service_id),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: next(engines))
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
    monkeypatch.setattr(
        smoke,
        "_ag_db_observations",
        lambda engine, remediation_action_id: ag_observations("WAITING_ON_CX"),
    )
    monkeypatch.setattr(
        smoke,
        "_cx_db_observations",
        lambda engine, remediation_action_id: cx_observations(),
    )

    evidence = smoke.run_ag_remediation_execution_status_sync_postgres_smoke(
        postgres_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"


def test_in_process_cx_status_client_maps_problem_response() -> None:
    class FakeResponse:
        status_code = 404

        def json(self) -> dict[str, Any]:
            return {
                "error_code": "cx.remediation_execution_not_found",
                "detail": "missing",
            }

    class FakeClient:
        def get(self, *args: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

    client = smoke.InProcessCxRemediationExecutionStatusClient(FakeClient())

    with pytest.raises(CxRemediationExecutionClientError) as exc_info:
        client.get_remediation_execution_detail(
            parent_cx_generation_id="cx-gen-001",
            remediation_action_id="missing",
            request_id="request-001",
            trace_id=smoke.TRACE_ID,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "cx.remediation_execution_not_found"
    assert client.call_count == 1
    assert client.last_path.endswith("/remediation-executions/missing")


def test_status_sync_smoke_noop_client_and_safe_json_fallback() -> None:
    with pytest.raises(AssertionError):
        smoke.NoopCxRemediationExecutionClient().submit_remediation_action({})

    class InvalidJsonResponse:
        def json(self) -> dict[str, Any]:
            raise ValueError("not json")

    assert smoke._safe_json(InvalidJsonResponse()) == {}


def test_status_sync_smoke_disposes_first_engine_when_second_engine_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ag_engine = FakeEngine()
    calls = iter([ag_engine, RuntimeError("cx engine failed")])

    def build_engine(database_url: str) -> FakeEngine:
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(smoke, "build_engine", build_engine)
    monkeypatch.setattr(
        smoke,
        "_cleanup_ag_smoke_rows",
        lambda engine, remediation_action_id: {"ag_generation_remediation_tasks": 0},
    )

    with pytest.raises(RuntimeError, match="cx engine failed"):
        smoke._execute_status_sync_smoke(
            ag_database_env="NEX_AG_TEST_DATABASE_URL",
            ag_database_url="postgresql://ag",
            cx_database_env="NEX_CX_TEST_DATABASE_URL",
            cx_database_url="postgresql://cx",
        )

    assert ag_engine.disposed is True


def test_status_sync_smoke_handles_first_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url: (_ for _ in ()).throw(RuntimeError("ag engine failed")),
    )

    with pytest.raises(RuntimeError, match="ag engine failed"):
        smoke._execute_status_sync_smoke(
            ag_database_env="NEX_AG_TEST_DATABASE_URL",
            ag_database_url="postgresql://ag",
            cx_database_env="NEX_CX_TEST_DATABASE_URL",
            cx_database_url="postgresql://cx",
        )


def test_ag_remediation_execution_status_sync_redaction_guard_rejects_raw_urls() -> None:
    env = postgres_env()

    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(env["NEX_CX_TEST_DATABASE_URL"], env)


def test_ag_and_cx_db_observations_handle_missing_rows() -> None:
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

    assert smoke._ag_db_observations(
        FakeObservationEngine(),
        remediation_action_id="missing",
    ) == {
        "row_count": 0,
        "action_status": None,
        "result_ref_id": None,
        "result_ref_type": None,
    }
    assert smoke._cx_db_observations(
        FakeObservationEngine(),
        remediation_action_id="missing",
    ) == {
        "row_count": 0,
        "execution_status": None,
        "parent_cx_generation_id": None,
        "result_ref_id": None,
        "result_ref_type": None,
    }


def test_ag_remediation_execution_status_sync_cleanup_helpers() -> None:
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

    assert smoke._cleanup_ag_smoke_rows(
        FakeCleanupEngine(),
        remediation_action_id="action-id",
    ) == {"ag_generation_remediation_tasks": 1}
    assert smoke._cleanup_cx_smoke_rows(
        FakeCleanupEngine(),
        remediation_action_id="action-id",
    ) == {"cx_remediation_execution_attempts": 1}
    assert smoke._rowcount(SimpleNamespace(rowcount=-1)) == 0


def test_ag_remediation_execution_status_sync_cleanup_ignores_sqlalchemy_errors() -> None:
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

    assert smoke._cleanup_ag_smoke_rows(
        ExplodingEngine(),
        remediation_action_id="action-id",
    ) == {"ag_generation_remediation_tasks": 0}
    assert smoke._cleanup_cx_smoke_rows(
        ExplodingEngine(),
        remediation_action_id="action-id",
    ) == {"cx_remediation_execution_attempts": 0}


def test_ag_remediation_execution_status_sync_main_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_ag_remediation_execution_status_sync_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "service_id": smoke.AG_SERVICE_ID,
            "failure_code": "forced",
        },
    )

    assert smoke.main(["--summary"]) == 1
    assert "ag_remediation_execution_status_sync_postgres_smoke=fail" in (
        capsys.readouterr().out
    )
