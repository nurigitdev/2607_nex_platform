from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import run_ag_operator_review_case_sla_escalation_postgres_smoke as smoke
from nex_ag.operator_review_cases import OperatorReviewCaseStore
from nex_runtime import InMemoryOperationalEventStore
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class FakeExecuteResult:
    def __init__(
        self,
        *,
        scalar_value: object | None = None,
        row: dict[str, object] | None = None,
        rowcount: int = 0,
    ) -> None:
        self._scalar_value = scalar_value
        self._row = row or {}
        self.rowcount = rowcount

    def scalar(self) -> object | None:
        return self._scalar_value

    def mappings(self) -> "FakeExecuteResult":
        return self

    def one(self) -> dict[str, object]:
        return self._row


class FakeObservationConnection:
    def __enter__(self) -> "FakeObservationConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: object, params: object | None = None) -> FakeExecuteResult:
        sql = str(statement)
        if "to_regclass" in sql:
            table_name = sql.split("public.")[-1].split("'")[0]
            return FakeExecuteResult(scalar_value=f"public.{table_name}")
        return FakeExecuteResult(row=_observations_without_tables())


class FakeObservationEngine:
    def connect(self) -> FakeObservationConnection:
        return FakeObservationConnection()


class FakeCleanupConnection:
    def __init__(self) -> None:
        self.calls = 0

    def __enter__(self) -> "FakeCleanupConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: object, params: object | None = None) -> FakeExecuteResult:
        self.calls += 1
        return FakeExecuteResult(rowcount=2 if self.calls == 1 else 1)


class FakeCleanupEngine:
    def __init__(self) -> None:
        self.connection = FakeCleanupConnection()

    def begin(self) -> FakeCleanupConnection:
        return self.connection


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
    }


def test_ag_operator_review_case_sla_escalation_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ag_operator_review_case_sla_escalation_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_case_sla_escalation_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ag_operator_review_case_sla_escalation_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_operator_review_case_sla_escalation_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"


def test_ag_operator_review_case_sla_escalation_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ag_operator_review_case_sla_escalation_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_ag_operator_review_case_sla_escalation_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewCaseStore",
        lambda session_factory: OperatorReviewCaseStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperationalEventStore",
        lambda session_factory: InMemoryOperationalEventStore(),
    )
    monkeypatch.setattr(smoke, "_db_observations", lambda *args, **kwargs: _observations())
    monkeypatch.setattr(smoke, "_cleanup_smoke_rows", lambda *args, **kwargs: {"cases": 1, "events": 1})
    env = smoke_env()

    evidence = smoke.run_ag_operator_review_case_sla_escalation_postgres_smoke(env)
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["checks"]["policy_schema"] is True
    assert evidence["checks"]["aging_overdue_count"] is True
    assert evidence["checks"]["escalation_candidate_count"] is True
    assert evidence["checks"]["dashboard_escalation_count"] is True
    assert evidence["cleanup"] == {"cases": 1, "events": 1}
    assert fake_engine.disposed is True
    assert env[smoke.DATABASE_ENV] not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert smoke.RAW_CASE_COMMENT not in serialized
    assert "ag-op-case-sla-create-idem" not in serialized
    assert smoke.summary_line(evidence).startswith(
        "ag_operator_review_case_sla_escalation_postgres_smoke=pass"
    )


def test_ag_operator_review_case_sla_escalation_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewCaseStore",
        lambda session_factory: OperatorReviewCaseStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperationalEventStore",
        lambda session_factory: InMemoryOperationalEventStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: {**_observations(), "event_count": 0},
    )
    monkeypatch.setattr(smoke, "_cleanup_smoke_rows", lambda *args, **kwargs: {"cases": 1, "events": 0})

    evidence = smoke.run_ag_operator_review_case_sla_escalation_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["event_rows_persisted"] is False
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_case_sla_escalation_postgres_smoke=fail "
        "reason=checks_failed"
    )


def test_ag_operator_review_case_sla_escalation_postgres_smoke_reports_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewCaseStore",
        lambda session_factory: (_ for _ in ()).throw(ValueError("store unavailable")),
    )

    evidence = smoke.run_ag_operator_review_case_sla_escalation_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert fake_engine.disposed is True


def test_ag_operator_review_case_sla_escalation_postgres_smoke_handles_engine_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url: (_ for _ in ()).throw(ValueError("engine unavailable")),
    )

    evidence = smoke.run_ag_operator_review_case_sla_escalation_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert "engine unavailable" in evidence["detail"]


def test_ag_operator_review_case_sla_escalation_postgres_smoke_helpers() -> None:
    assert smoke._regclass_matches("public.ag_op_cases", "ag_op_cases")
    assert not smoke._regclass_matches(None, "ag_op_cases")
    assert smoke._db_observations(
        FakeObservationEngine(),
        target_id="target",
        trace_id="trace",
        case_id="case",
        raw_case_comment="raw",
    ) == _observations()
    cleanup_engine = FakeCleanupEngine()
    assert smoke._cleanup_smoke_rows(cleanup_engine, "case", "target", "trace") == {
        "cases": 1,
        "events": 2,
    }
    assert cleanup_engine.connection.calls == 2
    assert smoke._cleanup_smoke_rows(object(), None, None, None) == {
        "cases": 0,
        "events": 0,
    }
    assert smoke._cleanup_smoke_rows(object(), "case", "target", "trace") == {
        "cases": 0,
        "events": 0,
    }
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
            smoke_env(),
            forbidden_values=(),
        )
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            smoke.RAW_CASE_COMMENT,
            {},
            forbidden_values=(smoke.RAW_CASE_COMMENT,),
        )


def test_ag_operator_review_case_sla_escalation_postgres_smoke_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    skipped = {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_case_sla_escalation_postgres_smoke",
        lambda: skipped,
    )

    assert smoke.main(["--summary"]) == 0
    assert "ag_operator_review_case_sla_escalation_postgres_smoke=skipped" in (
        capsys.readouterr().out
    )
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SKIPPED"


def _migration_result(*args: object, **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=("0687_ag_operator_review_case_sla_contracts",),
        applied=("0689_ag_operator_review_case_sla_escalation_postgres_smoke",),
        skipped=(),
    )


def _observations() -> dict[str, object]:
    return {
        "tables_present": {
            "ag_op_cases": True,
            "service_operational_events": True,
        },
        **_observations_without_tables(),
    }


def _observations_without_tables() -> dict[str, object]:
    return {
        "case_count": 1,
        "event_count": 1,
        "event_details_case_count": 1,
        "raw_case_comment_leak_count": 0,
    }
