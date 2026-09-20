from __future__ import annotations

from contextlib import nullcontext
import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ag_audit_retention_postgres_smoke as smoke
from nex_ag.audit_retention import (
    AgAuditRetentionPolicyError,
    build_ag_audit_retention_policy,
    _sha256_json,
)
from nex_ag.audit_retention_archive import InMemoryAgArchiveReceiptStore
from nex_ag.audit_retention_purge import InMemoryAgRetentionPurgeStore
from nex_ag.operator_reviews import OperatorEvidenceExportStore
from nex_runtime import InMemoryOperationalEventStore
from run_migrations import MigrationError


DATABASE_URL = (
    "postgresql+psycopg://nex_ag_user:private@127.0.0.1:5432/nex_ag_test"
)


class _Url:
    database = "nex_ag_test"

    @staticmethod
    def get_backend_name() -> str:
        return "postgresql"


class _Engine:
    url = _Url()

    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _env() -> dict[str, str]:
    return {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}


def _migration() -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=(smoke.MIGRATION_VERSION,),
        applied=(),
        skipped=(smoke.MIGRATION_VERSION,),
    )


def _context() -> dict[str, str]:
    return {
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "request-0888-unit",
        "event_id": "event-0888-unit",
        "export_id": "export-0888-unit",
        "target_id": "target-0888-unit",
        "operator_id": "operator-0888-unit",
    }


def _observation() -> dict[str, Any]:
    return {
        "backend": "postgresql",
        "database": "nex_ag_test",
        "migration_present": True,
        "event_count": 0,
        "export_count": 0,
        "receipt_count": 2,
        "purged_receipt_count": 2,
        "indexes_present": {name: True for name in smoke.INDEX_NAMES},
        "planner_indexes": {
            "operational_event": True,
            "evidence_export": True,
        },
    }


def _policy() -> dict[str, Any]:
    return build_ag_audit_retention_policy(smoke._smoke_policy_env({}))


def test_smoke_requires_explicit_opt_in_and_database_url() -> None:
    skipped = smoke.run_ag_audit_retention_postgres_smoke({})
    missing = smoke.run_ag_audit_retention_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in skipped["skip_reason"]
    assert "smoke=skipped" in smoke.summary_line(skipped)
    assert missing["status"] == "FAIL"
    assert missing["failure_code"] == "database_url_missing"


@pytest.mark.parametrize(
    "failure",
    [MigrationError(f"cannot connect {DATABASE_URL}"), AgAuditRetentionPolicyError("x", "bad")],
)
def test_smoke_redacts_migration_or_policy_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    if isinstance(failure, MigrationError):
        monkeypatch.setattr(
            smoke,
            "run_service_migrations",
            lambda *_a, **_k: (_ for _ in ()).throw(failure),
        )
    else:
        monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
        monkeypatch.setattr(
            smoke,
            "build_ag_audit_retention_policy",
            lambda *_a, **_k: (_ for _ in ()).throw(failure),
        )

    evidence = smoke.run_ag_audit_retention_postgres_smoke(_env())

    assert evidence["failure_code"] == "migration_or_policy_failed"
    assert DATABASE_URL not in evidence["detail"]


@pytest.mark.parametrize(
    ("runtime_ok", "remaining", "expected"),
    [(True, 0, "PASS"), (False, 1, "FAIL")],
)
def test_smoke_orchestrates_cleanup_and_result(
    monkeypatch: pytest.MonkeyPatch,
    runtime_ok: bool,
    remaining: int,
    expected: str,
) -> None:
    engine = _Engine()
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(smoke, "build_engine", lambda _url: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(smoke, "SqlAlchemyOperationalEventStore", lambda _f: object())
    monkeypatch.setattr(
        smoke, "SqlAlchemyOperatorEvidenceExportStore", lambda _f: object()
    )
    monkeypatch.setattr(smoke, "SqlAlchemyAgRetentionCandidateStore", lambda _f: object())
    monkeypatch.setattr(smoke, "SqlAlchemyAgArchiveReceiptStore", lambda _f: object())
    monkeypatch.setattr(smoke, "SqlAlchemyAgRetentionPurgeStore", lambda _f: object())
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda **_kwargs: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "PENDING",
            "checks": {"runtime": runtime_ok},
        },
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_rows",
        lambda *_a, **_k: {
            "events": 0,
            "exports": 0,
            "receipts": 2,
            "remaining_rows": remaining,
        },
    )

    evidence = smoke.run_ag_audit_retention_postgres_smoke(_env())

    assert evidence["status"] == expected
    assert evidence["checks"]["owned_rows_deleted"] is (remaining == 0)
    assert engine.disposed is True


def test_smoke_cleans_up_and_redacts_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    cleanup_calls: list[dict[str, str]] = []
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(smoke, "build_engine", lambda _url: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    for name in (
        "SqlAlchemyOperationalEventStore",
        "SqlAlchemyOperatorEvidenceExportStore",
        "SqlAlchemyAgRetentionCandidateStore",
        "SqlAlchemyAgArchiveReceiptStore",
        "SqlAlchemyAgRetentionPurgeStore",
    ):
        monkeypatch.setattr(smoke, name, lambda _f: object())
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError(f"database failed {DATABASE_URL}")
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_rows",
        lambda _engine, *, context: cleanup_calls.append(dict(context)) or {},
    )

    evidence = smoke.run_ag_audit_retention_postgres_smoke(_env())

    assert evidence["failure_code"] == "smoke_execution_failed"
    assert DATABASE_URL not in evidence["detail"]
    assert len(cleanup_calls) == 1
    assert engine.disposed is True


def test_smoke_handles_engine_creation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda _url: (_ for _ in ()).throw(ValueError("engine unavailable")),
    )

    evidence = smoke.run_ag_audit_retention_postgres_smoke(_env())

    assert evidence["failure_code"] == "smoke_execution_failed"


def test_execute_smoke_covers_two_source_lifecycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    event_record = {"event_id": context["event_id"], "created_at": smoke.SOURCE_TIME}
    export_record = {
        "export_id": context["export_id"],
        "updated_at": smoke.SOURCE_TIME,
    }
    candidates = [
        {
            "candidate_schema_version": "ag_retention_candidate.v1",
            "candidate_id": smoke._sha256_text(f"{kind}:{source_id}"),
            "source_kind": kind,
            "source_id": source_id,
            "source_timestamp": smoke.SOURCE_TIME,
            "retention_days": 365,
            "retention_cutoff": "2025-09-20T12:00:00Z",
            "content_sha256": _sha256_json(record),
            "archive_required": True,
            "archive_status": "UNARCHIVED",
            "purge_eligible": False,
            "raw_payload_included": False,
        }
        for kind, source_id, record in (
            ("operational_event", context["event_id"], event_record),
            ("evidence_export", context["export_id"], export_record),
        )
    ]

    class CandidateStore:
        def list_candidates(self, **_kwargs):
            return {
                "candidate_page_schema_version": "ag_retention_candidate_page.v1",
                "policy_id": "ag-audit-retention-v1",
                "as_of": smoke.AS_OF,
                "limit": 500,
                "candidate_count": 2,
                "eligible_count": 2,
                "invalid_record_count": 0,
                "has_more": False,
                "items": candidates,
                "raw_payload_included": False,
            }

    receipt_store = InMemoryAgArchiveReceiptStore()
    purge_store = InMemoryAgRetentionPurgeStore(
        receipt_store=receipt_store,
        source_records={
            ("operational_event", context["event_id"]): event_record,
            ("evidence_export", context["export_id"]): export_record,
        },
    )
    monkeypatch.setattr(smoke, "_seed_owned_rows", lambda **_kwargs: None)
    monkeypatch.setattr(
        smoke,
        "_database_observation",
        lambda *_a, **_k: _observation(),
    )

    evidence = smoke._execute_smoke(
        engine=_Engine(),
        event_store=object(),
        export_store=object(),
        candidate_store=CandidateStore(),
        receipt_store=receipt_store,
        purge_store=purge_store,
        migration=_migration(),
        policy=_policy(),
        database_url=DATABASE_URL,
        context=context,
    )

    assert all(evidence["checks"].values())
    assert evidence["lifecycle"] == {
        "candidate_count": 2,
        "dry_run_statuses": ["ELIGIBLE", "ELIGIBLE"],
        "execute_statuses": ["PURGED", "PURGED"],
        "retry_statuses": ["NOOP", "NOOP"],
    }


def test_seed_rows_and_helper_contracts() -> None:
    events = InMemoryOperationalEventStore()
    exports = OperatorEvidenceExportStore()
    context = _context()

    smoke._seed_owned_rows(event_store=events, export_store=exports, context=context)

    assert events.events[context["event_id"]]["event_id"] == context["event_id"]
    assert exports.get(context["export_id"])["export_id"] == context["export_id"]
    selected = smoke._smoke_policy_env({"CUSTOM": "value"})
    assert selected["CUSTOM"] == "value"
    assert selected["NEX_AG_ARCHIVE_PROVIDER_MODE"] == "external"
    assert smoke._engine_backend(_Engine()) == "postgresql"
    assert smoke._engine_backend(object()) == "unknown"
    assert len(smoke._sha256_text("value")) == 64
    assert smoke._mapping({"ok": True}) == {"ok": True}
    assert smoke._mapping("bad") == {}


def test_cleanup_guards_and_failure() -> None:
    class FailingEngine(_Engine):
        def begin(self):
            raise SQLAlchemyError("transaction unavailable")

    empty = smoke._cleanup_owned_rows(
        FailingEngine(), context={"event_id": "", "export_id": ""}
    )
    failed = smoke._cleanup_owned_rows(FailingEngine(), context=_context())

    assert empty["remaining_rows"] == 0
    assert failed["remaining_rows"] == -1


def test_database_observation_and_cleanup_with_fake_connection() -> None:
    row = {
        "database_name": "nex_ag_test",
        "migration_present": True,
        "event_count": 0,
        "export_count": 0,
        "receipt_count": 2,
        "purged_receipt_count": 2,
    }

    class Result:
        def __init__(self, value: Any, *, rowcount: int = 0) -> None:
            self.value = value
            self.rowcount = rowcount

        def mappings(self):
            return self

        def one(self):
            return self.value

        def scalars(self):
            return self

        def all(self):
            return self.value

        def scalar(self):
            return self.value

    class Connection:
        def __init__(self) -> None:
            self.delete_count = 0

        def execute(self, statement, _params=None):
            sql = str(statement)
            if "SELECT current_database()" in sql:
                return Result(row)
            if "SELECT indexname FROM pg_indexes" in sql:
                return Result(list(smoke.INDEX_NAMES))
            if "SET LOCAL" in sql:
                return Result(None)
            if "EXPLAIN" in sql:
                index = smoke.INDEX_NAMES[self.delete_count]
                self.delete_count += 1
                return Result([{"Plan": {"Index Name": index}}])
            if sql.lstrip().startswith("DELETE"):
                return Result(None, rowcount=1)
            return Result(0)

    connection = Connection()

    class Engine(_Engine):
        def begin(self):
            return nullcontext(connection)

    observed = smoke._database_observation(Engine(), context=_context())
    cleaned = smoke._cleanup_owned_rows(Engine(), context=_context())

    assert observed == _observation()
    assert cleaned == {
        "events": 1,
        "exports": 1,
        "receipts": 1,
        "remaining_rows": 0,
    }


def test_evidence_redaction_rejects_secrets() -> None:
    smoke.assert_smoke_evidence_redacted("safe evidence", _env())
    for secret in (
        DATABASE_URL,
        smoke.RAW_EVENT_MESSAGE,
        smoke.RAW_EVENT_CREDENTIAL,
        smoke.RAW_EXPORT_BODY,
        smoke.RAW_OBJECT_REF_PREFIX,
        smoke.CONFIRMATION_LEAK_MARKER,
    ):
        with pytest.raises(ValueError, match="contains a secret"):
            smoke.assert_smoke_evidence_redacted(f"evidence {secret}", _env())


def test_summary_line_reports_pass_and_failure() -> None:
    passed = smoke.summary_line(
        {
            "status": "PASS",
            "observation": {
                "database": "nex_ag_test",
                "backend": "postgresql",
                "purged_receipt_count": 2,
                "indexes_present": {name: True for name in smoke.INDEX_NAMES},
            },
            "lifecycle": {"candidate_count": 2},
            "cleanup": {"remaining_rows": 0},
        }
    )
    failed = smoke.summary_line({"status": "FAIL", "failure_code": "checks_failed"})

    assert "smoke=pass" in passed
    assert "candidates=2" in passed
    assert "purged=2" in passed
    assert "smoke=fail" in failed


def test_main_prints_summary_json_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: {})
    monkeypatch.setattr(
        smoke,
        "run_ag_audit_retention_postgres_smoke",
        lambda: {"status": "SKIPPED", "skip_reason": "disabled"},
    )

    assert smoke.main(["--summary", "--env-file", "test.env"]) == 0
    assert "smoke=skipped" in capsys.readouterr().out
    assert smoke.main(["--env-file", "test.env"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SKIPPED"

    monkeypatch.setattr(
        smoke,
        "run_ag_audit_retention_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "expected"},
    )
    assert smoke.main([]) == 1
