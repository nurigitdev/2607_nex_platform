from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_ag_operator_review_case_lifecycle_postgres_smoke as smoke
from nex_ag.operator_review_cases import OperatorReviewCaseStore
from nex_ag.operator_reviews import OperatorEvidenceExportStore, OperatorReviewNoteStore
from nex_runtime import InMemoryOperationalEventStore
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_ag_operator_review_case_lifecycle_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ag_operator_review_case_lifecycle_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_case_lifecycle_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ag_operator_review_case_lifecycle_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_operator_review_case_lifecycle_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"


def test_ag_operator_review_case_lifecycle_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ag_operator_review_case_lifecycle_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_ag_operator_review_case_lifecycle_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=("0678_ag_operator_review_case_lifecycle_contracts",),
            applied=("0679_ag_operator_review_case_lifecycle_postgres_smoke",),
            skipped=(),
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
        "SqlAlchemyOperatorReviewNoteStore",
        lambda session_factory: OperatorReviewNoteStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorEvidenceExportStore",
        lambda session_factory: OperatorEvidenceExportStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperationalEventStore",
        lambda session_factory: InMemoryOperationalEventStore(),
    )
    monkeypatch.setattr(smoke, "_db_observations", lambda *args, **kwargs: _passing_observations())
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda *args, **kwargs: {"cases": 1, "notes": 1, "exports": 1, "events": 2},
    )
    raw_url = "postgresql://nex_ag_user:secret@localhost/nex_ag_test"

    evidence = smoke.run_ag_operator_review_case_lifecycle_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: raw_url,
        }
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == smoke.DATABASE_ENV
    assert evidence["checks"]["closure_ready"] is True
    assert evidence["checks"]["action_outcome_terminal"] is True
    assert evidence["checks"]["workload_closed_count"] is True
    assert evidence["cleanup"] == {
        "cases": 1,
        "notes": 1,
        "exports": 1,
        "events": 2,
    }
    assert fake_engine.disposed is True
    assert raw_url not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert smoke.RAW_NOTE not in serialized
    assert smoke.RAW_EXPORT_BODY not in serialized
    assert smoke.RAW_ACTION_COMMENT not in serialized
    assert smoke.RAW_RESOLUTION_COMMENT not in serialized
    assert "ag-op-case-lifecycle-create-idem" not in serialized
    assert smoke.summary_line(evidence).startswith(
        "ag_operator_review_case_lifecycle_postgres_smoke=pass"
    )


def test_ag_operator_review_case_lifecycle_postgres_smoke_reports_failed_checks(
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
            skipped=("0679_ag_operator_review_case_lifecycle_postgres_smoke",),
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
        "SqlAlchemyOperatorReviewNoteStore",
        lambda session_factory: OperatorReviewNoteStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorEvidenceExportStore",
        lambda session_factory: OperatorEvidenceExportStore(),
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
        lambda *args, **kwargs: {"cases": 1, "notes": 1, "exports": 1, "events": 0},
    )

    evidence = smoke.run_ag_operator_review_case_lifecycle_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["event_rows_persisted"] is False
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_case_lifecycle_postgres_smoke=fail "
        "reason=checks_failed"
    )


def _passing_observations() -> dict[str, object]:
    return {
        "tables_present": {
            "ag_op_cases": True,
            "ag_op_notes": True,
            "ag_ev_exports": True,
            "service_operational_events": True,
        },
        "case_count": 1,
        "note_count": 1,
        "export_count": 1,
        "event_count": 2,
        "event_details_case_count": 2,
        "raw_comment_leak_count": 0,
    }
