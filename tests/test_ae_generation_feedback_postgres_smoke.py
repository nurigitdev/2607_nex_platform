from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_generation_feedback_postgres_smoke as smoke
from nex_ae_api.generation_feedback import GenerationFeedbackError
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class FakeFeedbackStore:
    def __init__(self) -> None:
        self.record: dict[str, Any] | None = None
        self.deleted: list[str] = []

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.record = record
        return record

    def get(self, feedback_id: str) -> dict[str, Any] | None:
        if self.record and self.record["feedback_id"] == feedback_id:
            return self.record
        return None

    def list_for_interaction(self, interaction_id: str) -> list[dict[str, Any]]:
        if self.record and self.record["interaction_id"] == interaction_id:
            return [self.record]
        return []

    def delete(self, feedback_id: str) -> int:
        self.deleted.append(feedback_id)
        return 1


def test_generation_feedback_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_generation_feedback_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ae_generation_feedback_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_generation_feedback_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ae_generation_feedback_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"
    assert smoke.summary_line(evidence) == (
        "ae_generation_feedback_postgres_smoke=fail "
        "reason=database_url_missing"
    )


def test_generation_feedback_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_generation_feedback_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ae_user:secret@localhost/nex_ae_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_generation_feedback_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    fake_store = FakeFeedbackStore()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=("0334_ae_generation_feedback_persistence",),
            applied=("0334_ae_generation_feedback_persistence",),
            skipped=(),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyGenerationFeedbackStore",
        lambda session_factory: fake_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda engine, feedback_id: {
            "table_present": True,
            "row_count": 1,
            "jsonb_columns": {
                "feedback_reasons": "jsonb",
                "quality_issue_refs": "jsonb",
                "metadata": "jsonb",
            },
        },
    )
    monkeypatch.setattr(smoke, "_cleanup_feedback", lambda engine, feedback_id: None)
    raw_url = "postgresql://nex_ae_user:secret@localhost/nex_ae_test"

    evidence = smoke.run_ae_generation_feedback_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: raw_url,
        }
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == smoke.DATABASE_ENV
    assert evidence["checks"]["jsonb_columns"] is True
    assert evidence["cleanup"]["deleted_rows"] == 1
    assert fake_engine.disposed is True
    assert raw_url not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert "feedback_comment" not in fake_store.record
    assert smoke.summary_line(evidence).startswith(
        "ae_generation_feedback_postgres_smoke=pass"
    )


def test_generation_feedback_postgres_smoke_reports_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=("0334_ae_generation_feedback_persistence",),
            applied=(),
            skipped=("0334_ae_generation_feedback_persistence",),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())

    class FailingFeedbackStore(FakeFeedbackStore):
        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            raise GenerationFeedbackError(
                status_code=503,
                error_code="ae.generation_feedback_store_unavailable",
                detail="store down",
            )

    monkeypatch.setattr(
        smoke,
        "SqlAlchemyGenerationFeedbackStore",
        lambda session_factory: FailingFeedbackStore(),
    )
    monkeypatch.setattr(smoke, "_cleanup_feedback", lambda engine, feedback_id: None)

    evidence = smoke.run_ae_generation_feedback_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ae_user:secret@localhost/nex_ae_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "store down"
    assert fake_engine.disposed is True


def test_generation_feedback_smoke_redaction_guard_rejects_raw_url() -> None:
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            "postgresql://nex_ae_user:secret@localhost/nex_ae_test",
            {
                smoke.DATABASE_ENV: (
                    "postgresql://nex_ae_user:secret@localhost/nex_ae_test"
                )
            },
        )


def test_generation_feedback_db_observations_handles_missing_row() -> None:
    class FakeScalarResult:
        def scalar(self) -> str:
            return "ae_generation_feedback"

    class FakeMappingResult:
        def mappings(self) -> "FakeMappingResult":
            return self

        def first(self) -> None:
            return None

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, params: object | None = None) -> object:
            return FakeScalarResult() if params is None else FakeMappingResult()

    class FakeObservationEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

    assert smoke._db_observations(FakeObservationEngine(), "missing") == {
        "table_present": True,
        "row_count": 0,
        "jsonb_columns": {
            "feedback_reasons": None,
            "quality_issue_refs": None,
            "metadata": None,
        },
    }


def test_generation_feedback_cleanup_ignores_sqlalchemy_errors() -> None:
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

    smoke._cleanup_feedback(ExplodingEngine(), "feedback-id")
