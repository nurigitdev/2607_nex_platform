from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_cx_remediation_execution_read_model_postgres_smoke as smoke
from nex_cx.remediation_execution import RemediationExecutionStore
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def migration_result() -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        profile=smoke.DEFAULT_PROFILE,
        dry_run=False,
        planned=("0355_cx_repair_attempt_lineage_persistence_foundation",),
        applied=("0355_cx_repair_attempt_lineage_persistence_foundation",),
        skipped=(),
    )


def observations() -> dict[str, Any]:
    return {
        "row_count": 1,
        "execution_status": "ACCEPTED",
        "parent_cx_generation_id": "cx-gen-remediation-read-model",
        "jsonb_columns": dict(smoke.EXPECTED_JSONB_COLUMNS),
        "index_names": sorted(smoke.EXPECTED_INDEXES),
    }


def test_cx_remediation_execution_read_model_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_cx_remediation_execution_read_model_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "cx_remediation_execution_read_model_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_cx_remediation_execution_read_model_postgres_smoke_rejects_dev_profile() -> None:
    evidence = smoke.run_cx_remediation_execution_read_model_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.SMOKE_PROFILE_ENV: "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "cx_remediation_execution_read_model_postgres_smoke=fail "
        "service=nex-cx reason=profile_not_allowed"
    )


def test_cx_remediation_execution_read_model_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_cx_remediation_execution_read_model_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_CX_TEST_DATABASE_URL" in evidence["detail"]


def test_cx_remediation_execution_read_model_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_cx_remediation_execution_read_model_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert evidence["detail"] == "bad migration"


def test_cx_remediation_execution_read_model_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    execution_store = RemediationExecutionStore()
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *args, **kwargs: migration_result())
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRemediationExecutionStore",
        lambda session_factory, **kwargs: execution_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda engine, remediation_action_id: observations(),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda engine, remediation_action_id: {
            "cx_remediation_execution_attempts": 1
        },
    )
    raw_url = "postgresql://nex_cx_user:secret@localhost/nex_cx_test"

    evidence = smoke.run_cx_remediation_execution_read_model_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": raw_url,
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["api"]["list_count"] == 1
    assert evidence["api"]["detail_execution_status"] == "ACCEPTED"
    assert evidence["api"]["lineage_status"] == "PENDING_REPAIR_GENERATION"
    assert evidence["api"]["missing_status"] == 404
    assert evidence["checks"]["lineage_schema"] is True
    assert evidence["checks"]["lineage_pending"] is True
    assert evidence["checks"]["lineage_parent_independent"] is True
    assert evidence["checks"]["lineage_redaction_safe"] is True
    assert evidence["checks"]["read_model_parent_independent"] is True
    assert evidence["cleanup"]["cx_remediation_execution_attempts"] == 1
    assert fake_engine.disposed is True
    assert raw_url not in str(evidence)
    assert "secret" not in evidence["redacted_database_url"]
    assert smoke.summary_line(evidence).startswith(
        "cx_remediation_execution_read_model_postgres_smoke=pass"
    )


def test_cx_remediation_execution_read_model_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    bad_observations = observations()
    bad_observations["execution_status"] = "FAILED"
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *args, **kwargs: migration_result())
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRemediationExecutionStore",
        lambda session_factory, **kwargs: RemediationExecutionStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda engine, remediation_action_id: bad_observations,
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda engine, remediation_action_id: {
            "cx_remediation_execution_attempts": 1
        },
    )

    evidence = smoke.run_cx_remediation_execution_read_model_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert fake_engine.disposed is True


def test_cx_remediation_execution_read_model_redaction_guard_rejects_raw_url() -> None:
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
            {
                "NEX_CX_TEST_DATABASE_URL": (
                    "postgresql://nex_cx_user:secret@localhost/nex_cx_test"
                )
            },
        )

    assert smoke._redaction_safe(
        {"redaction_summary": {"excluded_fields": ["provider_endpoint", "api_key"]}}
    )
    assert not smoke._redaction_safe({"provider_endpoint": "http://hidden"})


def test_cx_remediation_execution_read_model_db_observations_handles_missing_row() -> None:
    class FakeResult:
        def __init__(self, row: dict[str, Any] | None = None) -> None:
            self.row = row

        def mappings(self) -> "FakeResult":
            return self

        def first(self) -> dict[str, Any] | None:
            return self.row

        def all(self) -> list[dict[str, str]]:
            return [{"indexname": "idx_b"}, {"indexname": "idx_a"}]

    class FakeConnection:
        def __init__(self) -> None:
            self.calls = 0

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, params: object | None = None) -> FakeResult:
            self.calls += 1
            return FakeResult()

    class FakeObservationEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

    assert smoke._db_observations(
        FakeObservationEngine(),
        remediation_action_id="missing",
    ) == {
        "row_count": 0,
        "execution_status": None,
        "parent_cx_generation_id": None,
        "jsonb_columns": {
            "result_ref": None,
            "failure": None,
            "redaction_summary": None,
            "metadata": None,
        },
        "index_names": ["idx_a", "idx_b"],
    }


def test_cx_remediation_execution_read_model_cleanup_reports_rowcount() -> None:
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

    assert smoke._cleanup_smoke_rows(
        FakeCleanupEngine(),
        remediation_action_id="action-id",
    ) == {"cx_remediation_execution_attempts": 1}
    assert smoke._rowcount(SimpleNamespace(rowcount=-1)) == 0


def test_cx_remediation_execution_read_model_cleanup_ignores_sqlalchemy_errors() -> None:
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
    ) == {"cx_remediation_execution_attempts": 0}


def test_cx_remediation_execution_read_model_main_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_cx_remediation_execution_read_model_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "service_id": smoke.SERVICE_ID,
            "failure_code": "forced",
        },
    )

    assert smoke.main(["--summary"]) == 1
    assert "cx_remediation_execution_read_model_postgres_smoke=fail" in (
        capsys.readouterr().out
    )
