from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from nex_runtime import InMemoryJobQueue
from nex_wc.assignment_dispatch import (
    RECLAIM,
    enqueue_recoverable_assignment_jobs,
    run_assignment_dispatch_job,
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
from sqlalchemy.orm import sessionmaker

TENANT = "tenant-01b7e"
PROJECT = "project-01b7e"
WORK_ITEM_ID = "11111111-1111-4111-8111-11111111117e"
AGENT_ID = "22222222-2222-4222-8222-22222222227e"


class _Agents:
    def list_agents(self, **_kwargs):
        return [self.get_agent()]

    def get_agent(self, **_kwargs):
        return {
            "schema_version": "2.1",
            "tenant_id": TENANT,
            "agent_id": AGENT_ID,
            "agent_type": "PA",
            "profile_ref": "agent-profile://nex-platform/project-agent/v1",
            "status": "ACTIVE",
            "project_id": PROJECT,
            "created_at": "2026-11-19T01:00:00Z",
            "version": 1,
        }


class _Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate", "work:claim"],
            "revision_hash": "sha256:" + "a" * 64,
        }


def _work_item() -> dict[str, object]:
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-01b7e",
            "tenant_id": TENANT,
            "parent_agent_execution_id": "parent-execution-01b7e",
            "parent_executable_plan_id": "parent-plan-01b7e",
            "parent_executable_step_id": "parent-step-01b7e",
            "delegation_revision": 1,
            "goal": "Run a product-neutral recovery check.",
            "work_class": "BUSINESS_TRANSACTION",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.VOUCHER.APPROVE_AND_POST",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": "urn:nex:result:01b7e:v1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "trace-01b7e",
            "causation_id": "cause-01b7e",
        },
        "requester": {"entity_type": "USER", "entity_id": "requester-01b7e"},
        "accountable_owner": {
            "entity_type": "USER",
            "entity_id": "owner-01b7e",
        },
    }


def _claimed_runtime():
    clock = [datetime(2026, 11, 19, 1, 0, tzinfo=UTC)]
    work_items = InMemoryWorkItemRepository()
    repository = InMemoryCoordinationRepository(work_items)
    identifiers = iter(range(1, 100))
    service = WorkCoordinationService(
        repository,
        candidate_source=_Agents(),
        authorization_source=_Authorization(),
        id_factory=lambda: str(UUID(int=next(identifiers))),
        token_factory=lambda: "private-lease-token-01b7e",
        clock=lambda: clock[0],
        lease_seconds=60,
    )
    created = WorkItemService(
        work_items,
        authorization_source=_Authorization(),
        id_factory=lambda: WORK_ITEM_ID,
        clock=lambda: clock[0],
    ).create(_work_item())
    service.route(
        tenant_id=TENANT,
        work_item_id=WORK_ITEM_ID,
        expected_version=created["work_item"]["version"],
    )
    claimed = service.claim(
        tenant_id=TENANT,
        work_item_id=WORK_ITEM_ID,
        expected_version=2,
    )
    return clock, repository, service, claimed


def _time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def test_expired_unbound_claim_is_recovered_through_existing_claim_authority() -> None:
    clock, repository, service, first = _claimed_runtime()
    clock[0] += timedelta(seconds=61)
    queue = InMemoryJobQueue()

    scan = enqueue_recoverable_assignment_jobs(
        repository=repository,
        queue=queue,
        observed_at=_time(clock[0]),
        limit=10,
        created_at=_time(clock[0]),
    )

    assert scan["action"] == RECLAIM
    assert scan["scanned_count"] == scan["enqueued_count"] == 1
    job = queue.get_job(scan["job_ids"][0])
    result = run_assignment_dispatch_job(
        job,
        repository=repository,
        service=service,
    )
    claims = repository._claims[(TENANT, WORK_ITEM_ID)]
    assert result["outcome"] == "CLAIM_RECLAIMED"
    assert result["claim_generation"] == 2
    assert [(item["claim_generation"], item["state"]) for item in claims] == [
        (1, "EXPIRED"),
        (2, "ACTIVE"),
    ]
    assert repository._outbox[(TENANT, first["outbox_id"])]["delivery_state"] == (
        "FAILED"
    )


def test_execution_bound_or_inflight_handoff_is_never_reclaimed() -> None:
    for boundary in ("INFLIGHT", "EXECUTION_BOUND"):
        clock, repository, _service, claimed = _claimed_runtime()
        outbox = repository._outbox[(TENANT, claimed["outbox_id"])]
        if boundary == "INFLIGHT":
            outbox["delivery_state"] = "ENQUEUED"
        else:
            outbox["delivery_state"] = "ENQUEUED"
            outbox["enqueued_job_id"] = "delivery-job-01b7e"
            repository.mark_handoff_delivered(
                outbox_id=claimed["outbox_id"],
                event_id=claimed["event_id"],
                job_id="delivery-job-01b7e",
                updated_at=_time(clock[0]),
                agent_execution_id="execution-01b7e",
            )
        clock[0] += timedelta(seconds=61)

        assert repository.list_recoverable_work_items(
            observed_at=_time(clock[0]), limit=10
        ) == []


@pytest.mark.skipif(
    not os.getenv("NEX_WC_TEST_DATABASE_URL"),
    reason="NEX_WC_TEST_DATABASE_URL is required for protected WC PostgreSQL smoke",
)
def test_actual_postgres_expired_unbound_claim_recovery_is_zero_residue() -> None:
    engine = create_engine(os.environ["NEX_WC_TEST_DATABASE_URL"])
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    now = [datetime(2099, 1, 2, 1, 0, tzinfo=UTC)]
    work_item_id = "11111111-1111-4111-8111-11111111118e"

    def cleanup() -> None:
        with engine.begin() as connection:
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
        created = WorkItemService(
            SqlAlchemyWorkItemRepository(sessions),
            authorization_source=_Authorization(),
            id_factory=lambda: work_item_id,
            clock=lambda: now[0],
        ).create(_work_item())["work_item"]
        identifiers = iter(range(1000, 1100))
        repository = SqlAlchemyCoordinationRepository(sessions)
        service = WorkCoordinationService(
            repository,
            candidate_source=_Agents(),
            authorization_source=_Authorization(),
            id_factory=lambda: str(UUID(int=next(identifiers))),
            token_factory=lambda: "postgres-private-lease-01b7e",
            clock=lambda: now[0],
            lease_seconds=60,
        )
        service.route(
            tenant_id=TENANT,
            work_item_id=work_item_id,
            expected_version=created["version"],
        )
        service.claim(
            tenant_id=TENANT,
            work_item_id=work_item_id,
            expected_version=2,
        )
        now[0] += timedelta(seconds=61)
        queue = InMemoryJobQueue()
        scan = enqueue_recoverable_assignment_jobs(
            repository=repository,
            queue=queue,
            observed_at=_time(now[0]),
            limit=10,
            created_at=_time(now[0]),
        )
        recovered = run_assignment_dispatch_job(
            queue.get_job(scan["job_ids"][0]),
            repository=repository,
            service=service,
        )
        with engine.connect() as connection:
            generations = connection.execute(
                text(
                    "SELECT claim_generation, state FROM wc_claim "
                    "WHERE tenant_id=:tenant_id AND work_item_id=:work_item_id "
                    "ORDER BY claim_generation"
                ),
                {"tenant_id": TENANT, "work_item_id": work_item_id},
            ).all()
        assert recovered["outcome"] == "CLAIM_RECLAIMED"
        assert [(row[0], row[1]) for row in generations] == [
            (1, "EXPIRED"),
            (2, "ACTIVE"),
        ]
    finally:
        cleanup()
        with engine.connect() as connection:
            residue = connection.execute(
                text("SELECT count(*) FROM wc_work_item WHERE tenant_id=:tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one()
        engine.dispose()
    assert residue == 0
