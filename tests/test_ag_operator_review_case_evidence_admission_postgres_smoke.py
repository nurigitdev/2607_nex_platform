from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ag_operator_review_case_evidence_admission_postgres_smoke as smoke
from nex_ag.operator_review_cases import OperatorReviewCaseStore
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


def test_ag_operator_review_case_evidence_admission_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ag_operator_review_case_evidence_admission_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_case_evidence_admission_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_ag_operator_review_case_evidence_admission_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_operator_review_case_evidence_admission_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"
    assert smoke.summary_line(evidence) == (
        "ag_operator_review_case_evidence_admission_postgres_smoke=fail "
        "reason=database_url_missing"
    )


def test_ag_operator_review_case_evidence_admission_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ag_operator_review_case_evidence_admission_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert "bad migration" in evidence["detail"]


def test_ag_operator_review_case_evidence_admission_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=("0667_ag_operator_review_case_evidence_admission_contracts",),
            applied=("0668_ag_operator_review_case_evidence_admission_postgres_smoke",),
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
    monkeypatch.setattr(smoke, "_db_observations", lambda *args, **kwargs: _passing_observations())
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda *args, **kwargs: {"cases": 1, "notes": 1, "exports": 1},
    )
    raw_url = "postgresql://nex_ag_user:secret@localhost/nex_ag_test"

    evidence = smoke.run_ag_operator_review_case_evidence_admission_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: raw_url,
        }
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == smoke.DATABASE_ENV
    assert evidence["checks"]["detail_action_admission_linked"] is True
    assert evidence["checks"]["evidence_export_count"] is True
    assert evidence["checks"]["admission_requested_admitted"] is True
    assert evidence["cleanup"] == {"cases": 1, "notes": 1, "exports": 1}
    assert fake_engine.disposed is True
    assert raw_url not in serialized
    assert "secret" not in evidence["redacted_database_url"]
    assert smoke.RAW_NOTE not in serialized
    assert smoke.RAW_EXPORT_BODY not in serialized
    assert "ag-op-case-evidence-admission-idem" not in serialized
    assert smoke.summary_line(evidence).startswith(
        "ag_operator_review_case_evidence_admission_postgres_smoke=pass"
    )


def test_ag_operator_review_case_evidence_admission_postgres_smoke_reports_failed_checks(
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
            skipped=("0667_ag_operator_review_case_evidence_admission_contracts",),
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
        "_db_observations",
        lambda *args, **kwargs: {**_passing_observations(), "note_count": 0},
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda *args, **kwargs: {"cases": 1, "notes": 0, "exports": 1},
    )

    evidence = smoke.run_ag_operator_review_case_evidence_admission_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["note_row_persisted"] is False
    assert fake_engine.disposed is True


def test_ag_operator_review_case_evidence_admission_postgres_smoke_reports_exception_failure(
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
            skipped=("0667_ag_operator_review_case_evidence_admission_contracts",),
        ),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "_case_payload", lambda **kwargs: _raise_value_error())

    evidence = smoke.run_ag_operator_review_case_evidence_admission_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "bad payload"
    assert fake_engine.disposed is True


def test_ag_operator_review_case_evidence_admission_postgres_smoke_reports_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=(),
            applied=(),
            skipped=("0667_ag_operator_review_case_evidence_admission_contracts",),
        ),
    )
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url: (_ for _ in ()).throw(SQLAlchemyError("engine down")),
    )

    evidence = smoke.run_ag_operator_review_case_evidence_admission_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "engine down"


def test_ag_operator_review_case_evidence_admission_redaction_guard_rejects_sensitive_values() -> None:
    with pytest.raises(ValueError, match="raw DB URL"):
        smoke.assert_smoke_evidence_redacted(
            "postgresql://nex_ag_user:secret@localhost/nex_ag_test",
            {
                smoke.DATABASE_ENV: (
                    "postgresql://nex_ag_user:secret@localhost/nex_ag_test"
                )
            },
            raw_values=("safe",),
        )
    with pytest.raises(ValueError, match="raw sensitive value"):
        smoke.assert_smoke_evidence_redacted(
            "raw value leaked",
            {},
            raw_values=("raw value leaked",),
        )


def test_ag_operator_review_case_evidence_admission_helpers() -> None:
    payload = smoke._case_payload(suffix="abc", target_id="target")
    assert payload["target_ref"]["target_id"] == "target"
    note = smoke._note_record(
        operator_note_id="note",
        suffix="abc",
        request_id="request",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        target_id="target",
    )
    export = smoke._export_record(
        export_id="export",
        suffix="abc",
        request_id="request",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        target_id="target",
    )
    assert note["operator_note_id"] == "note"
    assert export["export_id"] == "export"
    assert smoke.RAW_NOTE not in str(note)
    assert smoke.RAW_EXPORT_BODY not in str(export)
    assert "Idempotency-Key" not in smoke._admin_headers(
        request_id="request",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    assert smoke._redaction_flags_are_false("bad", ("flag",)) is False
    assert smoke._redaction_flags_are_false({"flag": True}, ("flag",)) is False
    assert smoke._redaction_flags_are_false({"flag": False}, ("flag",)) is True
    assert smoke._regclass_matches("public.ag_op_notes", "ag_op_notes") is True
    assert smoke._regclass_matches(None, "ag_op_notes") is False
    assert smoke._cleanup_where(
        id_column="case_id",
        id_value="case",
        target_id="target",
    ) == (
        "case_id = :id_value OR target_id = :target_id",
        {"id_value": "case", "target_id": "target"},
    )
    assert len(smoke._sha256_text("value")) == 64


def test_ag_operator_review_case_evidence_admission_db_observations() -> None:
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
                "note_count": 1,
                "export_count": 1,
                "case_metadata_type": "jsonb",
                "note_metadata_type": "jsonb",
                "export_manifest_type": "jsonb",
                "export_metadata_type": "jsonb",
                "raw_payload_leak_count": 0,
            }

    class FakeConnection:
        def __init__(self) -> None:
            self._scalar_values = [
                "public.ag_op_cases",
                "public.ag_op_notes",
                "public.ag_ev_exports",
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
        case_id="case",
        target_id="target",
        operator_note_id="note",
        export_id="export",
    ) == _passing_observations()


def test_ag_operator_review_case_evidence_admission_cleanup_helpers() -> None:
    assert smoke._cleanup_smoke_rows(
        object(),
        case_id=None,
        target_id=None,
        operator_note_id=None,
        export_id=None,
    ) == {"cases": 0, "notes": 0, "exports": 0}

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
        case_id="case",
        target_id="target",
        operator_note_id="note",
        export_id="export",
    ) == {"cases": 0, "notes": 0, "exports": 0}

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

    assert smoke._cleanup_smoke_rows(
        WorkingEngine(),
        case_id="case",
        target_id="target",
        operator_note_id="note",
        export_id="export",
    ) == {"cases": 1, "notes": 1, "exports": 1}
    assert smoke._cleanup_smoke_rows(
        WorkingEngine(),
        case_id="case",
        target_id=None,
        operator_note_id=None,
        export_id=None,
    ) == {"cases": 1, "notes": 0, "exports": 0}


def test_ag_operator_review_case_evidence_admission_smoke_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_case_evidence_admission_postgres_smoke",
        lambda: {"smoke_schema_version": smoke.SCHEMA_VERSION, "status": "SKIPPED"},
    )

    assert smoke.main(["--summary"]) == 0
    assert (
        "ag_operator_review_case_evidence_admission_postgres_smoke=skipped"
        in capsys.readouterr().out
    )


def _passing_observations() -> dict[str, Any]:
    return {
        "tables_present": {
            "ag_op_cases": True,
            "ag_op_notes": True,
            "ag_ev_exports": True,
        },
        "case_count": 1,
        "note_count": 1,
        "export_count": 1,
        "jsonb_columns": {
            "case_metadata": "jsonb",
            "note_metadata": "jsonb",
            "export_manifest": "jsonb",
            "export_metadata": "jsonb",
        },
        "raw_payload_leak_count": 0,
    }


def _raise_value_error() -> None:
    raise ValueError("bad payload")
