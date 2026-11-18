from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Self
from uuid import UUID

import pytest
from nex_runtime import (
    FAILED,
    QUEUED,
    SUCCEEDED,
    InMemoryJobQueue,
    InMemoryWorkerHeartbeatStore,
    SqlAlchemyJobQueue,
    WorkerHeartbeatEmitter,
)
from nex_wc.assignment_dispatch import (
    RELOAD,
    RETRY,
    ROUTE,
    TERMINAL,
    AssignmentDispatchContractError,
    AssignmentDispatchExecutionError,
    enqueue_claimable_assignment_jobs,
    run_assignment_dispatch_job,
    run_assignment_dispatch_worker_once,
    validate_claimable_work_item,
)
from nex_wc.coordination import (
    InMemoryCoordinationRepository,
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.work_items import (
    InMemoryWorkItemRepository,
    SqlAlchemyWorkItemRepository,
    WorkItemService,
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

NOW_DT = datetime(2026, 11, 18, 2, 0, tzinfo=UTC)
NOW = "2026-11-18T02:00:00Z"
TENANT = "tenant-b5b2"
PROJECT = "project-b5b2"
PROFILE = "agent-profile://nex-platform/project-agent/v1"


class _Agents:
    def __init__(self, candidates: list[dict[str, object]] | None = None) -> None:
        self.candidates = list(candidates if candidates is not None else [_candidate()])

    def list_agents(self, **_: object) -> list[dict[str, object]]:
        return list(self.candidates)

    def get_agent(
        self, *, tenant_id: str, agent_id: str
    ) -> dict[str, object] | None:
        return next(
            (
                item
                for item in self.candidates
                if item["tenant_id"] == tenant_id and item["agent_id"] == agent_id
            ),
            None,
        )


class _Authorization:
    def __init__(self, **overrides: object) -> None:
        self.value = {
            "active": True,
            "scopes": ["work:delegate", "work:claim"],
            "revision_hash": "sha256:" + "a" * 64,
        }
        self.value.update(overrides)

    def effective_authorization(self, **_: object) -> dict[str, object]:
        return dict(self.value)


def _candidate() -> dict[str, object]:
    return {
        "schema_version": "2.1",
        "tenant_id": TENANT,
        "agent_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "agent_type": "PA",
        "profile_ref": PROFILE,
        "status": "ACTIVE",
        "project_id": PROJECT,
        "created_at": NOW,
        "version": 1,
    }


def _payload() -> dict[str, object]:
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-b5b2",
            "tenant_id": TENANT,
            "parent_agent_execution_id": "execution-b5b2",
            "parent_executable_plan_id": "plan-b5b2",
            "parent_executable_step_id": "step-b5b2",
            "delegation_revision": 1,
            "goal": "Execute an admitted project operation",
            "work_class": "BUSINESS_TRANSACTION",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.VOUCHER.APPROVE_AND_POST",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": "urn:nex:result:business:v1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "trace-b5b2",
            "causation_id": "cause-b5b2",
        },
        "requester": {"entity_type": "USER", "entity_id": "requester-b5b2"},
        "accountable_owner": {
            "entity_type": "USER",
            "entity_id": "owner-b5b2",
        },
    }


def _runtime(
    *,
    candidates: list[dict[str, object]] | None = None,
    claim_authorization: _Authorization | None = None,
) -> tuple[
    InMemoryWorkItemRepository,
    InMemoryCoordinationRepository,
    WorkCoordinationService,
    dict[str, object],
]:
    work_repository = InMemoryWorkItemRepository()
    work_service = WorkItemService(
        work_repository,
        authorization_source=_Authorization(),
        id_factory=lambda: "11111111-1111-4111-8111-111111115102",
        clock=lambda: NOW_DT,
    )
    work_item = work_service.create(_payload())["work_item"]
    values = iter(range(2, 100))
    repository = InMemoryCoordinationRepository(work_repository)
    service = WorkCoordinationService(
        repository,
        candidate_source=_Agents(candidates),
        authorization_source=claim_authorization or _Authorization(),
        id_factory=lambda: str(UUID(int=next(values))),
        token_factory=lambda: "private-lease-token-b5b2",
        clock=lambda: NOW_DT,
    )
    return work_repository, repository, service, work_item


def _heartbeat() -> WorkerHeartbeatEmitter:
    return WorkerHeartbeatEmitter(
        service_id="nex-wc",
        worker_id="wc-assignment-dispatch-b5b2",
        worker_type="wc.assignment.dispatch.worker",
        store=InMemoryWorkerHeartbeatStore(),
        started_at=NOW,
    )


def test_scheduler_is_state_bounded_idempotent_and_content_free() -> None:
    _, repository, _, work_item = _runtime()
    queue = InMemoryJobQueue()

    first = enqueue_claimable_assignment_jobs(
        repository=repository,
        queue=queue,
        state="CREATED",
        limit=10,
        created_at=NOW,
    )
    replay = enqueue_claimable_assignment_jobs(
        repository=repository,
        queue=queue,
        state="CREATED",
        limit=10,
        created_at=NOW,
    )

    assert first == replay
    assert first["action"] == ROUTE
    assert first["scanned_count"] == first["enqueued_count"] == 1
    assert len(queue.jobs) == 1
    assert first["next_cursor"]["work_item_id"] == work_item["work_item_id"]
    assert "goal" not in json.dumps(first)

    empty = enqueue_claimable_assignment_jobs(
        repository=repository,
        queue=queue,
        state="CREATED",
        limit=10,
        after=first["next_cursor"],
        created_at=NOW,
    )
    assert empty["scanned_count"] == empty["enqueued_count"] == 0
    assert empty["next_cursor"] == first["next_cursor"]


def test_handler_routes_claims_and_replays_without_exposing_lease_token() -> None:
    _, repository, service, _ = _runtime()
    queue = InMemoryJobQueue()
    enqueue_claimable_assignment_jobs(
        repository=repository,
        queue=queue,
        state="CREATED",
        limit=10,
        created_at=NOW,
    )
    route_job = next(iter(queue.jobs.values()))

    routed = run_assignment_dispatch_job(
        route_job,
        repository=repository,
        service=service,
    )
    route_replay = run_assignment_dispatch_job(
        route_job,
        repository=repository,
        service=service,
    )
    assert routed["outcome"] == "ROUTED"
    assert route_replay == {**routed, "outcome": "ROUTE_REPLAYED"}

    claim_queue = InMemoryJobQueue()
    enqueue_claimable_assignment_jobs(
        repository=repository,
        queue=claim_queue,
        state="ROUTED",
        limit=10,
        created_at=NOW,
    )
    claim_job = next(iter(claim_queue.jobs.values()))
    claimed = run_assignment_dispatch_job(
        claim_job,
        repository=repository,
        service=service,
    )
    claim_replay = run_assignment_dispatch_job(
        claim_job,
        repository=repository,
        service=service,
    )

    assert claimed["outcome"] == "CLAIMED"
    assert claim_replay == {**claimed, "outcome": "CLAIM_REPLAYED"}
    assert claimed["claim_generation"] == 1
    assert "private-lease-token-b5b2" not in json.dumps(claimed)
    assert repository.get_current_assignment_authority(
        tenant_id=TENANT,
        work_item_id=str(claim_job["request_id"]),
    ) is not None


def test_worker_completes_route_and_claim_with_shared_runner() -> None:
    _, repository, service, _ = _runtime()
    route_queue = InMemoryJobQueue()
    enqueue_claimable_assignment_jobs(
        repository=repository,
        queue=route_queue,
        state="CREATED",
        limit=1,
        created_at=NOW,
    )
    routed = run_assignment_dispatch_worker_once(
        queue=route_queue,
        heartbeat_emitter=_heartbeat(),
        repository=repository,
        service=service,
        worker_id="wc-assignment-dispatch-b5b2",
        clock=lambda: NOW,
    )
    assert routed.status == SUCCEEDED
    assert routed.handler_result["outcome"] == "ROUTED"

    claim_queue = InMemoryJobQueue()
    enqueue_claimable_assignment_jobs(
        repository=repository,
        queue=claim_queue,
        state="ROUTED",
        limit=1,
        created_at=NOW,
    )
    claimed = run_assignment_dispatch_worker_once(
        queue=claim_queue,
        heartbeat_emitter=_heartbeat(),
        repository=repository,
        service=service,
        worker_id="wc-assignment-dispatch-b5b2",
        clock=lambda: NOW,
    )
    assert claimed.status == SUCCEEDED
    assert claimed.handler_result["outcome"] == "CLAIMED"


def test_worker_requeues_no_capable_agent_with_backoff() -> None:
    _, repository, service, _ = _runtime(candidates=[])
    queue = InMemoryJobQueue()
    enqueue_claimable_assignment_jobs(
        repository=repository,
        queue=queue,
        state="CREATED",
        limit=1,
        created_at=NOW,
    )

    execution = run_assignment_dispatch_worker_once(
        queue=queue,
        heartbeat_emitter=_heartbeat(),
        repository=repository,
        service=service,
        worker_id="wc-assignment-dispatch-b5b2",
        clock=lambda: NOW,
    )

    assert execution.status == FAILED
    assert execution.error_code == "wc.assignment_no_eligible_agent"
    assert execution.completed_job["status"] == QUEUED
    assert execution.completed_job["error"]["retryable"] is True
    assert execution.completed_job["available_at"] > NOW


def test_worker_dead_letters_fresh_authorization_denial_without_mutation() -> None:
    _, repository, service, work_item = _runtime(
        claim_authorization=_Authorization(scopes=[])
    )
    service.route(
        tenant_id=TENANT,
        work_item_id=str(work_item["work_item_id"]),
        expected_version=1,
    )
    queue = InMemoryJobQueue()
    enqueue_claimable_assignment_jobs(
        repository=repository,
        queue=queue,
        state="ROUTED",
        limit=1,
        created_at=NOW,
    )

    execution = run_assignment_dispatch_worker_once(
        queue=queue,
        heartbeat_emitter=_heartbeat(),
        repository=repository,
        service=service,
        worker_id="wc-assignment-dispatch-b5b2",
        clock=lambda: NOW,
    )

    assert execution.error_code == "wc.claim_authorization_denied"
    assert execution.completed_job["status"] == FAILED
    current = repository.get_work_item(
        tenant_id=TENANT,
        work_item_id=str(work_item["work_item_id"]),
    )
    assert current["state"] == "ROUTED"
    assert current["version"] == 2
    assert repository.get_current_assignment_authority(
        tenant_id=TENANT,
        work_item_id=str(work_item["work_item_id"]),
    ) is None


@pytest.mark.parametrize("mode", ("MISSING", "STALE"))
def test_worker_dead_letters_terminal_or_unresolved_stale_authority(mode: str) -> None:
    work_repository, repository, service, work_item = _runtime()
    queue = InMemoryJobQueue()
    enqueue_claimable_assignment_jobs(
        repository=repository,
        queue=queue,
        state="CREATED",
        limit=1,
        created_at=NOW,
    )
    key = (TENANT, str(work_item["work_item_id"]))
    if mode == "MISSING":
        del work_repository._records[key]
        expected_error = "wc.work_item_not_found"
    else:
        record = work_repository._records[key]
        record["state"] = "ASSIGNED"
        record["version"] = 9
        record["work_item"]["state"] = "ASSIGNED"
        record["work_item"]["version"] = 9
        expected_error = "wc.assignment_dispatch_stale_unresolved"

    execution = run_assignment_dispatch_worker_once(
        queue=queue,
        heartbeat_emitter=_heartbeat(),
        repository=repository,
        service=service,
        worker_id="wc-assignment-dispatch-b5b2",
        clock=lambda: NOW,
    )

    assert execution.status == FAILED
    assert execution.error_code == expected_error
    assert execution.completed_job["status"] == FAILED
    assert execution.completed_job["retryable"] is False
    assert execution.completed_job["error"]["retryable"] is False


def test_handler_classifies_service_failures_and_invalid_jobs() -> None:
    _, repository, service, _ = _runtime()
    queue = InMemoryJobQueue()
    enqueue_claimable_assignment_jobs(
        repository=repository,
        queue=queue,
        state="CREATED",
        limit=1,
        created_at=NOW,
    )
    job = next(iter(queue.jobs.values()))
    malformed = {**job, "payload": {**job["payload"], "action": "EXECUTE"}}
    with pytest.raises(AssignmentDispatchExecutionError) as invalid:
        run_assignment_dispatch_job(
            malformed,
            repository=repository,
            service=service,
        )
    assert invalid.value.disposition == TERMINAL

    class _UnavailableService:
        def route(self, **_: object) -> dict[str, object]:
            error = RuntimeError("unavailable")
            error.error_code = "wc.agent_registry_unavailable"  # type: ignore[attr-defined]
            error.retryable = True  # type: ignore[attr-defined]
            raise error

        def claim(self, **_: object) -> dict[str, object]:
            raise AssertionError("claim must not be called")

    with pytest.raises(AssignmentDispatchExecutionError) as unavailable:
        run_assignment_dispatch_job(
            job,
            repository=repository,
            service=_UnavailableService(),
        )
    assert unavailable.value.disposition == RETRY

    stale = AssignmentDispatchExecutionError("stale", "stale", RELOAD)
    assert stale.disposition == RELOAD
    assert str(stale) == "stale"
    contract = AssignmentDispatchContractError("invalid", "invalid candidate")
    assert str(contract) == "invalid candidate"
    with pytest.raises(AssignmentDispatchContractError):
        validate_claimable_work_item("not-an-object")
    invalid_schema = {
        "schema_version": "invalid",
        "tenant_id": TENANT,
        "work_item_id": str(job["request_id"]),
        "state": "CREATED",
        "action": ROUTE,
        "expected_version": 1,
        "trace_id": str(job["trace_id"]),
        "created_at": NOW,
        "updated_at": NOW,
    }
    with pytest.raises(AssignmentDispatchContractError):
        validate_claimable_work_item(invalid_schema)


def test_current_assignment_authority_requires_complete_active_chain() -> None:
    _, repository, service, work_item = _runtime()
    work_item_id = str(work_item["work_item_id"])
    assert repository.get_current_assignment_authority(
        tenant_id=TENANT, work_item_id=work_item_id
    ) is None
    service.route(tenant_id=TENANT, work_item_id=work_item_id, expected_version=1)
    service.claim(tenant_id=TENANT, work_item_id=work_item_id, expected_version=2)
    key = (TENANT, work_item_id)
    claim = repository._claims[key][0]
    claim["state"] = "EXPIRED"
    assert repository.get_current_assignment_authority(
        tenant_id=TENANT, work_item_id=work_item_id
    ) is None
    claim["state"] = "ACTIVE"
    outbox_key = next(iter(repository._outbox))
    outbox = repository._outbox.pop(outbox_key)
    assert repository.get_current_assignment_authority(
        tenant_id=TENANT, work_item_id=work_item_id
    ) is None
    repository._outbox[outbox_key] = outbox
    repository._assignments[key]["status"] = "RELEASED"
    assert repository.get_current_assignment_authority(
        tenant_id=TENANT, work_item_id=work_item_id
    ) is None


def test_sql_assignment_authority_mapping_none_and_store_failure() -> None:
    class _Result:
        def __init__(self, row: dict[str, object] | None) -> None:
            self.row = row

        def mappings(self) -> _Result:
            return self

        def first(self) -> dict[str, object] | None:
            return self.row

    class _Session:
        def __init__(
            self,
            row: dict[str, object] | None,
            error: bool = False,
        ) -> None:
            self.row = row
            self.error = error

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(self, *_: object, **__: object) -> _Result:
            if self.error:
                raise SQLAlchemyError("unavailable")
            return _Result(self.row)

    empty = SqlAlchemyCoordinationRepository(lambda: _Session(None))
    assert empty.get_current_assignment_authority(
        tenant_id=TENANT,
        work_item_id="11111111-1111-4111-8111-111111115104",
    ) is None

    row = {
        "assignment_id": UUID(int=301),
        "work_item_id": UUID(int=302),
        "agent_id": UUID(int=303),
        "agent_type": "PA",
        "project_id": PROJECT,
        "claim_generation": 2,
        "status": "ACTIVE",
        "agent_execution_id": None,
        "claim_id": UUID(int=304),
        "claim_state": "ACTIVE",
        "claim_assignment_id": UUID(int=301),
        "claim_claim_generation": 2,
        "lease_verifier": "sha256:" + "b" * 64,
        "lease_expires_at": NOW_DT,
        "authorization_revision_hash": "sha256:" + "c" * 64,
        "outbox_id": UUID(int=305),
        "event_id": UUID(int=306),
    }
    mapped = SqlAlchemyCoordinationRepository(lambda: _Session(row))
    authority = mapped.get_current_assignment_authority(
        tenant_id=TENANT,
        work_item_id=str(row["work_item_id"]),
    )
    assert authority["assignment"]["agent_execution_id"] is None
    assert authority["claim"]["claim_generation"] == 2

    row["agent_execution_id"] = UUID(int=307)
    with_execution = mapped.get_current_assignment_authority(
        tenant_id=TENANT,
        work_item_id=str(row["work_item_id"]),
    )
    assert with_execution["assignment"]["agent_execution_id"] == str(
        row["agent_execution_id"]
    )

    unavailable = SqlAlchemyCoordinationRepository(lambda: _Session(None, True))
    with pytest.raises(Exception) as error:
        unavailable.get_current_assignment_authority(
            tenant_id=TENANT,
            work_item_id=str(row["work_item_id"]),
        )
    assert getattr(error.value, "error_code", None) == "wc.coordination_store_unavailable"


@pytest.mark.skipif(
    not os.getenv("NEX_WC_TEST_DATABASE_URL"),
    reason="NEX_WC_TEST_DATABASE_URL is required for protected WC PostgreSQL smoke",
)
def test_actual_postgres_scheduler_handler_restart_replay_and_zero_residue() -> None:
    engine = create_engine(os.environ["NEX_WC_TEST_DATABASE_URL"])
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    work_item_id = "11111111-1111-4111-8111-111111115103"
    postgres_now_dt = datetime(2099, 1, 1, 0, 0, 1, tzinfo=UTC)
    postgres_now = "2099-01-01T00:00:01Z"
    cursor = {
        "created_at": "2099-01-01T00:00:00Z",
        "tenant_id": "0",
        "work_item_id": "00000000-0000-0000-0000-000000000000",
    }

    def cleanup() -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM service_jobs "
                    "WHERE job_type = 'WC_ASSIGNMENT_DISPATCH' "
                    "AND request_id = :work_item_id"
                ),
                {"work_item_id": work_item_id},
            )
            for table in (
                "wc_event_outbox",
                "wc_claim",
                "wc_assignment",
                "wc_routing_decision",
                "wc_work_item",
            ):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": TENANT},
                )

    cleanup()
    try:
        item = WorkItemService(
            SqlAlchemyWorkItemRepository(sessions),
            authorization_source=_Authorization(),
            id_factory=lambda: work_item_id,
            clock=lambda: postgres_now_dt,
        ).create(_payload())["work_item"]
        identifiers = iter(range(200, 250))
        repository = SqlAlchemyCoordinationRepository(sessions)
        service = WorkCoordinationService(
            repository,
            candidate_source=_Agents(),
            authorization_source=_Authorization(),
            id_factory=lambda: str(UUID(int=next(identifiers))),
            token_factory=lambda: "postgres-private-lease-b5b2",
            clock=lambda: postgres_now_dt,
        )
        queue = SqlAlchemyJobQueue(sessions)

        route_schedule = enqueue_claimable_assignment_jobs(
            repository=repository,
            queue=queue,
            state="CREATED",
            limit=100,
            after=cursor,
            created_at=postgres_now,
        )
        assert route_schedule["enqueued_count"] >= 1
        route_execution = run_assignment_dispatch_worker_once(
            queue=queue,
            heartbeat_emitter=_heartbeat(),
            repository=repository,
            service=service,
            worker_id="wc-assignment-dispatch-postgres-b5b2",
            clock=lambda: postgres_now,
        )
        assert route_execution.status == SUCCEEDED

        claim_schedule = enqueue_claimable_assignment_jobs(
            repository=repository,
            queue=queue,
            state="ROUTED",
            limit=100,
            after=cursor,
            created_at=postgres_now,
        )
        assert claim_schedule["enqueued_count"] >= 1
        claim_execution = run_assignment_dispatch_worker_once(
            queue=queue,
            heartbeat_emitter=_heartbeat(),
            repository=repository,
            service=service,
            worker_id="wc-assignment-dispatch-postgres-b5b2",
            clock=lambda: postgres_now,
        )
        assert claim_execution.status == SUCCEEDED
        assert "postgres-private-lease-b5b2" not in json.dumps(
            claim_execution.handler_result
        )

        restarted = SqlAlchemyCoordinationRepository(sessions)
        authority = restarted.get_current_assignment_authority(
            tenant_id=TENANT,
            work_item_id=str(item["work_item_id"]),
        )
        replay = run_assignment_dispatch_job(
            claim_execution.job,
            repository=restarted,
            service=service,
        )
        assert authority is not None
        assert replay["outcome"] == "CLAIM_REPLAYED"
        assert replay["assignment_id"] == authority["assignment"]["assignment_id"]
        with engine.connect() as connection:
            counts = {
                table: connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": TENANT},
                ).scalar_one()
                for table in (
                    "wc_work_item",
                    "wc_routing_decision",
                    "wc_assignment",
                    "wc_claim",
                    "wc_event_outbox",
                )
            }
        assert set(counts.values()) == {1}
    finally:
        cleanup()
        with engine.connect() as connection:
            residue = connection.execute(
                text("SELECT count(*) FROM wc_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one()
        engine.dispose()
    assert residue == 0
