from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ag_operator_review_case_postgres_smoke as smoke
from nex_ag.operator_review_cases import OperatorReviewCaseStore
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_ag_operator_review_case_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ag_operator_review_case_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_case_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ag_operator_review_case_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_operator_review_case_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_case_postgres_smoke=fail reason=database_url_missing"
    )


def test_ag_operator_review_case_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ag_operator_review_case_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_ag_operator_review_case_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    case_store = OperatorReviewCaseStore()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=("0642_ag_operator_review_case_persistence",),
            applied=("0649_ag_operator_review_case_postgres_smoke",),
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
        "_db_observations",
        lambda engine, target_id: _passing_observations(),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_case_rows",
        lambda engine, case_id, target_id: {"cases": 1},
    )
    raw_url = "postgresql://nex_ag_user:secret@localhost/nex_ag_test"

    evidence = smoke.run_ag_operator_review_case_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: raw_url,
        }
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == smoke.DATABASE_ENV
    assert evidence["checks"]["case_create_status"] is True
    assert evidence["checks"]["case_create_replay_status"] is True
    assert evidence["checks"]["case_action_status"] is True
    assert evidence["checks"]["dashboard_case_visible"] is True
    assert evidence["cleanup"] == {"cases": 1}
    assert fake_engine.disposed is True
    assert raw_url not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert smoke.RAW_ACTION_COMMENT not in serialized
    assert "ag-op-case-create-idem" not in serialized
    assert "ag-op-case-action-idem" not in serialized
    assert smoke.summary_line(evidence).startswith(
        "ag_operator_review_case_postgres_smoke=pass"
    )


def test_ag_operator_review_case_postgres_smoke_reports_failed_checks(
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
            skipped=("0642_ag_operator_review_case_persistence",),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewCaseStore",
        lambda session_factory: OperatorReviewCaseStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda engine, target_id: {**_passing_observations(), "case_count": 0},
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_case_rows",
        lambda engine, case_id, target_id: {"cases": 1},
    )

    evidence = smoke.run_ag_operator_review_case_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["table_rows"] is False
    assert fake_engine.disposed is True


def test_ag_operator_review_case_postgres_smoke_reports_exception_failure(
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
            skipped=("0642_ag_operator_review_case_persistence",),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(
        smoke,
        "_case_payload",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("bad payload")),
    )

    evidence = smoke.run_ag_operator_review_case_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "bad payload"
    assert fake_engine.disposed is True


def test_ag_operator_review_case_postgres_smoke_reports_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=(),
            applied=(),
            skipped=("0642_ag_operator_review_case_persistence",),
        ),
    )
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url: (_ for _ in ()).throw(SQLAlchemyError("engine down")),
    )

    evidence = smoke.run_ag_operator_review_case_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "engine down"


def test_ag_operator_review_case_redaction_guard_rejects_sensitive_values() -> None:
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


def test_ag_operator_review_case_smoke_helper_branches() -> None:
    assert smoke._first_attention_status({"attention": "bad"}) is None
    assert smoke._first_attention_status({"attention": {"items": []}}) is None
    assert smoke._first_attention_status({"attention": {"items": ["bad"]}}) is None
    assert (
        smoke._first_attention_status(
            {"attention": {"items": [{"attention_status": "BLOCKED"}]}}
        )
        == "BLOCKED"
    )
    assert smoke._contains_attention_target("bad", "target") is False
    assert smoke._contains_attention_target({"attention": "bad"}, "target") is False
    assert (
        smoke._contains_attention_target(
            {"attention": [{"target_ref": {"target_id": "target"}}]},
            "target",
        )
        is True
    )
    assert (
        smoke._contains_attention_target(
            {"attention": {"items": [{"target_ref": {"target_id": "target"}}]}},
            "target",
        )
        is True
    )
    assert (
        smoke._contains_attention_target(
            {"attention": {"items": [{"target_ref": {"target_id": "other"}}]}},
            "target",
        )
        is False
    )
    assert smoke._regclass_matches("public.ag_op_cases", "ag_op_cases") is True
    assert smoke._regclass_matches(None, "ag_op_cases") is False


def test_ag_operator_review_case_db_observations() -> None:
    class FakeScalarResult:
        def scalar(self) -> str:
            return "public.ag_op_cases"

    class FakeMappingResult:
        def mappings(self) -> "FakeMappingResult":
            return self

        def one(self) -> dict[str, Any]:
            return {
                "case_count": 1,
                "operator_ref_type": "jsonb",
                "source_ref_type": "jsonb",
                "assignment_ref_type": "jsonb",
                "reason_codes_type": "jsonb",
                "metadata_type": "jsonb",
                "assigned_case_count": 1,
                "urgent_case_count": 1,
                "last_action_assign_count": 1,
                "assignee_count": 1,
            }

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, params: object | None = None) -> object:
            return FakeMappingResult() if params is not None else FakeScalarResult()

    class FakeObservationEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

    assert smoke._db_observations(FakeObservationEngine(), "target") == {
        "table_present": True,
        "case_count": 1,
        "jsonb_columns": {
            "operator_ref": "jsonb",
            "source_ref": "jsonb",
            "assignment_ref": "jsonb",
            "reason_codes": "jsonb",
            "metadata": "jsonb",
        },
        "assigned_case_count": 1,
        "urgent_case_count": 1,
        "last_action_assign_count": 1,
        "assignee_count": 1,
    }


def test_ag_operator_review_case_cleanup_helpers() -> None:
    assert smoke._cleanup_case_rows(object(), None, None) == {"cases": 0}

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

    assert smoke._cleanup_case_rows(ExplodingEngine(), "case", "target") == {
        "cases": 0
    }

    class Result:
        rowcount = 1

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

    assert smoke._cleanup_case_rows(WorkingEngine(), "case", "target") == {"cases": 1}
    assert smoke._cleanup_case_rows(WorkingEngine(), "case", None) == {"cases": 1}
    assert smoke._cleanup_case_rows(WorkingEngine(), None, "target") == {"cases": 1}


def test_ag_operator_review_case_smoke_helpers_and_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_case_postgres_smoke",
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
    assert smoke._service_headers(
        request_id="request",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )["Authorization"].startswith("Bearer ")
    assert smoke.main(["--summary"]) == 0
    assert (
        "ag_operator_review_case_postgres_smoke=skipped"
        in capsys.readouterr().out
    )


def _passing_observations() -> dict[str, Any]:
    return {
        "table_present": True,
        "case_count": 1,
        "jsonb_columns": {
            "operator_ref": "jsonb",
            "source_ref": "jsonb",
            "assignment_ref": "jsonb",
            "reason_codes": "jsonb",
            "metadata": "jsonb",
        },
        "assigned_case_count": 1,
        "urgent_case_count": 1,
        "last_action_assign_count": 1,
        "assignee_count": 1,
    }
