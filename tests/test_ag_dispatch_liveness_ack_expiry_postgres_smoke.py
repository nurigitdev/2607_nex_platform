from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_ag_dispatch_liveness_ack_expiry_postgres_smoke as smoke
from nex_ag.operator_review_liveness_ack import OperatorReviewLivenessAckStateStore
from run_migrations import MigrationError


class FakeUrl:
    database = "nex_ag_test"

    def get_backend_name(self) -> str:
        return "postgresql"


class FakeResult:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row

    def mappings(self) -> "FakeResult":
        return self

    def one(self) -> dict[str, object]:
        return self._row


class FakeConnection:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.statements: list[str] = []
        self.params: list[object] = []

    def execute(self, statement: object, params: object) -> FakeResult:
        self.statements.append(str(statement))
        self.params.append(params)
        return FakeResult(self.row)


class FakeBegin:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, *_args: object) -> None:
        return None


class FakeEngine:
    def __init__(self, row: dict[str, object] | None = None) -> None:
        self.url = FakeUrl()
        self.disposed = False
        self.connection = FakeConnection(
            row
            or {
                "database_name": "nex_ag_test",
                "table_regclass": "public.ag_op_review_ack_state",
                "index_regclass": "public.idx_ag_ack_state_expiry",
                "migration_recorded": True,
            }
        )

    def begin(self) -> FakeBegin:
        return FakeBegin(self.connection)

    def dispose(self) -> None:
        self.disposed = True


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: (
            "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/nex_ag_test"
        ),
    }


def migration_result(*_args: object, **_kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=(smoke.MIGRATION_VERSION,),
        applied=(smoke.MIGRATION_VERSION,),
        skipped=(),
    )


def configure_success(
    monkeypatch: pytest.MonkeyPatch,
    *,
    engine: FakeEngine | None = None,
    store: OperatorReviewLivenessAckStateStore | None = None,
) -> tuple[FakeEngine, OperatorReviewLivenessAckStateStore]:
    selected_engine = engine or FakeEngine()
    selected_store = store or OperatorReviewLivenessAckStateStore()
    monkeypatch.setattr(smoke, "run_service_migrations", migration_result)
    monkeypatch.setattr(smoke, "build_engine", lambda _url: selected_engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewLivenessAckStateStore",
        lambda _factory: selected_store,
    )
    return selected_engine, selected_store


def test_expiry_postgres_smoke_skips_without_opt_in() -> None:
    evidence = smoke.run_ag_dispatch_liveness_ack_expiry_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert "postgres_smoke=skipped" in smoke.summary_line(evidence)


def test_expiry_postgres_smoke_requires_database_url() -> None:
    evidence = smoke.run_ag_dispatch_liveness_ack_expiry_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"


def test_expiry_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MigrationError("bad")),
    )

    evidence = smoke.run_ag_dispatch_liveness_ack_expiry_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "migration_failed"
    assert evidence["detail"] == "bad"


def test_expiry_postgres_smoke_reports_engine_construction_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", migration_result)
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda _url: (_ for _ in ()).throw(ValueError("engine failed")),
    )

    evidence = smoke.run_ag_dispatch_liveness_ack_expiry_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "engine failed"


def test_expiry_postgres_smoke_success_is_scoped_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, store = configure_success(monkeypatch)

    evidence = smoke.run_ag_dispatch_liveness_ack_expiry_postgres_smoke(smoke_env())
    serialized = str(evidence)

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["database"]["database"] == "nex_ag_test"
    assert evidence["database"]["expiry_index_present"] is True
    assert evidence["candidate_selection"]["target_selected"] is True
    assert evidence["candidate_selection"]["conflict_selected"] is True
    assert evidence["reconciliation"]["applied_count"] == 1
    assert evidence["idempotent_rerun"]["candidate_count"] == 0
    assert evidence["conflict_probe"]["stale_cas_applied"] is False
    assert evidence["cleanup"] == {"deleted_rows": 2, "remaining_rows": 0}
    assert store.records == {}
    assert engine.disposed is True
    assert smoke_env()[smoke.DATABASE_ENV] not in serialized
    assert "postgres_smoke=pass" in smoke.summary_line(evidence)


def test_expiry_postgres_smoke_reports_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine(
        {
            "database_name": "nex_ag_test",
            "table_regclass": None,
            "index_regclass": None,
            "migration_recorded": False,
        }
    )
    configure_success(monkeypatch, engine=engine)

    evidence = smoke.run_ag_dispatch_liveness_ack_expiry_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "checks_failed"
    assert evidence["checks"]["table_present"] is False
    assert evidence["checks"]["expiry_index_present"] is False
    assert evidence["checks"]["migration_recorded"] is False
    assert engine.disposed is True


def test_expiry_postgres_smoke_cleans_up_after_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingStore(OperatorReviewLivenessAckStateStore):
        saves = 0

        def save(self, record: dict[str, object]) -> dict[str, object]:
            result = super().save(record)
            self.saves += 1
            if self.saves == 2:
                raise ValueError("second save failed")
            return result

    engine, store = configure_success(monkeypatch, store=FailingStore())

    evidence = smoke.run_ag_dispatch_liveness_ack_expiry_postgres_smoke(smoke_env())

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "smoke_execution_failed"
    assert "second save failed" in evidence["detail"]
    assert store.records == {}
    assert engine.disposed is True


def test_expiry_postgres_smoke_helpers_cover_metadata_and_redaction() -> None:
    engine = FakeEngine()
    observations = smoke._database_observations(engine)

    assert observations == {
        "backend": "postgresql",
        "database": "nex_ag_test",
        "table_name": smoke.TABLE_NAME,
        "table_present": True,
        "index_name": smoke.INDEX_NAME,
        "expiry_index_present": True,
        "migration_version": smoke.MIGRATION_VERSION,
        "migration_recorded": True,
    }
    assert smoke._regclass_matches(None, smoke.TABLE_NAME) is False
    assert smoke._engine_backend(SimpleNamespace(url=object())) == "unknown"
    assert smoke._engine_database(SimpleNamespace(url=object())) is None
    with pytest.raises(ValueError):
        smoke.assert_smoke_evidence_redacted(smoke_env()[smoke.DATABASE_ENV], smoke_env())
    assert "failure=boom" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "boom"}
    )


def test_expiry_postgres_smoke_main_and_quality_gate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda *_args: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_dispatch_liveness_ack_expiry_postgres_smoke",
        lambda: {"status": "PASS", "database": {}, "reconciliation": {}, "cleanup": {}},
    )

    assert smoke.main(["--summary"]) == 0
    assert "postgres_smoke=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_ag_dispatch_liveness_ack_expiry_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "boom"},
    )
    assert smoke.main([]) == 1
    assert '"failure_code": "boom"' in capsys.readouterr().out

    quality_gate = (
        smoke.ROOT / "scripts" / "quality" / "run_quality_gate.sh"
    ).read_text(encoding="utf-8")
    assert "run_ag_dispatch_liveness_ack_expiry_postgres_smoke.py --summary" in quality_gate
