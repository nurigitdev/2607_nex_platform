from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ag_generation_remediation_postgres_smoke as smoke
from nex_ag.generation_remediation import GenerationRemediationError
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class FakeRemediationStore:
    def __init__(self) -> None:
        self.record: dict[str, Any] | None = None
        self.deleted: list[str] = []

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.record = record
        return record

    def get(self, remediation_action_id: str) -> dict[str, Any] | None:
        if self.record and self.record["remediation_action_id"] == remediation_action_id:
            return self.record
        return None

    def list_for_generation(self, cx_generation_id: str) -> list[dict[str, Any]]:
        if self.record and self.record["cx_generation_id"] == cx_generation_id:
            return [self.record]
        return []

    def delete(self, remediation_action_id: str) -> int:
        self.deleted.append(remediation_action_id)
        return 1


def test_ag_remediation_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ag_generation_remediation_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ag_generation_remediation_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ag_remediation_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_generation_remediation_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"
    assert smoke.summary_line(evidence) == (
        "ag_generation_remediation_postgres_smoke=fail "
        "reason=database_url_missing"
    )


def test_ag_remediation_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ag_generation_remediation_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_ag_remediation_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    fake_store = FakeRemediationStore()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=("0345_ag_generation_remediation_task_persistence",),
            applied=("0345_ag_generation_remediation_task_persistence",),
            skipped=(),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyGenerationRemediationTaskStore",
        lambda session_factory: fake_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda engine, remediation_action_id: {
            "table_present": True,
            "row_count": 1,
            "jsonb_columns": dict(smoke.EXPECTED_JSONB_COLUMNS),
            "index_names": sorted(smoke.EXPECTED_INDEXES),
        },
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_remediation_task",
        lambda engine, remediation_action_id: None,
    )
    raw_url = "postgresql://nex_ag_user:secret@localhost/nex_ag_test"

    evidence = smoke.run_ag_generation_remediation_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: raw_url,
        }
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == smoke.DATABASE_ENV
    assert evidence["checks"]["jsonb_columns"] is True
    assert evidence["checks"]["indexes_present"] is True
    assert evidence["checks"]["result_ref_round_tripped"] is True
    assert evidence["cleanup"]["deleted_rows"] == 1
    assert fake_engine.disposed is True
    assert raw_url not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert "raw_generation_output" not in fake_store.record
    assert smoke.summary_line(evidence).startswith(
        "ag_generation_remediation_postgres_smoke=pass"
    )


def test_ag_remediation_postgres_smoke_reports_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=("0345_ag_generation_remediation_task_persistence",),
            applied=(),
            skipped=("0345_ag_generation_remediation_task_persistence",),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())

    class FailingRemediationStore(FakeRemediationStore):
        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            raise GenerationRemediationError(
                status_code=503,
                error_code="ag.generation_remediation_store_unavailable",
                detail="store down",
            )

    monkeypatch.setattr(
        smoke,
        "SqlAlchemyGenerationRemediationTaskStore",
        lambda session_factory: FailingRemediationStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_remediation_task",
        lambda engine, remediation_action_id: None,
    )

    evidence = smoke.run_ag_generation_remediation_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "store down"
    assert fake_engine.disposed is True


def test_ag_remediation_smoke_redaction_guard_rejects_raw_url() -> None:
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
            {
                smoke.DATABASE_ENV: (
                    "postgresql://nex_ag_user:secret@localhost/nex_ag_test"
                )
            },
        )


def test_ag_remediation_db_observations_handles_missing_row() -> None:
    class FakeScalarResult:
        def scalar(self) -> str:
            return "ag_generation_remediation_tasks"

    class FakeMappingResult:
        def mappings(self) -> "FakeMappingResult":
            return self

        def first(self) -> None:
            return None

    class FakeIndexResult:
        def mappings(self) -> "FakeIndexResult":
            return self

        def all(self) -> list[dict[str, str]]:
            return [{"indexname": "idx_ag_generation_remediation_tasks_generation_time"}]

    class FakeConnection:
        def __init__(self) -> None:
            self.execute_count = 0

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, params: object | None = None) -> object:
            self.execute_count += 1
            if self.execute_count == 1:
                return FakeScalarResult()
            if self.execute_count == 2:
                return FakeMappingResult()
            return FakeIndexResult()

    class FakeObservationEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

    assert smoke._db_observations(FakeObservationEngine(), "missing") == {
        "table_present": True,
        "row_count": 0,
        "jsonb_columns": {
            "owner_ref": None,
            "reason_codes": None,
            "source_refs": None,
            "evidence": None,
            "result_ref": None,
            "metadata": None,
        },
        "index_names": ["idx_ag_generation_remediation_tasks_generation_time"],
    }


def test_ag_remediation_cleanup_ignores_sqlalchemy_errors() -> None:
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

    smoke._cleanup_remediation_task(ExplodingEngine(), "remediation-action-id")
