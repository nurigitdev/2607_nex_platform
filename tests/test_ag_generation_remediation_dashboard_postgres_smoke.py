from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ag_generation_remediation_dashboard_postgres_smoke as smoke
from nex_ag.generation_remediation import GenerationRemediationError
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class FakeRemediationStore:
    source_kind = "postgres"
    database_env = smoke.DATABASE_ENV
    redacted_database_url = "postgresql://nex_ag_user:***@localhost/nex_ag_test"

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.deleted: list[str] = []

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[str(record["remediation_action_id"])] = record
        return record

    def list_recent(self, *, limit: int = 500) -> list[dict[str, Any]]:
        records = list(self.records.values())
        records.sort(key=lambda record: str(record.get("updated_at") or ""), reverse=True)
        return records[:limit]

    def delete(self, remediation_action_id: str) -> int:
        self.deleted.append(remediation_action_id)
        return 1 if self.records.pop(remediation_action_id, None) else 0


def test_ag_remediation_dashboard_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ag_generation_remediation_dashboard_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ag_generation_remediation_dashboard_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ag_remediation_dashboard_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_generation_remediation_dashboard_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"
    assert smoke.summary_line(evidence) == (
        "ag_generation_remediation_dashboard_postgres_smoke=fail "
        "reason=database_url_missing"
    )


def test_ag_remediation_dashboard_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ag_generation_remediation_dashboard_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_ag_remediation_dashboard_postgres_smoke_success_is_redacted(
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
        lambda *args, **kwargs: fake_store,
    )
    monkeypatch.setattr(smoke, "_db_row_count", lambda engine, action_ids: 3)
    monkeypatch.setattr(
        smoke,
        "_cleanup_remediation_tasks",
        lambda engine, action_ids: 0,
    )
    raw_url = "postgresql://nex_ag_user:secret@localhost/nex_ag_test"

    evidence = smoke.run_ag_generation_remediation_dashboard_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: raw_url,
        }
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == smoke.DATABASE_ENV
    assert evidence["checks"]["recent_contains_smoke_tasks"] is True
    assert evidence["checks"]["issue_candidate_failed_signal"] is True
    assert evidence["cleanup"]["deleted_rows"] == 3
    assert len(fake_store.deleted) == 3
    assert fake_engine.disposed is True
    assert raw_url not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert smoke.summary_line(evidence).startswith(
        "ag_generation_remediation_dashboard_postgres_smoke=pass"
    )


def test_ag_remediation_dashboard_postgres_smoke_reports_execution_failure(
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
        lambda *args, **kwargs: FailingRemediationStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_remediation_tasks",
        lambda engine, action_ids: 0,
    )

    evidence = smoke.run_ag_generation_remediation_dashboard_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "store down"
    assert fake_engine.disposed is True


def test_ag_remediation_dashboard_smoke_helpers_are_defensive() -> None:
    class BadJsonResponse:
        def json(self) -> object:
            raise ValueError("not json")

    class ListJsonResponse:
        def json(self) -> object:
            return []

    assert smoke._json_or_empty(BadJsonResponse()) == {}
    assert smoke._json_or_empty(ListJsonResponse()) == {}
    assert smoke._item_ids("bad") == []
    assert smoke._item_ids(
        [
            {"remediation_action_id": "ag-remediation-001"},
            {"missing": "id"},
            "bad",
        ]
    ) == ["ag-remediation-001"]
    assert smoke._first_remediation_issue_candidate("bad") is None
    assert smoke._first_remediation_issue_candidate(
        [
            {"rule_id": "other"},
            {"rule_id": "generation_remediation_attention_required.v1"},
        ]
    ) == {"rule_id": "generation_remediation_attention_required.v1"}


def test_ag_remediation_dashboard_smoke_db_helpers() -> None:
    class ScalarResult:
        rowcount = 1

        def scalar(self) -> int:
            return 1

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, *args: object, **kwargs: object) -> ScalarResult:
            return ScalarResult()

    class RowCountEngine:
        def connect(self) -> Connection:
            return Connection()

    class CleanupEngine:
        def begin(self) -> Connection:
            return Connection()

    class FailingCleanupConnection(Connection):
        def __enter__(self) -> "FailingCleanupConnection":
            raise SQLAlchemyError("cleanup down")

    class FailingCleanupEngine:
        def begin(self) -> FailingCleanupConnection:
            return FailingCleanupConnection()

    assert smoke._db_row_count(RowCountEngine(), ["a", "b"]) == 2
    assert smoke._db_row_count(RowCountEngine(), []) == 0
    assert smoke._cleanup_remediation_tasks(CleanupEngine(), ["a", "b"]) == 2
    assert smoke._cleanup_remediation_tasks(FailingCleanupEngine(), ["a"]) == 0
    assert smoke._redact_detail(
        "failed postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
    ) == "failed postgresql://nex_ag_user:***@localhost/nex_ag_test"


def test_ag_remediation_dashboard_smoke_redaction_guard_rejects_raw_url() -> None:
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
            {
                smoke.DATABASE_ENV: (
                    "postgresql://nex_ag_user:secret@localhost/nex_ag_test"
                )
            },
        )
