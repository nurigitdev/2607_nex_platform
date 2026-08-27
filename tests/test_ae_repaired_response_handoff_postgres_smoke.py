from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ae_repaired_response_handoff_postgres_smoke as smoke
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

    def list_for_interaction(self, interaction_id: str) -> list[dict[str, Any]]:
        if self.record and self.record["interaction_id"] == interaction_id:
            return [self.record]
        return []

    def delete(self, repaired_response_handoff_id: str) -> int:
        self.deleted.append(repaired_response_handoff_id)
        return 1


def good_observations() -> dict[str, Any]:
    return {
        "table_present": True,
        "migration_recorded": True,
        "row_count": 1,
        "handoff_schema_version": "ae_repaired_response_handoff.v1",
        "jsonb_columns": smoke.EXPECTED_JSONB_TYPES,
        "indexes_present": sorted(smoke.EXPECTED_INDEXES),
    }


def test_repaired_handoff_postgres_smoke_skips_when_disabled() -> None:
    evidence = smoke.run_ae_repaired_response_handoff_postgres_smoke({})

    assert evidence == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert smoke.summary_line(evidence) == (
        "ae_repaired_response_handoff_postgres_smoke=skipped "
        f"reason={smoke.SMOKE_ENV}"
    )


def test_repaired_handoff_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_repaired_response_handoff_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.SMOKE_PROFILE_ENV: "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert smoke.summary_line(evidence) == (
        "ae_repaired_response_handoff_postgres_smoke=fail "
        "service=nex-ae-api reason=profile_not_allowed"
    )


def test_repaired_handoff_postgres_smoke_reports_missing_database_url() -> None:
    evidence = smoke.run_ae_repaired_response_handoff_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "NEX_AE_TEST_DATABASE_URL" in evidence["detail"]


def test_repaired_handoff_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(MigrationError("bad migration")),
    )

    evidence = smoke.run_ae_repaired_response_handoff_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_AE_TEST_DATABASE_URL": "postgresql://nex_ae_user:secret@host/db",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "bad migration" in evidence["detail"]


def test_repaired_handoff_postgres_smoke_success_is_redacted(
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
        "_execute_ae_repaired_handoff_smoke",
        lambda **kwargs: {
            "request_id": "request-001",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "repaired_response_handoff_id": "handoff-001",
            "handoff_request_id": "handoff-request-001",
            "interaction_id": "interaction-001",
            "db_observations": good_observations(),
            "checks": {"ok": True},
            "cleanup": {"deleted_rows": 1},
        },
    )

    evidence = smoke.run_ae_repaired_response_handoff_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_AE_TEST_DATABASE_URL": raw_url,
        }
    )
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "NEX_AE_TEST_DATABASE_URL"
    assert evidence["redacted_database_url"] != raw_url
    assert "secret" not in evidence["redacted_database_url"]
    assert raw_url not in serialized
    assert smoke.summary_line(evidence).startswith(
        "ae_repaired_response_handoff_postgres_smoke=pass"
    )


def test_repaired_handoff_postgres_smoke_reports_execution_failure(
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
        "_execute_ae_repaired_handoff_smoke",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("store down")),
    )

    evidence = smoke.run_ae_repaired_response_handoff_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_AE_TEST_DATABASE_URL": "postgresql://nex_ae_user:secret@host/db",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert evidence["detail"] == "RuntimeError"


def test_execute_repaired_handoff_smoke_saves_reads_lists_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    fake_store = FakeHandoffStore()
    cleanup_calls: list[str] = []
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRepairedResponseHandoffStore",
        lambda session_factory: fake_store,
    )
    monkeypatch.setattr(smoke, "_db_observations", lambda *args, **kwargs: good_observations())
    monkeypatch.setattr(
        smoke,
        "_cleanup_handoff",
        lambda engine, handoff_id: cleanup_calls.append(handoff_id),
    )

    result = smoke._execute_ae_repaired_handoff_smoke(
        database_url="postgresql://nex_ae_user:secret@host/nex_ae_test",
        database_env="NEX_AE_TEST_DATABASE_URL",
    )

    assert result["checks"] == {key: True for key in result["checks"]}
    assert result["cleanup"]["deleted_rows"] == 1
    assert result["repaired_response_handoff_id"] in fake_store.deleted
    assert cleanup_calls == [result["repaired_response_handoff_id"]]
    assert fake_engine.disposed is True


def test_execute_repaired_handoff_smoke_raises_when_store_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    cleanup_calls: list[str] = []
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())

    class FailingHandoffStore(FakeHandoffStore):
        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            raise RepairedResponseHandoffError(
                status_code=503,
                error_code="ae.repaired_response_handoff_store_unavailable",
                detail="store down",
                retryable=True,
            )

    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRepairedResponseHandoffStore",
        lambda session_factory: FailingHandoffStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_handoff",
        lambda engine, handoff_id: cleanup_calls.append(handoff_id),
    )

    with pytest.raises(RuntimeError, match="store down"):
        smoke._execute_ae_repaired_handoff_smoke(
            database_url="postgresql://nex_ae_user:secret@host/nex_ae_test",
            database_env="NEX_AE_TEST_DATABASE_URL",
        )

    assert len(cleanup_calls) == 1
    assert fake_engine.disposed is True


def test_execute_repaired_handoff_smoke_raises_when_checks_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    cleanup_calls: list[str] = []
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRepairedResponseHandoffStore",
        lambda session_factory: FakeHandoffStore(),
    )
    monkeypatch.setattr(
        smoke,
        "_db_observations",
        lambda *args, **kwargs: {**good_observations(), "row_count": 0},
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_handoff",
        lambda engine, handoff_id: cleanup_calls.append(handoff_id),
    )

    with pytest.raises(RuntimeError, match="checks failed"):
        smoke._execute_ae_repaired_handoff_smoke(
            database_url="postgresql://nex_ae_user:secret@host/nex_ae_test",
            database_env="NEX_AE_TEST_DATABASE_URL",
        )

    assert len(cleanup_calls) == 1
    assert fake_engine.disposed is True


def test_execute_repaired_handoff_smoke_disposes_when_record_build_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    cleanup_calls: list[str] = []
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: fake_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyRepairedResponseHandoffStore",
        lambda session_factory: FakeHandoffStore(),
    )
    monkeypatch.setattr(
        smoke,
        "build_repaired_response_handoff_record",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("bad record")),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_handoff",
        lambda engine, handoff_id: cleanup_calls.append(handoff_id),
    )

    with pytest.raises(RuntimeError, match="bad record"):
        smoke._execute_ae_repaired_handoff_smoke(
            database_url="postgresql://nex_ae_user:secret@host/nex_ae_test",
            database_env="NEX_AE_TEST_DATABASE_URL",
        )

    assert cleanup_calls == []
    assert fake_engine.disposed is True


def test_repaired_handoff_smoke_redaction_guard_rejects_raw_url() -> None:
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

    def execute(
        self,
        statement: object,
        params: object | None = None,
    ) -> object:
        query = str(statement)
        if "to_regclass" in query:
            return FakeScalarResult("ae_repaired_response_handoffs")
        if "schema_migrations" in query:
            return FakeScalarResult(True)
        if "pg_indexes" in query:
            return FakeScalarsResult(sorted(smoke.EXPECTED_INDEXES))
        return FakeMappingResult(self.row)


class FakeObservationEngine:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def connect(self) -> FakeObservationConnection:
        return FakeObservationConnection(self.row)


def test_repaired_handoff_db_observations_reads_row_and_indexes() -> None:
    row = {
        "row_count": 1,
        "handoff_schema_version": "ae_repaired_response_handoff.v1",
        "actor_claims_ref_type": "jsonb",
        "source_type": "jsonb",
        "repaired_response_type": "jsonb",
        "lineage_type": "jsonb",
        "user_surface_type": "jsonb",
        "links_type": "jsonb",
        "redaction_summary_type": "jsonb",
    }

    observations = smoke._db_observations(
        FakeObservationEngine(row),
        repaired_response_handoff_id="handoff-001",
    )

    assert observations == good_observations()


def test_repaired_handoff_db_observations_handles_missing_row() -> None:
    observations = smoke._db_observations(
        FakeObservationEngine(None),
        repaired_response_handoff_id="missing",
    )

    assert observations == {
        "table_present": True,
        "migration_recorded": True,
        "row_count": 0,
        "handoff_schema_version": None,
        "jsonb_columns": {
            field_name: None for field_name in smoke.JSON_STORAGE_FIELDS
        },
        "indexes_present": sorted(smoke.EXPECTED_INDEXES),
    }


def test_repaired_handoff_cleanup_ignores_sqlalchemy_errors() -> None:
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

    smoke._cleanup_handoff(ExplodingEngine(), "handoff-001")


def test_repaired_handoff_main_prints_summary_and_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_repaired_response_handoff_postgres_smoke",
        lambda: {"smoke_schema_version": smoke.SCHEMA_VERSION, "status": "SKIPPED"},
    )

    assert smoke.main(["--summary"]) == 0
    assert "ae_repaired_response_handoff_postgres_smoke=skipped" in (
        capsys.readouterr().out
    )

    monkeypatch.setattr(
        smoke,
        "run_ae_repaired_response_handoff_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "service_id": smoke.SERVICE_ID,
            "failure_code": "execution_failed",
        },
    )

    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
