from __future__ import annotations

from datetime import UTC, datetime

import nex_ae_api.agent_runtime_operations as operations_module
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_ae_api.agent_runtime_operations import (
    AE_RUNTIME_OPERATIONS_PATH,
    AgentRuntimeOperationsError,
    SqlAlchemyAgentRuntimeOperationsSource,
    UnavailableAgentRuntimeOperationsSource,
    register_agent_runtime_operations_routes,
)
from nex_runtime import issue_mock_service_token
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)


@pytest.fixture
def operations_source():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_runtime_job (
                    tenant_id TEXT, runtime_job_id TEXT, job_type TEXT,
                    executable_step_id TEXT,
                    state TEXT, attempt_no INTEGER, run_after TEXT,
                    lease_until TEXT, created_at TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_runtime_job_attempt (
                    tenant_id TEXT, runtime_job_id TEXT, outcome TEXT,
                    started_at TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_rt_job_issue (
                    reason_code TEXT, issue_state TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_rt_dispatch_lease (
                    queue_name TEXT, fencing_token INTEGER,
                    lease_until TEXT, released_at TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE service_worker_heartbeats (
                    service_id TEXT, worker_id TEXT, worker_type TEXT,
                    status TEXT, last_seen_at TEXT, metadata TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_executable_step (
                    tenant_id TEXT, executable_step_id TEXT, executor_kind TEXT,
                    invocation_started_at TEXT, completed_at TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_agent_execution (
                    state TEXT, received_at TEXT, updated_at TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO ae_runtime_job VALUES
                ('private-a','job-a','START_EXECUTION','step-a','QUEUED',0,'2026-10-14T00:59:00Z',NULL,'2026-10-14T00:58:00Z'),
                ('private-b','job-b','START_EXECUTION','step-b','RUNNING',1,'2026-10-14T00:58:00Z','2026-10-14T01:01:00Z','2026-10-14T00:57:00Z'),
                ('private-c','job-c','CONTINUE_EXECUTION','step-c','QUEUED',2,'2026-10-14T00:59:30Z',NULL,'2026-10-14T00:56:00Z'),
                ('private-d','job-d','START_EXECUTION','step-d','QUEUED',0,'2026-10-14T02:00:00Z',NULL,'2026-10-14T00:55:00Z'),
                ('private-e','job-e','START_EXECUTION','step-e','FAILED',1,'2026-10-14T00:50:00Z',NULL,'2026-10-14T00:54:00Z'),
                ('private-f','job-f','START_EXECUTION','step-f','DEAD_LETTER',1,'2026-10-14T00:50:00Z',NULL,'2026-10-14T00:53:00Z')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO ae_runtime_job_attempt VALUES
                ('private-b','job-b','RUNNING','2026-10-14T00:57:01Z'),
                ('private-c','job-c','LEASE_EXPIRED','2026-10-14T00:56:02Z')
                """
            )
        )
        connection.execute(
            text("INSERT INTO ae_rt_job_issue VALUES ('STEP_NOT_FOUND','OPEN')")
        )
        connection.execute(
            text(
                "INSERT INTO ae_rt_dispatch_lease VALUES "
                "('ae-runtime',4,'2026-10-14T01:00:15Z',NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO service_worker_heartbeats VALUES "
                "('nex-ae-api','worker-local','ae.agent_runtime.worker','IDLE',"
                "'2026-10-14T00:59:50Z','{\"supported_executor_kinds\":[\"LOCAL_SKILL\"]}'),"
                "('nex-ae-api','worker-stale','ae.agent_runtime.worker','BUSY',"
                "'2026-10-14T00:58:00Z','{\"supported_executor_kinds\":[\"DETERMINISTIC_REPORT\"]}')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_executable_step VALUES "
                "('private-a','step-a','LOCAL_SKILL','2026-10-14T00:58:00Z','2026-10-14T00:58:02Z'),"
                "('private-b','step-b','LOCAL_SKILL',NULL,NULL),"
                "('private-c','step-c','DETERMINISTIC_REPORT',NULL,NULL),"
                "('private-d','step-d','DETERMINISTIC_AGGREGATE',NULL,NULL),"
                "('private-e','step-e','LOCAL_SKILL',NULL,NULL),"
                "('private-f','step-f','LOCAL_SKILL',NULL,NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_agent_execution VALUES "
                "('SUCCEEDED','2026-10-14T00:57:00Z','2026-10-14T00:57:03Z')"
            )
        )
    source = SqlAlchemyAgentRuntimeOperationsSource(sessionmaker(bind=engine))
    yield source
    engine.dispose()


def _authorization(service_id: str = "nex-ag", *, include_scope: bool = True) -> str:
    scopes = ["service:call"]
    if include_scope:
        scopes.append("operations:read")
    token = issue_mock_service_token(
        service_id=service_id,
        audience="nex-ae-api",
        scopes=scopes,
    )
    return f"Bearer {token.access_token}"


def _client(source, *, clock=lambda: NOW) -> TestClient:
    app = FastAPI()
    register_agent_runtime_operations_routes(app, source=source, clock=clock)
    return TestClient(app)


def test_sqlalchemy_projection_emits_bounded_privacy_safe_metrics(
    operations_source,
) -> None:
    snapshot = operations_source.snapshot(observed_at="2026-10-14T01:00:00Z")

    assert snapshot["queue"] == {
        "queued": 1,
        "running": 1,
        "retrying": 1,
        "delayed": 1,
        "failed": 1,
        "dead_letter": 1,
        "oldest_runnable_age_seconds": 60.0,
    }
    assert snapshot["attempts"] == {
        "total": 2,
        "lease_expiry_count": 1,
        "reclaim_count": 1,
        "stale_completion_rejection_count": None,
        "stale_completion_evidence": "NOT_PERSISTED",
    }
    assert snapshot["latency_ms"] == {
        "claim": 1500.0,
        "step": 2000.0,
        "execution": 3000.0,
    }
    assert snapshot["leadership"] == {
        "queue_name": "ae-runtime",
        "active": True,
        "fencing_token": 4,
        "lease_until": "2026-10-14T01:00:15Z",
    }
    assert snapshot["workers"] == {
        "status_counts": {"BUSY": 1, "IDLE": 1},
        "heartbeat_count": 2,
    }
    assert snapshot["capability"] == {
        "operational_state": "NO_CAPABLE_WORKER",
        "no_capable_worker_count": 1,
        "executor_counts": {"DETERMINISTIC_REPORT": 1},
        "active_executor_kinds": ["LOCAL_SKILL"],
        "bounded_executor_labels": True,
    }
    assert snapshot["issues"] == {
        "open_count": 1,
        "reason_counts": {"STEP_NOT_FOUND": 1},
    }
    assert snapshot["mutation_authority"] is False
    rendered = str(snapshot)
    assert "private-a" not in rendered
    assert "job-a" not in rendered


def test_route_is_ag_only_read_only_and_translates_unavailable(
    operations_source,
) -> None:
    client = _client(operations_source)
    assert client.get(AE_RUNTIME_OPERATIONS_PATH).status_code == 401
    assert (
        client.get(
            AE_RUNTIME_OPERATIONS_PATH,
            headers={"Authorization": _authorization(include_scope=False)},
        ).status_code
        == 401
    )
    forbidden = client.get(
        AE_RUNTIME_OPERATIONS_PATH,
        headers={"Authorization": _authorization("nex-cx")},
    )
    assert forbidden.status_code == 403
    allowed = client.get(
        AE_RUNTIME_OPERATIONS_PATH,
        headers={"Authorization": _authorization()},
    )
    assert allowed.status_code == 200
    assert allowed.json()["mutation_authority"] is False
    assert client.post(AE_RUNTIME_OPERATIONS_PATH).status_code == 405

    unavailable = _client(UnavailableAgentRuntimeOperationsSource()).get(
        AE_RUNTIME_OPERATIONS_PATH,
        headers={"Authorization": _authorization()},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == (
        "ae.agent_runtime_operations.persistence_unavailable"
    )


def test_projection_and_route_fail_closed_for_invalid_sources() -> None:
    with pytest.raises(AgentRuntimeOperationsError):
        SqlAlchemyAgentRuntimeOperationsSource(
            sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:")),
            sample_limit=0,
        )
    broken_engine = create_engine("sqlite+pysqlite:///:memory:")
    broken = SqlAlchemyAgentRuntimeOperationsSource(sessionmaker(bind=broken_engine))
    with pytest.raises(AgentRuntimeOperationsError) as exc_info:
        broken.snapshot(observed_at="2026-10-14T01:00:00Z")
    assert exc_info.value.error_code == "ae.agent_runtime_operations.store_unavailable"
    broken_engine.dispose()

    naive_clock = _client(
        UnavailableAgentRuntimeOperationsSource(),
        clock=lambda: datetime(2026, 10, 14, 1, 0),  # noqa: DTZ001
    ).get(
        AE_RUNTIME_OPERATIONS_PATH,
        headers={"Authorization": _authorization()},
    )
    assert naive_clock.status_code == 500
    assert (
        naive_clock.json()["error_code"] == "ae.agent_runtime_operations.clock_invalid"
    )


def test_empty_projection_and_timestamp_validation(operations_source) -> None:
    assert str(AgentRuntimeOperationsError("code", "detail")) == "detail"
    with operations_source._session_factory.begin() as session:
        for table in (
            "ae_runtime_job_attempt",
            "ae_runtime_job",
            "ae_rt_job_issue",
            "ae_rt_dispatch_lease",
            "service_worker_heartbeats",
            "ae_executable_step",
            "ae_agent_execution",
        ):
            session.execute(text(f"DELETE FROM {table}"))

    snapshot = operations_source.snapshot(observed_at="2026-10-14T01:00:00Z")
    assert snapshot["queue"]["oldest_runnable_age_seconds"] is None
    assert snapshot["leadership"] == {
        "queue_name": None,
        "active": False,
        "fencing_token": None,
        "lease_until": None,
    }
    assert snapshot["latency_ms"] == {
        "claim": None,
        "step": None,
        "execution": None,
    }
    assert snapshot["workers"]["heartbeat_count"] == 0
    assert snapshot["capability"] == {
        "operational_state": "CAPABLE",
        "no_capable_worker_count": 0,
        "executor_counts": {},
        "active_executor_kinds": [],
        "bounded_executor_labels": True,
    }

    for invalid in ("not-a-timestamp", 7, "2026-10-14T01:00:00"):
        with pytest.raises(AgentRuntimeOperationsError) as exc_info:
            operations_source.snapshot(observed_at=invalid)  # type: ignore[arg-type]
        assert (
            exc_info.value.error_code == "ae.agent_runtime_operations.timestamp_invalid"
        )

    with pytest.raises(AgentRuntimeOperationsError) as exc_info:
        SqlAlchemyAgentRuntimeOperationsSource(
            operations_source._session_factory,
            queue_name="",
        )
    assert exc_info.value.error_code == "ae.agent_runtime_operations.config_invalid"


def test_projection_preserves_domain_error(
    operations_source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = AgentRuntimeOperationsError(
        "ae.agent_runtime_operations.projection_invalid",
        "projection failed",
        500,
        False,
    )

    def fail_projection(**_kwargs):
        raise expected

    monkeypatch.setattr(operations_module, "_build_snapshot", fail_projection)
    with pytest.raises(AgentRuntimeOperationsError) as exc_info:
        operations_source.snapshot(observed_at="2026-10-14T01:00:00Z")
    assert exc_info.value is expected


def test_capability_metadata_is_bounded_and_malformed_values_are_ignored() -> None:
    assert operations_module._metadata_object({"value": 1}) == {"value": 1}
    assert operations_module._metadata_object("not-json") == {}
    assert operations_module._metadata_object("[1,2]") == {}
    assert operations_module._metadata_object(None) == {}

    projection = operations_module._capability_projection(
        observed_at="2026-10-14T01:00:00Z",
        workers=[
            {
                "status": "STOPPED",
                "last_seen_at": "2026-10-14T00:59:59Z",
                "metadata": {"supported_executor_kinds": ["DETERMINISTIC_REPORT"]},
            },
            {
                "status": "IDLE",
                "last_seen_at": "2026-10-14T00:59:59Z",
                "metadata": {"supported_executor_kinds": ["LOCAL_SKILL", "UNKNOWN"]},
            },
            {
                "status": "IDLE",
                "last_seen_at": "2026-10-14T00:59:59Z",
                "metadata": {"supported_executor_kinds": "LOCAL_SKILL"},
            },
        ],
        runnable_executors=[
            {"executor_kind": "LOCAL_SKILL", "runnable_count": 1},
            {"executor_kind": "DETERMINISTIC_REPORT", "runnable_count": 2},
            {"executor_kind": "UNKNOWN", "runnable_count": 50},
        ],
    )
    assert projection["active_executor_kinds"] == ["LOCAL_SKILL"]
    assert projection["executor_counts"] == {"DETERMINISTIC_REPORT": 2}
    assert projection["no_capable_worker_count"] == 2
