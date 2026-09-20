from __future__ import annotations

from contextlib import nullcontext
import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import run_ag_resilience_performance_postgres_smoke as smoke
from nex_ag.operator_reviews import OperatorEvidenceExportStore
from nex_ag.resilience_performance import (
    AgConcurrencyAdmissionGuard,
    AgSourceIsolationExecutor,
    build_ag_resilience_performance_policy,
)
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


class _Pool:
    def checkedout(self) -> int:
        return 0

    def checkedin(self) -> int:
        return 5

    def overflow(self) -> int:
        return -5


class _Engine:
    url = _Url()
    pool = _Pool()

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
        "request_id": "request-0878-unit",
        "target_id": "target-0878-unit",
        "operator_id": "operator-0878-unit",
        "event_prefix": "event-0878-unit",
        "export_prefix": "export-0878-unit",
    }


def _observation() -> dict[str, Any]:
    return {
        "backend": "postgresql",
        "database": "nex_ag_test",
        "server_version_num": "160000",
        "migration_present": True,
        "event_count": smoke.EVENT_COUNT,
        "export_count": smoke.EXPORT_COUNT,
        "indexes_present": {name: True for name in smoke.INDEX_NAMES},
        "planner_indexes": {
            "event_type": True,
            "event_trace": True,
            "export_trace": True,
        },
    }


def test_smoke_requires_explicit_opt_in_and_database_url() -> None:
    skipped = smoke.run_ag_resilience_performance_postgres_smoke({})
    missing = smoke.run_ag_resilience_performance_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in skipped["skip_reason"]
    assert "smoke=skipped" in smoke.summary_line(skipped)
    assert missing["status"] == "FAIL"
    assert missing["failure_code"] == "database_url_missing"


def test_smoke_redacts_migration_or_policy_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_a, **_k: (_ for _ in ()).throw(
            MigrationError(f"cannot connect {DATABASE_URL}")
        ),
    )

    evidence = smoke.run_ag_resilience_performance_postgres_smoke(_env())

    assert evidence["failure_code"] == "migration_or_policy_failed"
    assert DATABASE_URL not in evidence["detail"]
    assert "***" in evidence["detail"]


@pytest.mark.parametrize(
    ("runtime_ok", "remaining", "expected"),
    [(True, 0, "PASS"), (False, 1, "FAIL")],
)
def test_smoke_orchestrates_engines_cleanup_and_result(
    monkeypatch: pytest.MonkeyPatch,
    runtime_ok: bool,
    remaining: int,
    expected: str,
) -> None:
    engines = [_Engine(), _Engine()]
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(smoke, "build_engine", lambda *_a, **_k: engines.pop(0))
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
            "events": smoke.EVENT_COUNT,
            "exports": smoke.EXPORT_COUNT,
            "remaining_rows": remaining,
        },
    )
    created = list(engines)

    evidence = smoke.run_ag_resilience_performance_postgres_smoke(_env())

    assert evidence["status"] == expected
    assert evidence["checks"]["owned_rows_deleted"] is (remaining == 0)
    assert all(engine.disposed for engine in created)


def test_smoke_cleans_up_after_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engines = [_Engine(), _Engine()]
    cleanup_calls: list[dict[str, str]] = []
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(smoke, "build_engine", lambda *_a, **_k: engines.pop(0))
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
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError(f"database failed {DATABASE_URL}")
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_rows",
        lambda _engine, *, context: cleanup_calls.append(dict(context)) or {},
    )

    evidence = smoke.run_ag_resilience_performance_postgres_smoke(_env())

    assert evidence["failure_code"] == "smoke_execution_failed"
    assert DATABASE_URL not in evidence["detail"]
    assert len(cleanup_calls) == 1


def test_smoke_handles_engine_creation_failure_without_partial_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("engine unavailable")),
    )

    evidence = smoke.run_ag_resilience_performance_postgres_smoke(_env())

    assert evidence["failure_code"] == "smoke_execution_failed"
    assert evidence["detail"] == "engine unavailable"


def test_execute_smoke_runs_concurrent_protected_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = build_ag_resilience_performance_policy(
        {
            "NEX_AG_PERF_SMOKE_REQUEST_COUNT": "8",
            "NEX_AG_PERF_SMOKE_CONCURRENCY": "2",
        }
    )
    guard = AgConcurrencyAdmissionGuard(max_in_flight=8, wait_timeout_ms=100)
    executor = AgSourceIsolationExecutor(
        timeout_ms=2000,
        slow_operation_ms=1000,
        max_workers=2,
    )
    monkeypatch.setattr(smoke, "_database_observation", lambda *_a, **_k: _observation())
    try:
        evidence = smoke._execute_smoke(
            api_engine=_Engine(),
            worker_engine=_Engine(),
            event_store=InMemoryOperationalEventStore(),
            export_store=OperatorEvidenceExportStore(),
            migration=_migration(),
            policy=policy,
            guard=guard,
            source_executor=executor,
            database_url=DATABASE_URL,
            context=_context(),
        )
    finally:
        executor.close()

    assert all(evidence["checks"].values())
    assert evidence["load"]["request_count"] == 8
    assert evidence["load"]["concurrency"] == 2
    assert evidence["load"]["unique_page_signatures"] == 1
    assert evidence["pagination"]["disjoint"] is True
    assert evidence["runtime"]["admission"]["rejected_total"] == 0
    assert smoke.RAW_EVENT_MESSAGE not in str(evidence)


def test_database_observation_reads_migration_indexes_rows_and_plans() -> None:
    class _Result:
        def __init__(self, value: object) -> None:
            self.value = value

        def mappings(self) -> "_Result":
            return self

        def one(self) -> object:
            return self.value

        def all(self) -> object:
            return self.value

        def scalar(self) -> object:
            return self.value

    class _Connection:
        def execute(self, statement: object, *_args: object, **_kwargs: object) -> _Result:
            sql = str(statement)
            if "current_database()" in sql:
                return _Result(
                    {
                        "database_name": "nex_ag_test",
                        "server_version_num": "160000",
                        "migration_present": True,
                        "event_count": smoke.EVENT_COUNT,
                        "export_count": smoke.EXPORT_COUNT,
                    }
                )
            if "FROM pg_indexes" in sql:
                return _Result(
                    [
                        {"indexname": name, "indexdef": f"CREATE INDEX {name}"}
                        for name in smoke.INDEX_NAMES
                    ]
                )
            if "SET LOCAL" in sql:
                return _Result(None)
            if "event_type =" in sql:
                return _Result([{"Plan": {"Index Name": smoke.INDEX_NAMES[0]}}])
            if "service_operational_events" in sql:
                return _Result([{"Plan": {"Index Name": smoke.INDEX_NAMES[1]}}])
            return _Result([{"Plan": {"Index Name": smoke.INDEX_NAMES[2]}}])

    class _ObservedEngine(_Engine):
        def begin(self):
            return nullcontext(_Connection())

    observation = smoke._database_observation(
        _ObservedEngine(),
        context=_context(),
    )

    assert observation == _observation()
    assert smoke._explain_uses_index(
        _Connection(),
        "SELECT event_id FROM service_operational_events WHERE event_type = :event_type",
        {"event_type": "type"},
        smoke.INDEX_NAMES[0],
    ) is True
    assert smoke._explain_uses_index(
        _Connection(),
        "SELECT 1",
        {},
        "missing_index",
    ) is False


def test_cleanup_owned_rows_empty_context_and_failure() -> None:
    class _Result:
        def __init__(self, *, rowcount: int = 0, scalar: int = 0) -> None:
            self.rowcount = rowcount
            self._scalar = scalar

        def scalar(self) -> int:
            return self._scalar

    class _Connection:
        def __init__(self) -> None:
            self.results = iter(
                [
                    _Result(rowcount=smoke.EXPORT_COUNT),
                    _Result(rowcount=smoke.EVENT_COUNT),
                    _Result(scalar=0),
                ]
            )

        def execute(self, *_args: object, **_kwargs: object) -> _Result:
            return next(self.results)

    class _CleanupEngine(_Engine):
        def begin(self):
            return nullcontext(_Connection())

    class _FailingEngine(_Engine):
        def begin(self):
            raise SQLAlchemyError("unavailable")

    assert smoke._cleanup_owned_rows(_CleanupEngine(), context=_context()) == {
        "events": smoke.EVENT_COUNT,
        "exports": smoke.EXPORT_COUNT,
        "remaining_rows": 0,
    }
    assert smoke._cleanup_owned_rows(_CleanupEngine(), context={}) == {
        "events": 0,
        "exports": 0,
        "remaining_rows": 0,
    }
    assert smoke._cleanup_owned_rows(
        _FailingEngine(), context=_context()
    )["remaining_rows"] == -1


def test_helpers_redaction_summary_and_percentile() -> None:
    assert smoke._nearest_rank([4.0, 1.0, 3.0, 2.0], 0.50) == 2.0
    with pytest.raises(ValueError, match="cannot be empty"):
        smoke._nearest_rank([], 0.95)
    assert smoke._action_ids({"recent_actions": [{"event_id": "one"}, {}]}) == [
        "one"
    ]
    assert smoke._action_ids({"recent_actions": "invalid"}) == []
    assert smoke._mapping({"ok": True}) == {"ok": True}
    assert smoke._mapping("invalid") == {}
    assert smoke._engine_backend(_Engine()) == "postgresql"
    assert smoke._engine_backend(object()) == "unknown"
    smoke.assert_smoke_evidence_redacted("safe", _env())
    for secret in (
        DATABASE_URL,
        smoke.RAW_EVENT_MESSAGE,
        smoke.RAW_EVENT_CREDENTIAL,
        smoke.RAW_EXPORT_BODY,
    ):
        with pytest.raises(ValueError, match="contains a secret"):
            smoke.assert_smoke_evidence_redacted(f"evidence={secret}", _env())
    passed = smoke.summary_line(
        {
            "status": "PASS",
            "observation": {
                "database": "nex_ag_test",
                "backend": "postgresql",
                "indexes_present": {name: True for name in smoke.INDEX_NAMES},
            },
            "load": {"request_count": 25, "concurrency": 4, "p95_ms": 12.5},
            "cleanup": {"remaining_rows": 0},
        }
    )
    assert "smoke=pass" in passed
    assert "requests=25" in passed
    assert "indexes=3" in passed
    assert "smoke=fail" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "checks_failed"}
    )


def test_main_prints_summary_json_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: {})
    monkeypatch.setattr(
        smoke,
        "run_ag_resilience_performance_postgres_smoke",
        lambda: {"status": "SKIPPED", "skip_reason": "disabled"},
    )

    assert smoke.main(["--summary", "--env-file", "test.env"]) == 0
    assert "smoke=skipped" in capsys.readouterr().out
    assert smoke.main(["--env-file", "test.env"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SKIPPED"

    monkeypatch.setattr(
        smoke,
        "run_ag_resilience_performance_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "expected"},
    )
    assert smoke.main([]) == 1
