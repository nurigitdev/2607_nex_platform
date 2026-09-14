from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import run_ag_operator_review_escalation_dispatch_provider_postgres_smoke as smoke
from nex_ag.operator_review_cases import (
    OperatorReviewCaseStore,
    OperatorReviewEscalationDispatchStore,
    OperatorReviewEscalationStore,
)
from run_migrations import MigrationError


ROOT = Path(__file__).resolve().parents[1]


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

    def execute(
        self,
        statement: object,
        params: object | None = None,
    ) -> FakeExecuteResult:
        sql = str(statement)
        if "to_regclass" in sql:
            table_name = sql.split("public.")[-1].split("'")[0]
            return FakeExecuteResult(scalar_value=f"public.{table_name}")
        if "AS leak_count" in sql:
            return FakeExecuteResult(row={"leak_count": 0})
        return FakeExecuteResult(row=_observation_row())


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

    def execute(
        self,
        statement: object,
        params: object | None = None,
    ) -> FakeExecuteResult:
        self.calls += 1
        return FakeExecuteResult(rowcount={1: 2, 2: 1, 3: 1}[self.calls])


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


def test_ag_dispatch_provider_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ag_operator_review_escalation_dispatch_provider_postgres_smoke(
        {}
    )

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_escalation_dispatch_provider_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV} is not enabled."
    )


def test_ag_dispatch_provider_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_operator_review_escalation_dispatch_provider_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"


def test_ag_dispatch_provider_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ag_operator_review_escalation_dispatch_provider_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_ag_dispatch_provider_postgres_smoke_success_is_redacted(
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
        "SqlAlchemyOperatorReviewEscalationStore",
        lambda session_factory: OperatorReviewEscalationStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewEscalationDispatchStore",
        lambda session_factory: OperatorReviewEscalationDispatchStore(),
    )
    monkeypatch.setattr(smoke, "_db_observations", lambda *args, **kwargs: _observations())
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda *args, **kwargs: {
            "cases": 1,
            "escalations": 1,
            "dispatches": 2,
        },
    )
    env = smoke_env()

    evidence = smoke.run_ag_operator_review_escalation_dispatch_provider_postgres_smoke(
        env
    )
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert evidence["status"] == "PASS"
    assert evidence["checks"]["worker_processed_two"] is True
    assert evidence["checks"]["provider_categories_persisted"] is True
    assert evidence["checks"]["dashboard_http_statuses"] is True
    assert evidence["cleanup"] == {
        "cases": 1,
        "escalations": 1,
        "dispatches": 2,
    }
    assert fake_engine.disposed is True
    assert env[smoke.DATABASE_ENV] not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert smoke.RAW_PROVIDER_PAYLOAD not in serialized
    assert "notification-token-smoke" not in serialized
    assert smoke.summary_line(evidence).startswith(
        "ag_operator_review_escalation_dispatch_provider_postgres_smoke=pass"
    )


def test_ag_dispatch_provider_postgres_smoke_reports_failed_checks(
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
        "SqlAlchemyOperatorReviewEscalationStore",
        lambda session_factory: OperatorReviewEscalationStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewEscalationDispatchStore",
        lambda session_factory: OperatorReviewEscalationDispatchStore(),
    )
    failed_observations = {**_observations(), "provider_metadata_count": 1}
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: failed_observations,
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda *args, **kwargs: {"cases": 0, "escalations": 0, "dispatches": 0},
    )

    evidence = smoke.run_ag_operator_review_escalation_dispatch_provider_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["provider_metadata_persisted"] is False
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_escalation_dispatch_provider_postgres_smoke=fail "
        "failure=checks_failed"
    )


def test_ag_dispatch_provider_postgres_smoke_reports_execution_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", _migration_result)
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url: (_ for _ in ()).throw(ValueError("engine boom")),
    )

    evidence = smoke.run_ag_operator_review_escalation_dispatch_provider_postgres_smoke(
        smoke_env()
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert "engine boom" in evidence["detail"]


def test_ag_dispatch_provider_postgres_smoke_db_observations_and_cleanup() -> None:
    observations = smoke._db_observations(
        FakeObservationEngine(),
        target_id="target-0729",
        trace_id=smoke.TRACE_ID,
        case_id="case-0729",
        escalation_id="escalation-0729",
        dispatch_ids=["dispatch-email", "dispatch-incident"],
        idempotency_keys=("idem-email", "idem-incident"),
    )

    assert observations == _observations()

    cleanup_engine = FakeCleanupEngine()
    cleanup = smoke._cleanup_smoke_rows(
        cleanup_engine,
        case_id="case-0729",
        escalation_id="escalation-0729",
        dispatch_ids=["dispatch-email", "dispatch-incident"],
        target_id="target-0729",
        trace_id=smoke.TRACE_ID,
    )
    assert cleanup == {"cases": 1, "escalations": 1, "dispatches": 2}
    assert cleanup_engine.connection.calls == 3
    assert smoke._cleanup_smoke_rows(
        cleanup_engine,
        case_id=None,
        escalation_id=None,
        dispatch_ids=[],
        target_id="target-0729",
        trace_id=smoke.TRACE_ID,
    ) == {"cases": 0, "escalations": 0, "dispatches": 0}


def test_ag_dispatch_provider_postgres_smoke_redaction_guard() -> None:
    with pytest.raises(ValueError, match=smoke.DATABASE_ENV):
        smoke.assert_smoke_evidence_redacted(
            smoke_env()[smoke.DATABASE_ENV],
            smoke_env(),
            forbidden_values=(),
        )
    with pytest.raises(ValueError, match="Sensitive dispatch provider"):
        smoke.assert_smoke_evidence_redacted(
            smoke.RAW_PROVIDER_PAYLOAD,
            {},
            forbidden_values=(smoke.RAW_PROVIDER_PAYLOAD,),
        )


def test_ag_dispatch_provider_postgres_smoke_main_summary_and_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_provider_postgres_smoke",
        lambda: {"status": "SKIPPED", "skip_reason": "disabled"},
    )
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py", "--summary"],
    )
    smoke.main()
    assert "provider_postgres_smoke=skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py"],
    )
    smoke.main()
    assert '"status": "SKIPPED"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_provider_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py", "--summary"],
    )
    with pytest.raises(SystemExit):
        smoke.main()


def test_ag_dispatch_provider_postgres_smoke_script_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(smoke.SMOKE_ENV, "0")
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py", "--summary"],
    )

    runpy.run_path(
        str(
            ROOT
            / "scripts"
            / "smoke"
            / "run_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py"
        ),
        run_name="__main__",
    )

    assert "provider_postgres_smoke=skipped" in capsys.readouterr().out


def _migration_result(*args: object, **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=("0000_base",),
        applied=("0729_provider_postgres_smoke",),
        skipped=(),
    )


def _observations() -> dict[str, object]:
    return {
        "tables_present": {
            "ag_op_cases": True,
            "ag_op_escalations": True,
            "ag_op_esc_dispatches": True,
        },
        "case_count": 1,
        "escalation_count": 1,
        "dispatch_count": 2,
        "succeeded_count": 2,
        "provider_metadata_count": 2,
        "raw_value_leak_count": 0,
        "idempotency_leak_count": 0,
    }


def _observation_row() -> dict[str, object]:
    return {
        "case_count": 1,
        "escalation_count": 1,
        "dispatch_count": 2,
        "succeeded_count": 2,
        "provider_metadata_count": 2,
        "row_secret_leak_count": 0,
    }
