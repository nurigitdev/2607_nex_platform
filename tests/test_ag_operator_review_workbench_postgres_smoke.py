from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ag_operator_review_workbench_postgres_smoke as smoke
from nex_ag.operator_reviews import (
    OperatorEvidenceExportStore,
    OperatorReviewNoteStore,
)
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_ag_operator_review_workbench_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ag_operator_review_workbench_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_workbench_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ag_operator_review_workbench_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_operator_review_workbench_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_workbench_postgres_smoke=fail "
        "reason=database_url_missing"
    )


def test_ag_operator_review_workbench_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ag_operator_review_workbench_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_ag_operator_review_workbench_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    note_store = OperatorReviewNoteStore()
    export_store = OperatorEvidenceExportStore()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=(
                "0622_ag_operator_review_note_persistence",
                "0626_ag_redacted_evidence_export_persistence",
            ),
            applied=("0638_ag_operator_review_workbench_smoke",),
            skipped=(),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewNoteStore",
        lambda session_factory: note_store,
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorEvidenceExportStore",
        lambda session_factory: export_store,
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda engine, target_id: _passing_observations(),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_workbench_rows",
        lambda engine, operator_note_id, export_id: {"notes": 1, "exports": 1},
    )
    raw_url = "postgresql://nex_ag_user:secret@localhost/nex_ag_test"

    evidence = smoke.run_ag_operator_review_workbench_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: raw_url,
        }
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == smoke.DATABASE_ENV
    assert evidence["checks"]["workbench_target_count"] is True
    assert evidence["checks"]["dashboard_workbench_visible"] is True
    assert evidence["checks"]["issue_candidate_visible"] is True
    assert evidence["cleanup"] == {"notes": 1, "exports": 1}
    assert fake_engine.disposed is True
    assert raw_url not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert smoke.RAW_NOTE not in serialized
    assert "ag-op-workbench-note-idem" not in serialized
    assert "ag-op-workbench-export-idem" not in serialized
    assert smoke.summary_line(evidence).startswith(
        "ag_operator_review_workbench_postgres_smoke=pass"
    )


def test_ag_operator_review_workbench_postgres_smoke_reports_failed_checks(
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
            skipped=("0638_ag_operator_review_workbench_smoke",),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
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
        "_db_observations",
        lambda engine, target_id: {**_passing_observations(), "note_count": 0},
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_workbench_rows",
        lambda engine, operator_note_id, export_id: {"notes": 1, "exports": 1},
    )

    evidence = smoke.run_ag_operator_review_workbench_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["table_rows"] is False
    assert fake_engine.disposed is True


def test_ag_operator_review_workbench_postgres_smoke_reports_exception_failure(
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
            skipped=("0638_ag_operator_review_workbench_smoke",),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(
        smoke,
        "_note_payload",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("bad payload")),
    )

    evidence = smoke.run_ag_operator_review_workbench_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "bad payload"
    assert fake_engine.disposed is True


def test_ag_operator_review_workbench_postgres_smoke_reports_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=(),
            applied=(),
            skipped=("0638_ag_operator_review_workbench_smoke",),
        ),
    )
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url: (_ for _ in ()).throw(SQLAlchemyError("engine down")),
    )

    evidence = smoke.run_ag_operator_review_workbench_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "engine down"


def test_ag_operator_review_workbench_redaction_guard_rejects_sensitive_values() -> None:
    with pytest.raises(ValueError, match="raw DB URL"):
        smoke.assert_smoke_evidence_redacted(
            "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
            {
                smoke.DATABASE_ENV: (
                    "postgresql://nex_ag_user:secret@localhost/nex_ag_test"
                )
            },
            raw_note="safe note",
            idempotency_keys=("safe-note-idem", "safe-export-idem"),
        )
    with pytest.raises(ValueError, match="raw note text"):
        smoke.assert_smoke_evidence_redacted(
            "raw note leaked",
            {},
            raw_note="raw note leaked",
            idempotency_keys=("safe-note-idem", "safe-export-idem"),
        )
    with pytest.raises(ValueError, match="raw idempotency key"):
        smoke.assert_smoke_evidence_redacted(
            "export idem leaked",
            {},
            raw_note="safe note",
            idempotency_keys=("safe-note-idem", "export idem leaked"),
        )


def test_ag_operator_review_workbench_helper_branches() -> None:
    assert smoke._matches_expected_filters("bad", {"target_service": "nex-ag"}) is False
    assert (
        smoke._matches_expected_filters(
            {"target_service": "nex-ag"},
            {"target_service": "nex-ag"},
        )
        is True
    )
    assert smoke._first_attention_status({"attention": "bad"}) is None
    assert smoke._first_attention_status({"attention": {"items": []}}) is None
    assert smoke._first_attention_status({"attention": {"items": ["bad"]}}) is None
    assert (
        smoke._first_attention_status(
            {"attention": {"items": [{"attention_status": "BLOCKED"}]}}
        )
        == "BLOCKED"
    )
    assert smoke._regclass_matches("public.ag_op_notes", "ag_op_notes") is True
    assert smoke._regclass_matches(None, "ag_op_notes") is False


def test_ag_operator_review_workbench_db_observations() -> None:
    class FakeScalarResult:
        def __init__(self, value: str) -> None:
            self.value = value

        def scalar(self) -> str:
            return self.value

    class FakeMappingResult:
        def mappings(self) -> "FakeMappingResult":
            return self

        def one(self) -> dict[str, Any]:
            return {
                "note_count": 1,
                "export_count": 1,
                "note_operator_ref_type": "jsonb",
                "export_operator_ref_type": "jsonb",
                "evidence_manifest_type": "jsonb",
                "failed_export_count": 1,
                "active_high_note_count": 1,
            }

    class FakeConnection:
        def __init__(self) -> None:
            self.scalar_calls = 0

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, params: object | None = None) -> object:
            if params is not None:
                return FakeMappingResult()
            self.scalar_calls += 1
            table = "public.ag_op_notes" if self.scalar_calls == 1 else "ag_ev_exports"
            return FakeScalarResult(table)

    class FakeObservationEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

    assert smoke._db_observations(FakeObservationEngine(), "target") == {
        "tables_present": {
            "ag_op_notes": True,
            "ag_ev_exports": True,
        },
        "note_count": 1,
        "export_count": 1,
        "jsonb_columns": {
            "note_operator_ref": "jsonb",
            "export_operator_ref": "jsonb",
            "evidence_manifest": "jsonb",
        },
        "failed_export_count": 1,
        "active_high_note_count": 1,
    }


def test_ag_operator_review_workbench_cleanup_helpers() -> None:
    assert smoke._cleanup_workbench_rows(object(), None, None) == {
        "notes": 0,
        "exports": 0,
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

    assert smoke._cleanup_workbench_rows(ExplodingEngine(), "note", "export") == {
        "notes": 0,
        "exports": 0,
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

    working_engine = WorkingEngine()
    assert smoke._cleanup_workbench_rows(working_engine, "note", "export") == {
        "notes": 1,
        "exports": 1,
    }
    assert smoke._cleanup_workbench_rows(working_engine, "note", None) == {
        "notes": 1,
        "exports": 0,
    }
    assert smoke._cleanup_workbench_rows(working_engine, None, "export") == {
        "notes": 0,
        "exports": 1,
    }


def test_ag_operator_review_workbench_smoke_helpers_and_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_workbench_postgres_smoke",
        lambda: {"smoke_schema_version": smoke.SCHEMA_VERSION, "status": "SKIPPED"},
    )

    assert smoke._note_payload(suffix="abc", target_id="target")["target_ref"][
        "target_id"
    ] == "target"
    assert smoke._export_payload(suffix="abc", target_id="target")[
        "export_status"
    ] == "FAILED"
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
        "ag_operator_review_workbench_postgres_smoke=skipped"
        in capsys.readouterr().out
    )


def _passing_observations() -> dict[str, Any]:
    return {
        "tables_present": {
            "ag_op_notes": True,
            "ag_ev_exports": True,
        },
        "note_count": 1,
        "export_count": 1,
        "jsonb_columns": {
            "note_operator_ref": "jsonb",
            "export_operator_ref": "jsonb",
            "evidence_manifest": "jsonb",
        },
        "failed_export_count": 1,
        "active_high_note_count": 1,
    }
