from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ag_operator_review_case_workbench_postgres_smoke as smoke
from nex_runtime import InMemoryOperationalEventStore
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_ag_operator_review_case_workbench_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ag_operator_review_case_workbench_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_case_workbench_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ag_operator_review_case_workbench_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_operator_review_case_workbench_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_case_workbench_postgres_smoke=fail "
        "reason=database_url_missing"
    )


def test_ag_operator_review_case_workbench_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ag_operator_review_case_workbench_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_ag_operator_review_case_workbench_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    case_store = smoke.OperatorReviewCaseStore()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=("0657_ag_operator_review_case_workbench_contract_openapi",),
            applied=("0658_ag_operator_review_case_workbench_postgres_smoke",),
            skipped=(),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewCaseStore",
        lambda session_factory: case_store,
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperationalEventStore",
        lambda session_factory: InMemoryOperationalEventStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: _passing_observations(),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda engine, case_id, target_id, trace_id: {"cases": 1, "events": 2},
    )
    raw_url = "postgresql://nex_ag_user:secret@localhost/nex_ag_test"

    evidence = smoke.run_ag_operator_review_case_workbench_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: raw_url,
        }
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == smoke.DATABASE_ENV
    assert evidence["checks"]["queue_status"] is True
    assert evidence["checks"]["queue_latest_action_assign"] is True
    assert evidence["checks"]["detail_timeline_link"] is True
    assert evidence["checks"]["timeline_case_event"] is True
    assert evidence["checks"]["timeline_action_event"] is True
    assert evidence["checks"]["event_rows_persisted"] is True
    assert evidence["cleanup"] == {"cases": 1, "events": 2}
    assert fake_engine.disposed is True
    assert raw_url not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert smoke.RAW_ACTION_COMMENT not in serialized
    assert "ag-op-case-workbench-create-idem" not in serialized
    assert "ag-op-case-workbench-action-idem" not in serialized
    assert smoke.summary_line(evidence).startswith(
        "ag_operator_review_case_workbench_postgres_smoke=pass"
    )


def test_ag_operator_review_case_workbench_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=(),
            applied=(),
            skipped=("0657_ag_operator_review_case_workbench_contract_openapi",),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewCaseStore",
        lambda session_factory: smoke.OperatorReviewCaseStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperationalEventStore",
        lambda session_factory: InMemoryOperationalEventStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: {**_passing_observations(), "event_count": 0},
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda engine, case_id, target_id, trace_id: {"cases": 1, "events": 0},
    )

    evidence = smoke.run_ag_operator_review_case_workbench_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["event_rows_persisted"] is False
    assert fake_engine.disposed is True


def test_ag_operator_review_case_workbench_postgres_smoke_reports_exception_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=(),
            applied=(),
            skipped=("0657_ag_operator_review_case_workbench_contract_openapi",),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "_case_payload", lambda **kwargs: _raise_value_error())

    evidence = smoke.run_ag_operator_review_case_workbench_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "bad payload"
    assert fake_engine.disposed is True


def test_ag_operator_review_case_workbench_postgres_smoke_reports_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=(),
            applied=(),
            skipped=("0657_ag_operator_review_case_workbench_contract_openapi",),
        ),
    )
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url: (_ for _ in ()).throw(SQLAlchemyError("engine down")),
    )

    evidence = smoke.run_ag_operator_review_case_workbench_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "engine down"


def test_ag_operator_review_case_workbench_redaction_guard_rejects_sensitive_values() -> None:
    with pytest.raises(ValueError, match="raw DB URL"):
        smoke.assert_smoke_evidence_redacted(
            "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
            {
                smoke.DATABASE_ENV: (
                    "postgresql://nex_ag_user:secret@localhost/nex_ag_test"
                )
            },
            raw_action_comment="safe comment",
            idempotency_keys=("safe-create-idem", "safe-action-idem"),
        )
    with pytest.raises(ValueError, match="raw action comment"):
        smoke.assert_smoke_evidence_redacted(
            "raw action comment leaked",
            {},
            raw_action_comment="raw action comment leaked",
            idempotency_keys=("safe-create-idem", "safe-action-idem"),
        )
    with pytest.raises(ValueError, match="raw idempotency key"):
        smoke.assert_smoke_evidence_redacted(
            "action idem leaked",
            {},
            raw_action_comment="safe comment",
            idempotency_keys=("safe-create-idem", "action idem leaked"),
        )


def test_ag_operator_review_case_workbench_smoke_helpers() -> None:
    assert smoke._queue_latest_action_type({"items": []}) is None
    assert smoke._queue_latest_action_type({"items": ["bad"]}) is None
    assert smoke._queue_latest_action_type({"items": [{}]}) is None
    assert (
        smoke._queue_latest_action_type(
            {"items": [{"latest_action": {"action_type": "ASSIGN"}}]}
        )
        == "ASSIGN"
    )
    assert smoke._redaction_flags_are_false("bad", ("flag",)) is False
    assert smoke._redaction_flags_are_false({"flag": True}, ("flag",)) is False
    assert smoke._redaction_flags_are_false({"flag": False}, ("flag",)) is True
    assert smoke._regclass_matches("public.service_operational_events", "service_operational_events") is True
    assert smoke._regclass_matches(None, "service_operational_events") is False


def test_ag_operator_review_case_workbench_db_observations() -> None:
    class FakeScalarResult:
        def __init__(self, value: str) -> None:
            self._value = value

        def scalar(self) -> str:
            return self._value

    class FakeMappingResult:
        def mappings(self) -> "FakeMappingResult":
            return self

        def one(self) -> dict[str, Any]:
            return {
                "case_count": 1,
                "event_count": 2,
                "case_event_count": 1,
                "action_event_count": 1,
                "event_details_type": "jsonb",
                "event_details_case_count": 2,
                "raw_action_comment_leak_count": 0,
            }

    class FakeConnection:
        def __init__(self) -> None:
            self._scalar_values = [
                "public.ag_op_cases",
                "public.service_operational_events",
            ]

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, params: object | None = None) -> object:
            if params is None:
                return FakeScalarResult(self._scalar_values.pop(0))
            return FakeMappingResult()

    class FakeObservationEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

    assert smoke._db_observations(
        FakeObservationEngine(),
        target_id="target",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        case_id="case",
        raw_action_comment="raw",
    ) == _passing_observations()


def test_ag_operator_review_case_workbench_cleanup_helpers() -> None:
    assert smoke._cleanup_smoke_rows(object(), None, None, None) == {
        "cases": 0,
        "events": 0,
    }

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
        "case",
        "target",
        "trace",
    ) == {"cases": 0, "events": 0}

    class Result:
        rowcount = 2

    class WorkingBegin:
        def __enter__(self) -> "WorkingBegin":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, *args: object, **kwargs: object) -> Result:
            return Result()

    class WorkingEngine:
        def begin(self) -> WorkingBegin:
            return WorkingBegin()

    assert smoke._cleanup_smoke_rows(WorkingEngine(), "case", "target", "trace") == {
        "cases": 2,
        "events": 2,
    }
    assert smoke._cleanup_smoke_rows(WorkingEngine(), "case", None, None) == {
        "cases": 2,
        "events": 2,
    }
    assert smoke._cleanup_smoke_rows(WorkingEngine(), None, "target", None) == {
        "cases": 2,
        "events": 2,
    }


def test_ag_operator_review_case_workbench_smoke_helpers_and_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_case_workbench_postgres_smoke",
        lambda: {"smoke_schema_version": smoke.SCHEMA_VERSION, "status": "SKIPPED"},
    )

    assert smoke._case_payload(suffix="abc", target_id="target")["target_ref"][
        "target_id"
    ] == "target"
    assert smoke._action_payload(suffix="abc")["action_type"] == "ASSIGN"
    assert "Idempotency-Key" not in smoke._admin_headers(
        request_id="request",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    assert smoke.main(["--summary"]) == 0
    assert (
        "ag_operator_review_case_workbench_postgres_smoke=skipped"
        in capsys.readouterr().out
    )


def _passing_observations() -> dict[str, Any]:
    return {
        "tables_present": {
            "ag_op_cases": True,
            "service_operational_events": True,
        },
        "case_count": 1,
        "event_count": 2,
        "event_type_counts": {
            smoke.OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE: 1,
            smoke.OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE: 1,
        },
        "event_details_type": "jsonb",
        "event_details_case_count": 2,
        "raw_action_comment_leak_count": 0,
    }


def _raise_value_error() -> None:
    raise ValueError("bad payload")
