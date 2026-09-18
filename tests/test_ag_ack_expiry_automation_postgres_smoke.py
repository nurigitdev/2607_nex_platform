from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

import run_ag_ack_expiry_automation_postgres_smoke as smoke
from run_migrations import MigrationError


def smoke_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: (
            "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/nex_ag_test"
        ),
    }


def test_postgres_smoke_skips_without_opt_in() -> None:
    evidence = smoke.run_ag_ack_expiry_automation_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert "postgres_smoke=skipped" in smoke.summary_line(evidence)


def test_postgres_smoke_requires_test_database_url() -> None:
    evidence = smoke.run_ag_ack_expiry_automation_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "database_url_missing"


def test_postgres_smoke_redacts_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = smoke_env()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MigrationError(f"cannot connect {env[smoke.DATABASE_ENV]}")
        ),
    )

    evidence = smoke.run_ag_ack_expiry_automation_postgres_smoke(env)

    assert evidence["failure_code"] == "migration_failed"
    assert env[smoke.DATABASE_ENV] not in evidence["detail"]


def test_postgres_smoke_orchestrates_cleanup_and_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeEngine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    engine = FakeEngine()
    store = object()
    migration = SimpleNamespace(service_id=smoke.SERVICE_ID)
    evidence = {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "PENDING",
        "checks": {"runtime": True},
    }
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: migration)
    monkeypatch.setattr(smoke, "build_engine", lambda _url: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewLivenessAckStateStore",
        lambda _factory: store,
    )
    monkeypatch.setattr(smoke, "SqlAlchemyOperationalEventStore", lambda _factory: object())
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda *_args, **_kwargs: (evidence, "state-0828", "request-0828"),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_rows",
        lambda *_args, **_kwargs: {
            "deleted_state_rows": 1,
            "deleted_event_rows": 2,
            "remaining_state_rows": 0,
            "remaining_event_rows": 0,
        },
    )

    result = smoke.run_ag_ack_expiry_automation_postgres_smoke(smoke_env())

    assert result["status"] == "PASS"
    assert result["checks"]["owned_state_deleted"] is True
    assert result["checks"]["owned_events_deleted"] is True
    assert engine.disposed is True


def test_postgres_smoke_failure_still_cleans_and_disposes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeEngine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    engine = FakeEngine()
    cleanup_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_a, **_k: SimpleNamespace(service_id=smoke.SERVICE_ID),
    )
    monkeypatch.setattr(smoke, "build_engine", lambda _url: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyOperatorReviewLivenessAckStateStore",
        lambda _factory: object(),
    )
    monkeypatch.setattr(smoke, "SqlAlchemyOperationalEventStore", lambda _factory: object())
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("failed")),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_rows",
        lambda *_args, **kwargs: cleanup_calls.append(kwargs) or {},
    )

    result = smoke.run_ag_ack_expiry_automation_postgres_smoke(smoke_env())

    assert result["failure_code"] == "smoke_execution_failed"
    assert cleanup_calls == [{"state_id": None, "request_id": None}]
    assert engine.disposed is True


def test_postgres_smoke_handles_engine_build_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_a, **_k: SimpleNamespace(service_id=smoke.SERVICE_ID),
    )
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda _url: (_ for _ in ()).throw(ValueError("engine failed")),
    )

    result = smoke.run_ag_ack_expiry_automation_postgres_smoke(smoke_env())

    assert result["failure_code"] == "smoke_execution_failed"


def test_invoke_cli_parses_object_and_rejects_bad_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def good_main(_argv: list[str], stdout: Any, **_kwargs: Any) -> int:
        stdout.write('{"result_status":"PLANNED"}')
        return 0

    monkeypatch.setattr(smoke, "automation_cli_main", good_main)
    assert smoke._invoke_cli([], environ={})["result_status"] == "PLANNED"

    monkeypatch.setattr(smoke, "automation_cli_main", lambda *_a, **_k: 2)
    with pytest.raises(smoke.JSONDecodeError, match="exit code"):
        smoke._invoke_cli([], environ={})

    def invalid_main(_argv: list[str], stdout: Any, **_kwargs: Any) -> int:
        stdout.write("not-json")
        return 0

    monkeypatch.setattr(smoke, "automation_cli_main", invalid_main)
    with pytest.raises(smoke.JSONDecodeError, match="invalid JSON"):
        smoke._invoke_cli([], environ={})

    def list_main(_argv: list[str], stdout: Any, **_kwargs: Any) -> int:
        stdout.write("[]")
        return 0

    monkeypatch.setattr(smoke, "automation_cli_main", list_main)
    with pytest.raises(smoke.JSONDecodeError, match="must be an object"):
        smoke._invoke_cli([], environ={})


def test_smoke_helpers_and_redaction() -> None:
    state = smoke._smoke_state("state-0828", suffix="abc")

    assert state["state_status"] == "SUPPRESSED"
    assert state["suppressed_until"] == "1900-01-01T00:05:00Z"
    assert smoke._mapping(None) == {}
    assert smoke._regclass_matches("public.ag_op_review_ack_state", smoke.ACK_STATE_TABLE)
    assert smoke._regclass_matches(None, smoke.ACK_STATE_TABLE) is False
    assert smoke._engine_backend(object()) == "unknown"
    assert smoke._engine_database(object()) is None
    assert smoke.summary_line({"status": "FAIL", "failure_code": "bad"}).endswith(
        "failure=bad"
    )
    with pytest.raises(ValueError, match="sensitive"):
        smoke.assert_smoke_evidence_redacted(
            json.dumps({"comment": smoke.RAW_COMMENT}),
            smoke_env(),
        )


def test_summary_line_reports_pass_aggregates() -> None:
    line = smoke.summary_line(
        {
            "status": "PASS",
            "database": {"database": "nex_ag_test", "backend": "postgresql"},
            "run": {"applied_count": 1, "lifecycle_event_count": 2},
            "cleanup": {"deleted_state_rows": 1},
        }
    )

    assert "postgres_smoke=pass" in line
    assert "database=nex_ag_test" in line
    assert "events=2" in line


def test_execute_smoke_covers_cli_database_and_event_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeUrl:
        database = "nex_ag_test"

        def get_backend_name(self) -> str:
            return "postgresql"

    class FakeEngine:
        url = FakeUrl()

    class FakeStore:
        record: dict[str, Any] | None = None

        def save(self, record: dict[str, Any]) -> dict[str, Any]:
            self.record = dict(record)
            return record

        def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
            return [dict(self.record or {})]

        def get(self, state_id: str) -> dict[str, Any] | None:
            if self.record and self.record["ack_state_id"] == state_id:
                return dict(self.record)
            return None

    class FakeEventStore:
        events: list[dict[str, Any]] = []

        def list_events(self, *, event_type: str, **_kwargs: Any) -> list[dict[str, Any]]:
            return [event for event in self.events if event["event_type"] == event_type]

    store = FakeStore()
    event_store = FakeEventStore()

    def invoke(argv: list[str], *, environ: Any) -> dict[str, Any]:
        del environ
        request_id = argv[argv.index("--request-id") + 1]
        if "--plan" in argv:
            return {
                "result_status": "PLANNED",
                "plan": {
                    "plan_status": "READY",
                    "candidate_count": 1,
                    "will_mutate": False,
                },
            }
        assert store.record is not None
        store.record["state_status"] = "EXPIRED"
        event_store.events = [
            {
                "event_type": smoke.ACK_EXPIRY_AUTOMATION_EVENT_STARTED,
                "request_id": request_id,
            },
            {
                "event_type": smoke.ACK_EXPIRY_AUTOMATION_EVENT_COMPLETED,
                "request_id": request_id,
            },
        ]
        return {
            "result_status": "EXECUTED",
            "tick_result": {
                "tick_status": "COMPLETED",
                "candidate_count": 1,
                "applied_count": 1,
                "conflict_count": 0,
            },
        }

    monkeypatch.setattr(smoke, "_invoke_cli", invoke)
    monkeypatch.setattr(
        smoke,
        "_database_observations",
        lambda *_args, **_kwargs: {
            "backend": "postgresql",
            "database": "nex_ag_test",
            "ack_state_table_present": True,
            "event_table_present": True,
            "state_status": "EXPIRED",
            "event_count": 2,
        },
    )
    migration = SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=("0802",),
        applied=(),
        skipped=("0802",),
    )

    evidence, state_id, request_id = smoke._execute_smoke(
        FakeEngine(),
        store,
        event_store,
        migration=migration,
        database_url=smoke_env()[smoke.DATABASE_ENV],
        environ=smoke_env(),
    )

    assert state_id.startswith("ack-automation-smoke-0828-")
    assert request_id.startswith("ag-ack-automation-run-0828-")
    assert all(evidence["checks"].values())
    assert evidence["run"]["lifecycle_event_count"] == 2


def test_database_observations_and_cleanup_helpers() -> None:
    class FakeUrl:
        database = "nex_ag_test"

        def get_backend_name(self) -> str:
            return "postgresql"

    class Result:
        def __init__(
            self,
            *,
            row: dict[str, Any] | None = None,
            rowcount: int = 0,
            scalar: int = 0,
        ) -> None:
            self.row = row
            self.rowcount = rowcount
            self.scalar = scalar

        def mappings(self) -> "Result":
            return self

        def one(self) -> dict[str, Any]:
            return dict(self.row or {})

        def scalar_one(self) -> int:
            return self.scalar

    class Connection:
        calls = 0

        def execute(self, statement: Any, _params: Any) -> Result:
            sql = str(statement)
            if "current_database" in sql:
                return Result(
                    row={
                        "database_name": "nex_ag_test",
                        "ack_state_table": "public.ag_op_review_ack_state",
                        "event_table": "public.service_operational_events",
                        "state_status": "EXPIRED",
                        "event_count": 2,
                    }
                )
            if sql.lstrip().startswith("DELETE"):
                return Result(rowcount=2)
            return Result(scalar=0)

    class Engine:
        url = FakeUrl()
        connection = Connection()

        def begin(self) -> Any:
            return nullcontext(self.connection)

    class Store:
        def delete(self, state_id: str) -> int:
            return int(state_id == "state-0828")

        def get(self, _state_id: str) -> None:
            return None

    engine = Engine()
    observations = smoke._database_observations(
        engine,
        state_id="state-0828",
        request_id="request-0828",
    )
    cleanup = smoke._cleanup_owned_rows(
        engine,
        Store(),
        state_id="state-0828",
        request_id="request-0828",
    )
    empty_cleanup = smoke._cleanup_owned_rows(
        engine,
        Store(),
        state_id=None,
        request_id=None,
    )

    assert observations["backend"] == "postgresql"
    assert observations["ack_state_table_present"] is True
    assert observations["event_count"] == 2
    assert cleanup == {
        "deleted_state_rows": 1,
        "deleted_event_rows": 2,
        "remaining_state_rows": 0,
        "remaining_event_rows": 0,
    }
    assert empty_cleanup == {
        "deleted_state_rows": 0,
        "deleted_event_rows": 0,
        "remaining_state_rows": 0,
        "remaining_event_rows": 0,
    }


def test_main_prints_summary_and_sets_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_ag_ack_expiry_automation_postgres_smoke",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--summary"]) == 0
    assert "postgres_smoke=skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ag_ack_expiry_automation_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "test"},
    )
    assert smoke.main([]) == 1
    assert '"failure_code": "test"' in capsys.readouterr().out
