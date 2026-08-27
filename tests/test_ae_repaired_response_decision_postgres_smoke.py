from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_repaired_response_decision_postgres_smoke as smoke
from nex_ae_api.repaired_response_decisions import RepairedResponseDecisionError
from nex_ae_api.repaired_responses import RepairedResponseHandoffError
from run_migrations import MigrationError


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class FakeHandoffStore:
    def __init__(self) -> None:
        self.record: dict[str, Any] | None = None
        self.deleted: list[str] = []

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.record = record
        return record

    def get(self, repaired_response_handoff_id: str) -> dict[str, Any] | None:
        if self.record and self.record["repaired_response_handoff_id"] == (
            repaired_response_handoff_id
        ):
            return self.record
        return None

    def delete(self, repaired_response_handoff_id: str) -> int:
        self.deleted.append(repaired_response_handoff_id)
        return 1


class FakeDecisionStore:
    def __init__(self) -> None:
        self.record: dict[str, Any] | None = None
        self.deleted: list[str] = []

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.record = record
        return record

    def get(self, repaired_response_decision_id: str) -> dict[str, Any] | None:
        if self.record and self.record["repaired_response_decision_id"] == (
            repaired_response_decision_id
        ):
            return self.record
        return None

    def list_for_handoff(self, repaired_response_handoff_id: str) -> list[dict[str, Any]]:
        if self.record and self.record["repaired_response_handoff_id"] == (
            repaired_response_handoff_id
        ):
            return [self.record]
        return []

    def delete(self, repaired_response_decision_id: str) -> int:
        self.deleted.append(repaired_response_decision_id)
        return 1


def good_observations(
    *,
    selected_cx_generation_id: str = "cx-gen-repair",
) -> dict[str, Any]:
    return {
        "table_present": True,
        "migration_recorded": True,
        "row_count": 1,
        "handoff_row_count": 1,
        "decision_schema_version": smoke.AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION,
        "decision_action": smoke.DECISION_ACTION_ACCEPT_REPAIR,
        "selected_cx_generation_id": selected_cx_generation_id,
        "jsonb_columns": smoke.EXPECTED_JSONB_TYPES,
        "indexes_present": sorted(smoke.EXPECTED_INDEXES),
    }


def test_repaired_decision_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_repaired_response_decision_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ae_repaired_response_decision_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_repaired_decision_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_repaired_response_decision_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_repaired_response_decision_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_repaired_decision_postgres_smoke_reports_missing_database_url() -> None:
    evidence = smoke.run_ae_repaired_response_decision_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_repaired_decision_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_repaired_response_decision_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_AE_TEST_DATABASE_URL": "postgresql://nex_ae_user:secret@host/db",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "bad migration" in evidence["detail"]


def test_repaired_decision_postgres_smoke_success_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_url = "postgresql://nex_ae_user:secret@host/nex_ae_test"
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=(smoke.MIGRATION_VERSION,),
            applied=(),
            skipped=(smoke.MIGRATION_VERSION,),
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_repaired_decision_smoke",
        lambda **kwargs: {
            "request_id": "request-001",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "repaired_response_handoff_id": "handoff-001",
            "repaired_response_decision_id": "decision-001",
            "decision_request_id": "decision-request-001",
            "interaction_id": "interaction-001",
            "db_observations": good_observations(),
            "checks": {"ok": True},
            "cleanup": {"deleted_decisions": 1, "deleted_handoffs": 1},
        },
    )

    evidence = smoke.run_ae_repaired_response_decision_postgres_smoke(
        {smoke.SMOKE_ENV: "1", "NEX_AE_TEST_DATABASE_URL": raw_url}
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["redacted_database_url"] != raw_url
    assert "secret" not in evidence["redacted_database_url"]
    assert raw_url not in serialized
    assert smoke.summary_line(evidence).startswith(
        "ae_repaired_response_decision_postgres_smoke=pass"
    )


def test_repaired_decision_postgres_smoke_reports_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id=smoke.SERVICE_ID,
            planned=(smoke.MIGRATION_VERSION,),
            applied=(),
            skipped=(smoke.MIGRATION_VERSION,),
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_repaired_decision_smoke",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("route down")),
    )

    evidence = smoke.run_ae_repaired_response_decision_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_AE_TEST_DATABASE_URL": "postgresql://nex_ae_user:secret@host/db",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert evidence["detail"] == "RuntimeError"


def test_execute_repaired_decision_smoke_routes_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    fake_handoff_store = FakeHandoffStore()
    fake_decision_store = FakeDecisionStore()
    cleanup_calls: list[dict[str, str | None]] = []
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRepairedResponseHandoffStore",
        lambda session_factory: fake_handoff_store,
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRepairedResponseDecisionStore",
        lambda session_factory: fake_decision_store,
    )

    def observations(*args: Any, **kwargs: Any) -> dict[str, Any]:
        repair_id = fake_handoff_store.record["source"]["repair_cx_generation_id"]
        return good_observations(selected_cx_generation_id=repair_id)

    monkeypatch.setattr(smoke, "_db_observations", observations)
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda engine, **kwargs: cleanup_calls.append(kwargs),
    )

    result = smoke._execute_ae_repaired_decision_smoke(
        database_url="postgresql://nex_ae_user:secret@host/nex_ae_test",
        database_env="NEX_AE_TEST_DATABASE_URL",
    )

    assert result["checks"] == {key: True for key in result["checks"]}
    assert result["cleanup"] == {"deleted_decisions": 1, "deleted_handoffs": 1}
    assert result["repaired_response_decision_id"] in fake_decision_store.deleted
    assert result["repaired_response_handoff_id"] in fake_handoff_store.deleted
    assert cleanup_calls == [
        {
            "repaired_response_decision_id": result["repaired_response_decision_id"],
            "repaired_response_handoff_id": result["repaired_response_handoff_id"],
        }
    ]
    assert fake_engine.disposed is True


def test_execute_repaired_decision_smoke_raises_when_handoff_store_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    cleanup_calls: list[dict[str, str | None]] = []
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())

    class FailingHandoffStore(FakeHandoffStore):
        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            raise RepairedResponseHandoffError(
                status_code=503,
                error_code="ae.repaired_response_handoff_store_unavailable",
                detail="handoff store down",
                retryable=True,
            )

    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRepairedResponseHandoffStore",
        lambda session_factory: FailingHandoffStore(),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRepairedResponseDecisionStore",
        lambda session_factory: FakeDecisionStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda engine, **kwargs: cleanup_calls.append(kwargs),
    )

    with pytest.raises(RuntimeError, match="handoff store down"):
        smoke._execute_ae_repaired_decision_smoke(
            database_url="postgresql://nex_ae_user:secret@host/nex_ae_test",
            database_env="NEX_AE_TEST_DATABASE_URL",
        )

    assert cleanup_calls[0]["repaired_response_decision_id"] is None
    assert cleanup_calls[0]["repaired_response_handoff_id"] is not None
    assert fake_engine.disposed is True


def test_execute_repaired_decision_smoke_raises_when_route_checks_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    fake_handoff_store = FakeHandoffStore()
    cleanup_calls: list[dict[str, str | None]] = []
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRepairedResponseHandoffStore",
        lambda session_factory: fake_handoff_store,
    )

    class FailingDecisionStore(FakeDecisionStore):
        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            raise RepairedResponseDecisionError(
                status_code=503,
                error_code="ae.repaired_response_decision_store_unavailable",
                detail="decision store down",
                retryable=True,
            )

    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRepairedResponseDecisionStore",
        lambda session_factory: FailingDecisionStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda engine, **kwargs: cleanup_calls.append(kwargs),
    )

    with pytest.raises(RuntimeError, match="route create failed"):
        smoke._execute_ae_repaired_decision_smoke(
            database_url="postgresql://nex_ae_user:secret@host/nex_ae_test",
            database_env="NEX_AE_TEST_DATABASE_URL",
        )

    assert cleanup_calls[0]["repaired_response_handoff_id"] is not None
    assert cleanup_calls[0]["repaired_response_decision_id"] is None
    assert fake_engine.disposed is True


def test_execute_repaired_decision_smoke_raises_when_observation_checks_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    fake_handoff_store = FakeHandoffStore()
    cleanup_calls: list[dict[str, str | None]] = []
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRepairedResponseHandoffStore",
        lambda session_factory: fake_handoff_store,
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRepairedResponseDecisionStore",
        lambda session_factory: FakeDecisionStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: {**good_observations(), "row_count": 0},
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_smoke_rows",
        lambda engine, **kwargs: cleanup_calls.append(kwargs),
    )

    with pytest.raises(RuntimeError, match="checks failed"):
        smoke._execute_ae_repaired_decision_smoke(
            database_url="postgresql://nex_ae_user:secret@host/nex_ae_test",
            database_env="NEX_AE_TEST_DATABASE_URL",
        )

    assert cleanup_calls[0]["repaired_response_handoff_id"] is not None
    assert cleanup_calls[0]["repaired_response_decision_id"] is not None
    assert fake_engine.disposed is True


def test_repaired_decision_smoke_redaction_guard_rejects_raw_url() -> None:
    raw_url = "postgresql://nex_ae_user:secret@host/nex_ae_test"

    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(
            f"unsafe {raw_url}",
            {"NEX_AE_TEST_DATABASE_URL": raw_url},
        )


class FakeScalarResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar(self) -> Any:
        return self.value


class FakeMappingResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def mappings(self) -> "FakeMappingResult":
        return self

    def first(self) -> dict[str, Any] | None:
        return self.row


class FakeScalarsResult:
    def __init__(self, values: list[str]) -> None:
        self.values = values

    def scalars(self) -> "FakeScalarsResult":
        return self

    def all(self) -> list[str]:
        return self.values


class FakeObservationConnection:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def __enter__(self) -> "FakeObservationConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: object, params: object | None = None) -> object:
        query = str(statement)
        if "to_regclass" in query:
            return FakeScalarResult("ae_repaired_response_decisions")
        if "schema_migrations" in query:
            return FakeScalarResult(True)
        if "ae_repaired_response_handoffs" in query:
            return FakeScalarResult(1)
        if "pg_indexes" in query:
            return FakeScalarsResult(sorted(smoke.EXPECTED_INDEXES))
        return FakeMappingResult(self.row)


class FakeObservationEngine:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def connect(self) -> FakeObservationConnection:
        return FakeObservationConnection(self.row)


def test_repaired_decision_db_observations_reads_row_and_indexes() -> None:
    row = {
        "row_count": 1,
        "decision_schema_version": smoke.AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION,
        "decision_action": smoke.DECISION_ACTION_ACCEPT_REPAIR,
        "selected_cx_generation_id": "cx-gen-repair",
        "actor_claims_ref_type": "jsonb",
        "reason_codes_type": "jsonb",
        "metadata_type": "jsonb",
    }

    observations = smoke._db_observations(
        FakeObservationEngine(row),
        repaired_response_decision_id="decision-001",
        repaired_response_handoff_id="handoff-001",
    )

    assert observations == good_observations()


def test_repaired_decision_db_observations_handles_missing_row() -> None:
    observations = smoke._db_observations(
        FakeObservationEngine(None),
        repaired_response_decision_id="missing-decision",
        repaired_response_handoff_id="handoff-001",
    )

    assert observations == {
        "table_present": True,
        "migration_recorded": True,
        "row_count": 0,
        "handoff_row_count": 1,
        "decision_schema_version": None,
        "decision_action": None,
        "selected_cx_generation_id": None,
        "jsonb_columns": {
            field_name: None for field_name in smoke.JSON_STORAGE_FIELDS
        },
        "indexes_present": sorted(smoke.EXPECTED_INDEXES),
    }


def test_repaired_decision_cleanup_ignores_sqlalchemy_errors() -> None:
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

    smoke._cleanup_smoke_rows(
        ExplodingEngine(),
        repaired_response_decision_id="decision-001",
        repaired_response_handoff_id="handoff-001",
    )
    smoke._cleanup_smoke_rows(
        ExplodingEngine(),
        repaired_response_decision_id=None,
        repaired_response_handoff_id=None,
    )


def test_repaired_decision_cleanup_deletes_decision_then_handoff() -> None:
    class RecordingBegin:
        def __init__(self) -> None:
            self.deleted: list[dict[str, str]] = []

        def __enter__(self) -> "RecordingBegin":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object, params: dict[str, str]) -> None:
            self.deleted.append(params)

    class RecordingEngine:
        def __init__(self) -> None:
            self.connection = RecordingBegin()

        def begin(self) -> RecordingBegin:
            return self.connection

    engine = RecordingEngine()

    smoke._cleanup_smoke_rows(
        engine,
        repaired_response_decision_id="decision-001",
        repaired_response_handoff_id="handoff-001",
    )

    assert engine.connection.deleted == [
        {"decision_id": "decision-001"},
        {"handoff_id": "handoff-001"},
    ]


def test_repaired_decision_main_prints_summary_and_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_repaired_response_decision_postgres_smoke",
        lambda: {"smoke_schema_version": smoke.SCHEMA_VERSION, "status": "SKIPPED"},
    )

    assert smoke.main(["--summary"]) == 0
    assert "ae_repaired_response_decision_postgres_smoke=skipped" in (
        capsys.readouterr().out
    )

    monkeypatch.setattr(
        smoke,
        "run_ae_repaired_response_decision_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "service_id": smoke.SERVICE_ID,
            "failure_code": "execution_failed",
        },
    )

    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
