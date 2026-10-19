from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from nex_ae_api.multi_step_engine import SqlAlchemyMultiStepEngine
from nex_ae_api.runtime_jobs import RuntimeJobClaim, SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_executors import (
    DelegateWorkExecutorDependencies,
    P5StepExecutionWorker,
    P5StepExecutorRegistry,
    P7DelegateWorkExecutor,
)
from nex_ae_api.work_result_publication import (
    SqlAlchemyWcWorkResultPublisher,
    WorkResultPublicationError,
)
from nex_ae_api.work_result_resume import (
    SqlAlchemyWorkResultResumeSource,
    WorkResultResumeError,
)
from nex_runtime import InMemoryJobQueue
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc import coordination as wc_coordination
from nex_wc import handoff_delivery as wc_handoff_delivery
from nex_wc.coordination import (
    CoordinationError,
    InMemoryCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.handoff_delivery import (
    HandoffDeliveryError,
    enqueue_pending_handoffs,
    run_handoff_delivery_job,
)
from nex_wc.work_items import InMemoryWorkItemRepository, WorkItemService
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from test_nex_ae_multi_step_engine import (
    EXECUTION_ID,
    PLAN_ID,
    STEP_1_ID,
    TENANT,
)
from test_nex_ae_multi_step_engine import (
    _factory as multi_step_factory,
)

NOW_DT = datetime(2026, 10, 19, 1, 0, tzinfo=UTC)
NOW = "2026-10-19T01:00:00Z"
LATER = "2026-10-19T01:10:00Z"
WORK_ITEM_ID = "11111111-1111-4111-8111-111111111118"
AGENT_ID = "22222222-2222-4222-8222-222222222228"
DELIVERY_ID = "33333333-3333-4333-8333-333333333338"
CHILD_EXECUTION_ID = "44444444-4444-4444-8444-444444444448"
RESULT_ID = "result-p7-s8"
WAIT_ID = "55555555-5555-4555-8555-555555555558"
EVENT_ID = "66666666-6666-4666-8666-666666666668"
RESUME_JOB_ID = "77777777-7777-4777-8777-777777777778"
RESULT_CONTRACT = "urn:nex:result:p7-s8:1"


class _Agents:
    def list_agents(self, **_kwargs):
        return [self.get_agent()]

    def get_agent(self, **_kwargs):
        return {
            "schema_version": "2.1",
            "tenant_id": "tenant-p7-s8",
            "agent_id": AGENT_ID,
            "agent_type": "PA",
            "profile_ref": "agent-profile://pa/project-budget-read/v1",
            "status": "ACTIVE",
            "project_id": "project-p7-s8",
            "created_at": NOW,
            "version": 1,
        }


class _Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:claim"],
            "revision_hash": "a" * 64,
        }


def _work_payload() -> dict[str, object]:
    return {
        "work_item_id": WORK_ITEM_ID,
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-p7-s8",
            "tenant_id": "tenant-p7-s8",
            "parent_agent_execution_id": EXECUTION_ID,
            "parent_executable_plan_id": PLAN_ID,
            "parent_executable_step_id": STEP_1_ID,
            "delegation_revision": 1,
            "goal": "Verify restart-safe delivery.",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": "project-p7-s8"},
            "project_scope_ref": "project-p7-s8",
            "result_contract_ref": RESULT_CONTRACT,
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "correlation-p7-s8",
            "causation_id": STEP_1_ID,
        },
        "requester": {"entity_type": "USER", "entity_id": "user-p7-s8"},
        "accountable_owner": {
            "entity_type": "USER",
            "entity_id": "user-p7-s8",
        },
    }


def test_expired_claim_reclaim_increments_generation_and_blocks_stale_handoff() -> None:
    clock = [NOW_DT]
    work_repository = InMemoryWorkItemRepository()
    item = WorkItemService(work_repository, clock=lambda: clock[0]).create(
        _work_payload()
    )["work_item"]
    ids = iter(
        f"00000000-0000-4000-8000-{value:012d}" for value in range(1, 30)
    )
    repository = InMemoryCoordinationRepository(work_repository)
    service = WorkCoordinationService(
        repository,
        candidate_source=_Agents(),
        authorization_source=_Authorization(),
        id_factory=lambda: next(ids),
        token_factory=lambda: "lease-p7-s8",
        clock=lambda: clock[0],
        lease_seconds=300,
    )
    service.route(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=1
    )
    first = service.claim(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=2
    )
    queue = InMemoryJobQueue()
    stale_job = enqueue_pending_handoffs(
        store=repository, queue=queue, clock=lambda: clock[0]
    )[0]

    with pytest.raises(CoordinationError) as active:
        service.claim(
            tenant_id=item["tenant_id"],
            work_item_id=item["work_item_id"],
            expected_version=3,
        )
    assert active.value.error_code == "wc.active_claim_exists"

    clock[0] += timedelta(seconds=301)
    second = service.claim(
        tenant_id=item["tenant_id"], work_item_id=item["work_item_id"], expected_version=3
    )
    claims = repository._claims[(item["tenant_id"], item["work_item_id"])]
    assert [(claim["claim_generation"], claim["state"]) for claim in claims] == [
        (1, "EXPIRED"),
        (2, "ACTIVE"),
    ]
    assert second["claim"]["claim_generation"] == 2
    assert repository._outbox[(item["tenant_id"], first["outbox_id"])][
        "delivery_state"
    ] == "FAILED"

    delivered = []
    client = SimpleNamespace(deliver=lambda envelope: delivered.append(envelope) or {})
    with pytest.raises(HandoffDeliveryError) as stale:
        run_handoff_delivery_job(
            stale_job,
            store=repository,
            client=client,
            clock=lambda: clock[0],
        )
    assert stale.value.error_code == "wc.handoff_claim_stale"
    assert delivered == []

    clock[0] += timedelta(seconds=301)
    repository._assignments.pop((item["tenant_id"], item["work_item_id"]))
    with pytest.raises(CoordinationError) as missing_assignment:
        service.claim(
            tenant_id=item["tenant_id"],
            work_item_id=item["work_item_id"],
            expected_version=4,
        )
    assert missing_assignment.value.error_code == "wc.claim_recovery_conflict"


def test_claim_timestamp_and_handoff_lease_corruption_fail_closed() -> None:
    with pytest.raises(HandoffDeliveryError) as missing_claim_ref:
        wc_handoff_delivery._required({}, "claim_ref")
    assert missing_claim_ref.value.error_code == "wc.handoff_value_invalid"

    for value in (None, "not-a-time", "2026-10-19T01:00:00"):
        with pytest.raises(CoordinationError) as invalid:
            wc_coordination._parse_time(value)
        assert invalid.value.error_code == "wc.coordination_store_invalid"

    handoff = {"claim_ref": "claim-p7-s8", "claim_generation": 2}
    authority = {
        "delivery_state": "ENQUEUED",
        "claim_state": "ACTIVE",
        "assignment_status": "ACTIVE",
        "active_claim_id": "claim-p7-s8",
        "claim_generation": 2,
        "claim_lease_expires_at": LATER,
    }
    wc_handoff_delivery._require_current_claim_authority(
        authority, handoff, NOW_DT
    )
    assert wc_handoff_delivery._datetime(NOW) == NOW_DT
    assert wc_handoff_delivery._datetime(NOW_DT) is NOW_DT

    for lease, code in (
        ("not-a-time", "wc.handoff_claim_authority_invalid"),
        ("2026-10-19T01:10:00", "wc.handoff_claim_authority_invalid"),
        (NOW, "wc.handoff_claim_expired"),
    ):
        with pytest.raises(HandoffDeliveryError) as rejected:
            wc_handoff_delivery._require_current_claim_authority(
                {**authority, "claim_lease_expires_at": lease},
                handoff,
                NOW_DT + timedelta(seconds=1),
            )
        assert rejected.value.error_code == code


def _publisher_factory():
    engine = create_engine("sqlite+pysqlite://", future=True)
    result = {
        "tenant_id": "tenant-p7-s8",
        "result_id": RESULT_ID,
        "agent_execution_id": CHILD_EXECUTION_ID,
        "agent_id": AGENT_ID,
        "status": "SUCCEEDED",
        "result_hash": "sha256:" + "b" * 64,
        "structured_result": {"result_ref": "AE:RESULT:p7-s8"},
        "artifact_refs": [],
        "evidence_refs": [],
        "business_refs": [],
        "provenance": {"executable_plan_id": PLAN_ID},
    }
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ae_agent_execution (
                tenant_id TEXT, agent_execution_id TEXT, agent_id TEXT,
                agent_type TEXT, project_id TEXT, work_item_ref TEXT,
                claim_ref TEXT, claim_generation INTEGER, assignment_ref TEXT,
                correlation_id TEXT, causation_id TEXT, state TEXT, phase TEXT,
                result_id TEXT, completed_at TEXT, updated_at TEXT, version INTEGER,
                PRIMARY KEY (tenant_id, agent_execution_id))
        """))
        connection.execute(text("""
            CREATE TABLE ae_agent_result (
                tenant_id TEXT, result_id TEXT, result_envelope_json TEXT,
                PRIMARY KEY (tenant_id, result_id))
        """))
        connection.execute(text("""
            CREATE TABLE ae_result_delivery (
                tenant_id TEXT, delivery_id TEXT, result_id TEXT,
                agent_execution_id TEXT, target_type TEXT, target_ref TEXT,
                state TEXT, attempt_no INTEGER, external_delivery_ref TEXT,
                latest_preflight_ref TEXT, created_at TEXT, updated_at TEXT,
                acknowledged_at TEXT, PRIMARY KEY (tenant_id, delivery_id))
        """))
        connection.execute(text("""
            CREATE TABLE ae_claim_handoff_inbox (
                tenant_id TEXT, agent_execution_id TEXT, planning_source_json TEXT,
                PRIMARY KEY (tenant_id, agent_execution_id))
        """))
        connection.execute(
            text("INSERT INTO ae_agent_execution VALUES "
                 "(:t,:e,:a,'PA','project-p7-s8',:w,:c,1,:assignment,'corr','cause',"
                 "'RUNNING','RESULT_PUBLISH',:r,NULL,:now,1)"),
            {
                "t": "tenant-p7-s8",
                "e": CHILD_EXECUTION_ID,
                "a": AGENT_ID,
                "w": WORK_ITEM_ID,
                "c": "88888888-8888-4888-8888-888888888888",
                "assignment": "99999999-9999-4999-8999-999999999999",
                "r": RESULT_ID,
                "now": NOW,
            },
        )
        connection.execute(
            text("INSERT INTO ae_agent_result VALUES (:t,:r,:payload)"),
            {"t": "tenant-p7-s8", "r": RESULT_ID, "payload": json.dumps(result)},
        )
        connection.execute(
            text("INSERT INTO ae_result_delivery VALUES "
                 "(:t,:d,:r,:e,'WC_WORK_RESULT',:w,'PENDING',0,NULL,NULL,:now,:now,NULL)"),
            {
                "t": "tenant-p7-s8",
                "d": DELIVERY_ID,
                "r": RESULT_ID,
                "e": CHILD_EXECUTION_ID,
                "w": WORK_ITEM_ID,
                "now": NOW,
            },
        )
        connection.execute(
            text("INSERT INTO ae_claim_handoff_inbox VALUES (:t,:e,:source)"),
            {
                "t": "tenant-p7-s8",
                "e": CHILD_EXECUTION_ID,
                "source": json.dumps({"result_contract_ref": RESULT_CONTRACT}),
            },
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_work_result_response_loss_retries_identical_semantics() -> None:
    factory = _publisher_factory()

    class _AcceptedThenLost:
        def __init__(self) -> None:
            self.results: list[dict[str, object]] = []

        def status(self, **_kwargs):
            return {"version": 3 + len(self.results)}

        def submit(self, *, work_result, **_kwargs):
            proposed = dict(work_result)
            self.results.append(proposed)
            if len(self.results) == 1:
                raise WorkResultPublicationError(
                    "ae.wc_work_result_unavailable", "response lost", True
                )
            return {
                "created": False,
                "work_item_id": WORK_ITEM_ID,
                "work_item_version": 4,
                "result_id": RESULT_ID,
                "result_hash": semantic_sha256_hash_ref(proposed),
            }

    client = _AcceptedThenLost()
    publisher = SqlAlchemyWcWorkResultPublisher(factory, client)
    with pytest.raises(WorkResultPublicationError):
        publisher.publish(
            tenant_id="tenant-p7-s8", delivery_id=DELIVERY_ID, now=NOW
        )
    accepted = publisher.publish(
        tenant_id="tenant-p7-s8", delivery_id=DELIVERY_ID, now=LATER
    )

    assert client.results[0] == client.results[1]
    assert client.results[0]["submitted_at"] == NOW
    assert accepted["delivery_state"] == "ACKNOWLEDGED"


def _work_result_event() -> dict[str, object]:
    return {
        "schema_version": "2.1",
        "event_id": EVENT_ID,
        "event_name": "WORK_RESULT_SUBMITTED",
        "tenant_id": TENANT,
        "work_item_id": WORK_ITEM_ID,
        "result_id": RESULT_ID,
        "revision_no": 1,
        "result_type": "AGENT_RESULT",
        "result_schema_ref": RESULT_CONTRACT,
        "technical_outcome": "SUCCEEDED",
        "business_outcome": "VERIFIED",
        "source_execution_ref": CHILD_EXECUTION_ID,
        "claim_ref": "88888888-8888-4888-8888-888888888888",
        "claim_generation": 1,
        "assignment_ref": "99999999-9999-4999-8999-999999999999",
        "submitted_by": {"entity_type": "AGENT", "entity_id": AGENT_ID},
        "resume_match_ref": WORK_ITEM_ID,
        "correlation_id": "corr",
        "causation_id": RESULT_ID,
        "occurred_at": NOW,
    }


def _resume_claim(**job_overrides) -> RuntimeJobClaim:
    job = {
        "tenant_id": TENANT,
        "runtime_job_id": RESUME_JOB_ID,
        "job_type": "RESUME_EXECUTION",
        "state": "RUNNING",
        "wait_id": WAIT_ID,
        "payload": {
            "wait_id": WAIT_ID,
            "event_id": EVENT_ID,
            "result_id": RESULT_ID,
            "external_ref": WORK_ITEM_ID,
        },
        **job_overrides,
    }
    return RuntimeJobClaim(job=job, attempt={})


def test_work_result_resume_source_fails_closed_without_exact_authority() -> None:
    engine = create_engine("sqlite+pysqlite://", future=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ae_external_event_inbox (
                tenant_id TEXT, event_id TEXT, result_id TEXT, external_ref TEXT,
                event_payload TEXT, state TEXT)
        """))
        connection.execute(text("""
            CREATE TABLE ae_wait_registration (
                tenant_id TEXT, wait_id TEXT, matched_event_id TEXT, state TEXT,
                resume_runtime_job_id TEXT)
        """))
    source = SqlAlchemyWorkResultResumeSource(factory)

    with pytest.raises(WorkResultResumeError) as wrong_type:
        source.resolve(object())
    assert wrong_type.value.error_code == "ae.work_result_resume_invalid"
    assert str(wrong_type.value) == wrong_type.value.detail

    with pytest.raises(WorkResultResumeError) as malformed:
        source.resolve(_resume_claim(state="QUEUED"))
    assert malformed.value.error_code == "ae.work_result_resume_invalid"

    with pytest.raises(WorkResultResumeError) as missing:
        source.resolve(_resume_claim())
    assert missing.value.error_code == "ae.work_result_resume_authority_missing"
    assert missing.value.retryable is False


def test_work_result_resume_source_types_store_failure() -> None:
    source = SqlAlchemyWorkResultResumeSource(_publisher_factory())

    with pytest.raises(WorkResultResumeError) as unavailable:
        source.resolve(_resume_claim())

    assert unavailable.value.error_code == "ae.work_result_resume_store_unavailable"
    assert unavailable.value.retryable is True


def test_resume_crash_after_step_commit_recovers_without_duplicate_step_result() -> None:
    factory = multi_step_factory()
    event = _work_result_event()
    with factory.begin() as session:
        for statement in (
            "ALTER TABLE ae_wait_registration ADD COLUMN matched_event_id TEXT",
            "ALTER TABLE ae_wait_registration ADD COLUMN resume_runtime_job_id TEXT",
            "ALTER TABLE ae_wait_registration ADD COLUMN updated_at TEXT",
        ):
            session.execute(text(statement))
        session.execute(text("""
            CREATE TABLE ae_external_event_inbox (
                tenant_id TEXT, event_id TEXT, result_id TEXT, external_ref TEXT,
                event_payload TEXT, state TEXT, PRIMARY KEY (tenant_id, event_id))
        """))
        session.execute(
            text("UPDATE ae_agent_execution SET state='WAITING_DEPENDENCY', "
                 "phase='STEP_EXECUTION' WHERE tenant_id=:tenant_id"),
            {"tenant_id": TENANT},
        )
        session.execute(
            text("UPDATE ae_executable_step SET step_type='DELEGATE_WORK', "
                 "executor_kind='WC_DELEGATE_WORK', state='WAITING', version=2, "
                 "output_contract_ref=:contract WHERE tenant_id=:tenant_id "
                 "AND executable_step_id=:step_id"),
            {"contract": RESULT_CONTRACT, "tenant_id": TENANT, "step_id": STEP_1_ID},
        )
        session.execute(
            text("INSERT INTO ae_wait_registration VALUES "
                 "(:wait_id,:tenant_id,:execution_id,:step_id,'WORK_RESULT',:external_ref,"
                 ":contract,'RESUME_QUEUED',2,:now,:now,:event_id,:job_id,:now)"),
            {
                "wait_id": WAIT_ID,
                "tenant_id": TENANT,
                "execution_id": EXECUTION_ID,
                "step_id": STEP_1_ID,
                "external_ref": WORK_ITEM_ID,
                "contract": RESULT_CONTRACT,
                "now": NOW,
                "event_id": EVENT_ID,
                "job_id": RESUME_JOB_ID,
            },
        )
        session.execute(
            text("INSERT INTO ae_external_event_inbox VALUES "
                 "(:tenant_id,:event_id,:result_id,:external_ref,:payload,'MATCHED')"),
            {
                "tenant_id": TENANT,
                "event_id": EVENT_ID,
                "result_id": RESULT_ID,
                "external_ref": WORK_ITEM_ID,
                "payload": json.dumps(event),
            },
        )

    ids = iter(
        (
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa8",
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb8",
            "cccccccc-cccc-4ccc-8ccc-ccccccccccc8",
            "dddddddd-dddd-4ddd-8ddd-ddddddddddd8",
        )
    )
    queue = SqlAlchemyRuntimeJobQueue(factory, id_factory=lambda: next(ids))
    queue.enqueue_unique(
        tenant_id=TENANT,
        runtime_job_id=RESUME_JOB_ID,
        job_type="RESUME_EXECUTION",
        execution_id=EXECUTION_ID,
        executable_step_id=STEP_1_ID,
        wait_id=WAIT_ID,
        dedup_key=f"p7:resume:{WAIT_ID}:{EVENT_ID}",
        run_after=NOW,
        payload={
            "wait_id": WAIT_ID,
            "event_id": EVENT_ID,
            "result_id": RESULT_ID,
            "external_ref": WORK_ITEM_ID,
        },
        correlation_id="corr",
        causation_id=EVENT_ID,
        now=NOW,
    )
    source = SqlAlchemyWorkResultResumeSource(factory)
    dependencies = DelegateWorkExecutorDependencies(
        runtime_repository=SimpleNamespace(load=lambda **_kwargs: {}),
        wait_repository=SimpleNamespace(register=lambda **_kwargs: {}),
        work_item_client=SimpleNamespace(create_work_item=lambda _payload: {}),
    )
    registry = P5StepExecutorRegistry(
        {"WC_DELEGATE_WORK": P7DelegateWorkExecutor(dependencies=dependencies)}
    )
    engine = SqlAlchemyMultiStepEngine(
        factory,
        queue,
        id_factory=lambda: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee8",
    )

    class _CrashAfterCommitQueue:
        def complete(self, **_kwargs):
            raise RuntimeError("simulated process crash after StepResult commit")

        def fail(self, **kwargs):
            return queue.fail(**kwargs)

    first_claim = queue.claim(
        tenant_id=TENANT, worker_id="worker-p7-s8", lease_seconds=60, now=NOW
    )
    assert first_claim is not None
    crashing_worker = P5StepExecutionWorker(
        engine=engine,
        jobs=_CrashAfterCommitQueue(),
        executors=registry,
        continuation_source=source,
        clock=lambda: datetime.fromisoformat(NOW.replace("Z", "+00:00")),
    )
    with pytest.raises(RuntimeError, match="simulated process crash"):
        crashing_worker.run_claim(tenant_id=TENANT, claim=first_claim)

    recovery_at = (NOW_DT + timedelta(seconds=61)).isoformat().replace("+00:00", "Z")
    recovered_claim = queue.claim(
        tenant_id=TENANT,
        worker_id="worker-p7-s8-restarted",
        lease_seconds=60,
        now=recovery_at,
    )
    assert recovered_claim is not None
    recovered = P5StepExecutionWorker(
        engine=engine,
        jobs=queue,
        executors=registry,
        continuation_source=source,
        clock=lambda: NOW_DT + timedelta(seconds=61),
    ).run_claim(tenant_id=TENANT, claim=recovered_claim)

    with factory() as session:
        step_result_count = session.execute(
            text("SELECT count(*) FROM ae_step_result WHERE tenant_id=:tenant_id "
                 "AND executable_step_id=:step_id"),
            {"tenant_id": TENANT, "step_id": STEP_1_ID},
        ).scalar_one()
        wait_state = session.execute(
            text("SELECT state FROM ae_wait_registration WHERE tenant_id=:tenant_id "
                 "AND wait_id=:wait_id"),
            {"tenant_id": TENANT, "wait_id": WAIT_ID},
        ).scalar_one()
        parent = tuple(
            session.execute(
                text("SELECT state, phase FROM ae_agent_execution WHERE tenant_id=:tenant_id"),
                {"tenant_id": TENANT},
            ).one()
        )
    attempts = queue.list_attempts(TENANT, RESUME_JOB_ID)
    assert recovered.disposition == "ALREADY_TERMINAL"
    assert recovered.runtime_job["state"] == "DONE"
    assert step_result_count == 1
    assert wait_state == "CONSUMED"
    assert parent == ("RUNNING", "STEP_EXECUTION")
    assert [attempt["outcome"] for attempt in attempts] == ["LEASE_EXPIRED", "DONE"]
