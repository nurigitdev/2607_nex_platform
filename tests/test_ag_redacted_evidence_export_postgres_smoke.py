from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ag_redacted_evidence_export_postgres_smoke as smoke
from nex_ag.operator_reviews import OperatorEvidenceExportStore, OperatorReviewNoteError
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_ag_redacted_evidence_export_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ag_redacted_evidence_export_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ag_redacted_evidence_export_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ag_redacted_evidence_export_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_redacted_evidence_export_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"
    assert smoke.summary_line(evidence) == (
        "ag_redacted_evidence_export_postgres_smoke=fail "
        "reason=database_url_missing"
    )


def test_ag_redacted_evidence_export_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ag_redacted_evidence_export_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_ag_redacted_evidence_export_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    fake_store = OperatorEvidenceExportStore()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=("0626_ag_redacted_evidence_export_persistence",),
            applied=("0626_ag_redacted_evidence_export_persistence",),
            skipped=(),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorEvidenceExportStore",
        lambda session_factory: fake_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda engine, export_id: {
            "table_present": True,
            "row_count": 1,
            "jsonb_columns": {
                "operator_ref": "jsonb",
                "evidence_manifest": "jsonb",
                "metadata": "jsonb",
            },
            "metadata_idempotency_hash_present": True,
            "metadata_raw_idempotency_absent": True,
            "manifest_raw_payloads_excluded": True,
            "manifest_storage_paths_excluded": True,
            "evidence_item_count": 2,
            "evidence_hash_shape": True,
        },
    )
    monkeypatch.setattr(smoke, "_cleanup_evidence_export", lambda engine, export_id: 1)
    raw_url = "postgresql://nex_ag_user:secret@localhost/nex_ag_test"

    evidence = smoke.run_ag_redacted_evidence_export_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: raw_url,
        }
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == smoke.DATABASE_ENV
    assert evidence["checks"]["manifest_raw_payloads_excluded"] is True
    assert evidence["cleanup"]["deleted_rows"] == 1
    assert fake_engine.disposed is True
    assert raw_url not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert smoke.RAW_EVIDENCE_BODY not in serialized
    assert "ag-ev-export-smoke-idem" not in serialized
    assert smoke.summary_line(evidence).startswith(
        "ag_redacted_evidence_export_postgres_smoke=pass"
    )


def test_ag_redacted_evidence_export_postgres_smoke_reports_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=("0626_ag_redacted_evidence_export_persistence",),
            applied=(),
            skipped=("0626_ag_redacted_evidence_export_persistence",),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())

    class FailingStore(OperatorEvidenceExportStore):
        def get(self, export_id: str) -> dict[str, Any] | None:
            raise OperatorReviewNoteError(
                status_code=503,
                error_code="ag.evidence_export_store_unavailable",
                detail="store down",
            )

    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorEvidenceExportStore",
        lambda session_factory: FailingStore(),
    )

    evidence = smoke.run_ag_redacted_evidence_export_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert fake_engine.disposed is True


def test_ag_redacted_evidence_export_postgres_smoke_reports_exception_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=("0626_ag_redacted_evidence_export_persistence",),
            applied=(),
            skipped=("0626_ag_redacted_evidence_export_persistence",),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(
        smoke,
        "_smoke_payload",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("bad payload")),
    )

    evidence = smoke.run_ag_redacted_evidence_export_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "bad payload"
    assert fake_engine.disposed is True


def test_ag_redacted_evidence_export_redaction_guard_rejects_sensitive_values() -> None:
    with pytest.raises(ValueError, match="raw DB URL"):
        smoke.assert_smoke_evidence_redacted(
            "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
            {
                smoke.DATABASE_ENV: (
                    "postgresql://nex_ag_user:secret@localhost/nex_ag_test"
                )
            },
            raw_evidence_body="safe evidence body",
            idempotency_key="safe-idem",
        )
    with pytest.raises(ValueError, match="raw body"):
        smoke.assert_smoke_evidence_redacted(
            "raw body leaked",
            {},
            raw_evidence_body="raw body leaked",
            idempotency_key="safe-idem",
        )
    with pytest.raises(ValueError, match="raw idempotency key"):
        smoke.assert_smoke_evidence_redacted(
            "idem leaked",
            {},
            raw_evidence_body="safe evidence body",
            idempotency_key="idem leaked",
        )


def test_ag_redacted_evidence_export_db_observations_handles_missing_row() -> None:
    class FakeScalarResult:
        def scalar(self) -> str:
            return "ag_ev_exports"

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
            "operator_ref": None,
            "evidence_manifest": None,
            "metadata": None,
        },
        "metadata_idempotency_hash_present": False,
        "metadata_raw_idempotency_absent": False,
        "manifest_raw_payloads_excluded": False,
        "manifest_storage_paths_excluded": False,
        "evidence_item_count": 0,
        "evidence_hash_shape": False,
    }


def test_ag_redacted_evidence_export_cleanup_ignores_sqlalchemy_errors() -> None:
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

    assert smoke._cleanup_evidence_export(ExplodingEngine(), "export") == 0


def test_ag_redacted_evidence_export_cleanup_returns_deleted_row_count() -> None:
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

    assert smoke._cleanup_evidence_export(WorkingEngine(), "export") == 1


def test_ag_redacted_evidence_export_smoke_helpers_and_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_redacted_evidence_export_postgres_smoke",
        lambda: {"smoke_schema_version": smoke.SCHEMA_VERSION, "status": "SKIPPED"},
    )

    assert smoke._smoke_payload(suffix="abc", target_id="target")[
        "target_ref"
    ] == {
        "target_service": "nex-ag",
        "target_kind": "redacted_evidence_export_smoke",
        "target_id": "target",
    }
    assert "Idempotency-Key" not in smoke._admin_headers(
        request_id="request",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    assert smoke.main(["--summary"]) == 0
    assert "ag_redacted_evidence_export_postgres_smoke=skipped" in (
        capsys.readouterr().out
    )
