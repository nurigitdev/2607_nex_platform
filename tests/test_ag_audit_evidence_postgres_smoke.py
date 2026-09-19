from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ag_audit_evidence_postgres_smoke as smoke
from nex_ag.operator_reviews import OperatorEvidenceExportStore
from nex_runtime import InMemoryOperationalEventStore
from run_migrations import MigrationError


DATABASE_URL = (
    "postgresql+psycopg://nex_ag_user:private@127.0.0.1:5432/nex_ag_test"
)


class FakeUrl:
    database = "nex_ag_test"

    @staticmethod
    def get_backend_name() -> str:
        return "postgresql"


class FakeEngine:
    url = FakeUrl()

    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: DATABASE_URL,
    }


def _migration() -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=("0001",),
        applied=(),
        skipped=("0001",),
    )


def _context() -> dict[str, str]:
    return {
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "request-0868-unit",
        "source_event_id": "event-0868-unit",
        "export_id": "export-0868-unit",
        "target_id": "target-0868-unit",
        "idempotency_key": "idempotency-0868-unit",
        "operator_id": "operator-0868-unit",
    }


def _observation() -> dict[str, Any]:
    return {
        "backend": "postgresql",
        "database": "nex_ag_test",
        "tables_present": {
            "service_operational_events": True,
            "ag_ev_exports": True,
        },
        "package_table_absent": True,
        "event_count": 3,
        "source_event_count": 1,
        "generated_event_count": 1,
        "verified_event_count": 1,
        "package_event_count": 2,
        "export_count": 1,
        "hash_ready_export_count": 1,
    }


def test_smoke_skips_without_opt_in() -> None:
    evidence = smoke.run_ag_audit_evidence_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert "smoke=skipped" in smoke.summary_line(evidence)


def test_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_audit_evidence_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"


def test_smoke_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MigrationError(f"cannot connect {DATABASE_URL}")
        ),
    )

    evidence = smoke.run_ag_audit_evidence_postgres_smoke(_env())

    assert evidence["failure_code"] == "migration_failed"
    assert DATABASE_URL not in evidence["detail"]
    assert "***" in evidence["detail"]


@pytest.mark.parametrize(
    ("runtime_check", "remaining_rows", "expected_status"),
    [(True, 0, "PASS"), (False, 1, "FAIL")],
)
def test_smoke_orchestrates_result_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    runtime_check: bool,
    remaining_rows: int,
    expected_status: str,
) -> None:
    engine = FakeEngine()
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(smoke, "build_engine", lambda _url: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(smoke, "SqlAlchemyOperationalEventStore", lambda _f: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorEvidenceExportStore",
        lambda _f: object(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda *_a, **_k: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "PENDING",
            "checks": {"runtime": runtime_check},
        },
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_rows",
        lambda *_a, **_k: {
            "events": 3,
            "exports": 1,
            "remaining_rows": remaining_rows,
        },
    )

    evidence = smoke.run_ag_audit_evidence_postgres_smoke(_env())

    assert evidence["status"] == expected_status
    assert evidence["checks"]["owned_rows_deleted"] is (remaining_rows == 0)
    assert engine.disposed is True


def test_smoke_cleans_up_and_redacts_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    cleanup_calls: list[dict[str, str]] = []
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(smoke, "build_engine", lambda _url: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(smoke, "SqlAlchemyOperationalEventStore", lambda _f: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorEvidenceExportStore",
        lambda _f: object(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda *_a, **_k: (_ for _ in ()).throw(
            RuntimeError(f"database failed {DATABASE_URL}")
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_rows",
        lambda _engine, *, context: cleanup_calls.append(dict(context)) or {},
    )

    evidence = smoke.run_ag_audit_evidence_postgres_smoke(_env())

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

    evidence = smoke.run_ag_audit_evidence_postgres_smoke(_env())

    assert evidence["failure_code"] == "smoke_execution_failed"


def test_execute_smoke_runs_protected_create_verify_and_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = InMemoryOperationalEventStore()
    exports = OperatorEvidenceExportStore()
    monkeypatch.setattr(
        smoke,
        "_database_observation",
        lambda *_a, **_k: _observation(),
    )

    evidence = smoke._execute_smoke(
        FakeEngine(),
        event_store=events,
        export_store=exports,
        migration=_migration(),
        database_url=DATABASE_URL,
        context=_context(),
    )

    assert all(evidence["checks"].values())
    assert evidence["package"]["verification_status"] == "VERIFIED"
    assert evidence["observation"]["event_count"] == 3
    assert len(events.list_events(trace_id=_context()["trace_id"], limit=10)) == 3
    assert len(exports.list_exports(trace_id=_context()["trace_id"], limit=10)) == 1
    serialized = str(evidence)
    assert smoke.RAW_EVENT_MESSAGE not in serialized
    assert smoke.RAW_EVENT_CREDENTIAL not in serialized
    assert smoke.RAW_EXPORT_BODY not in serialized


def test_execute_smoke_reports_failed_runtime_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = _observation()
    observation["package_table_absent"] = False
    monkeypatch.setattr(
        smoke,
        "_database_observation",
        lambda *_a, **_k: observation,
    )

    evidence = smoke._execute_smoke(
        FakeEngine(),
        event_store=InMemoryOperationalEventStore(),
        export_store=OperatorEvidenceExportStore(),
        migration=_migration(),
        database_url=DATABASE_URL,
        context=_context(),
    )

    assert evidence["checks"]["no_new_package_table"] is False


def test_database_observation_reads_direct_postgresql_rows() -> None:
    class Result:
        def __init__(self, value: object) -> None:
            self.value = value

        def scalar(self) -> object:
            return self.value

        def mappings(self):
            return self

        def one(self) -> object:
            return self.value

    class Connection:
        def __init__(self) -> None:
            self.results = iter(
                [
                    Result("public.service_operational_events"),
                    Result("public.ag_ev_exports"),
                    Result(None),
                    Result(
                        {
                            "database_name": "nex_ag_test",
                            "event_count": 3,
                            "source_event_count": 1,
                            "generated_event_count": 1,
                            "verified_event_count": 1,
                            "package_event_count": 2,
                            "export_count": 1,
                            "hash_ready_export_count": 1,
                        }
                    ),
                ]
            )

        def execute(self, *_args: object, **_kwargs: object) -> Result:
            return next(self.results)

    class Engine(FakeEngine):
        def connect(self):
            return nullcontext(Connection())

    observation = smoke._database_observation(Engine(), context=_context())

    assert observation == _observation()


def test_cleanup_owned_rows_and_empty_context() -> None:
    class Result:
        def __init__(self, *, rowcount: int = 0, scalar: int = 0) -> None:
            self.rowcount = rowcount
            self._scalar = scalar

        def scalar(self) -> int:
            return self._scalar

    class Connection:
        def __init__(self) -> None:
            self.results = iter(
                [
                    Result(rowcount=3),
                    Result(rowcount=1),
                    Result(scalar=0),
                ]
            )

        def execute(self, *_args: object, **_kwargs: object) -> Result:
            return next(self.results)

    class Engine(FakeEngine):
        def begin(self):
            return nullcontext(Connection())

    assert smoke._cleanup_owned_rows(Engine(), context=_context()) == {
        "events": 3,
        "exports": 1,
        "remaining_rows": 0,
    }
    assert smoke._cleanup_owned_rows(Engine(), context={}) == {
        "events": 0,
        "exports": 0,
        "remaining_rows": 0,
    }


def test_cleanup_failure_and_helper_contracts() -> None:
    class FailingEngine(FakeEngine):
        def begin(self):
            raise SQLAlchemyError("transaction unavailable")

    cleanup = smoke._cleanup_owned_rows(FailingEngine(), context=_context())

    assert cleanup["remaining_rows"] == -1
    assert smoke._regclass_matches("public.ag_ev_exports", "ag_ev_exports") is True
    assert smoke._regclass_matches(None, "ag_ev_exports") is False
    assert smoke._engine_backend(FakeEngine()) == "postgresql"
    assert smoke._engine_database(FakeEngine()) == "nex_ag_test"
    assert smoke._engine_backend(object()) == "unknown"
    assert smoke._engine_database(object()) is None
    assert len(smoke._sha256_text("value")) == 64
    assert smoke._mapping({"ok": True}) == {"ok": True}
    assert smoke._mapping("bad") == {}


def test_evidence_redaction_rejects_secrets() -> None:
    smoke.assert_smoke_evidence_redacted("safe evidence", _env())
    for secret in (
        DATABASE_URL,
        smoke.RAW_EVENT_MESSAGE,
        smoke.RAW_EVENT_CREDENTIAL,
        smoke.RAW_EXPORT_BODY,
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
                "event_count": 3,
                "export_count": 1,
            },
            "package": {"verification_status": "VERIFIED"},
            "cleanup": {"remaining_rows": 0},
        }
    )
    failed = smoke.summary_line(
        {"status": "FAIL", "failure_code": "checks_failed"}
    )

    assert "smoke=pass" in passed
    assert "events=3" in passed
    assert "package_status=VERIFIED" in passed
    assert "smoke=fail" in failed


def test_main_prints_summary_and_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: {})
    monkeypatch.setattr(
        smoke,
        "run_ag_audit_evidence_postgres_smoke",
        lambda: {"status": "SKIPPED", "skip_reason": "disabled"},
    )

    assert smoke.main(["--summary", "--env-file", "test.env"]) == 0
    assert "smoke=skipped" in capsys.readouterr().out
    assert smoke.main(["--env-file", "test.env"]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_audit_evidence_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "test"},
    )
    assert smoke.main([]) == 1
