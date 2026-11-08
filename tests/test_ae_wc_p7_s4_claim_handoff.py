from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import nex_wc.handoff_delivery as delivery_module
import nex_ae_api.agent_execution as execution_module
from nex_ae_api.agent_execution import (
    AgentExecutionAdmissionService,
    AgentExecutionError,
    AgentRuntimeAdmission,
    ExecutionTriggerV21,
    SqlAlchemyAgentExecutionRepository,
)
from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry
from nex_ae_api.claim_handoff_api import register_claim_handoff_routes
from nex_runtime import (
    InMemoryJobQueue,
    InMemoryWorkerHeartbeatStore,
    SERVICE_SPECS,
    WorkerHeartbeatEmitter,
    build_service_app,
    issue_mock_service_token,
)
from nex_wc.coordination import (
    CoordinationError,
    InMemoryCoordinationRepository,
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.handoff_delivery import (
    HandoffDeliveryError,
    HttpClaimHandoffClient,
    enqueue_pending_handoffs,
    run_handoff_delivery_job,
    run_handoff_delivery_worker_once,
)
from nex_wc.work_items import InMemoryWorkItemRepository, WorkItemService


NOW_DT = datetime(2026, 10, 18, 7, 0, tzinfo=UTC)
NOW = "2026-10-18T07:00:00Z"
TENANT = "tenant-s4"
PROJECT = "project-s4"
REQUESTER = "requester-s4"
AGENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa4"
EXECUTION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb4"
PROFILE = "agent-profile://pa/project-budget-read/v1"


def _ae_sessions():
    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ae_agent_identity (
                tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                schema_version TEXT NOT NULL, agent_type TEXT NOT NULL,
                profile_ref TEXT NOT NULL, status TEXT NOT NULL,
                project_id TEXT, created_at TEXT NOT NULL, version INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, agent_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_ia_principal_assignment (
                assignment_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                principal_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, version INTEGER NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_agent_execution (
                tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, agent_type TEXT NOT NULL,
                principal_id TEXT NOT NULL, trigger_schema_version TEXT NOT NULL,
                trigger_id TEXT NOT NULL, source_type TEXT NOT NULL,
                source_ref TEXT NOT NULL, project_id TEXT,
                workspace_id TEXT, conversation_id TEXT, legacy_interaction_id TEXT,
                state TEXT NOT NULL, phase TEXT NOT NULL, version INTEGER NOT NULL,
                result_id TEXT, correlation_id TEXT NOT NULL, causation_id TEXT,
                received_at TEXT NOT NULL, work_item_ref TEXT, claim_ref TEXT,
                claim_generation INTEGER, assignment_ref TEXT, requester_ref TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, agent_execution_id),
                UNIQUE (tenant_id, trigger_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_claim_handoff_inbox (
                tenant_id TEXT NOT NULL, event_id TEXT NOT NULL,
                handoff_id TEXT NOT NULL, handoff_semantic_hash TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, planning_source_json TEXT,
                received_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, event_id),
                UNIQUE (tenant_id, handoff_id)
            )
        """))
    return sessionmaker(bind=engine, expire_on_commit=False)


def _ae_admission():
    sessions = _ae_sessions()
    identities = SqlAlchemyAgentIdentityRegistry(
        sessions, id_factory=lambda: AGENT_ID, clock=lambda: NOW_DT
    )
    identities.register_agent(
        tenant_id=TENANT,
        agent_type="PA",
        profile_ref=PROFILE,
        project_id=PROJECT,
    )
    executions = SqlAlchemyAgentExecutionRepository(sessions)
    ids = iter((EXECUTION_ID, "cccccccc-cccc-4ccc-8ccc-ccccccccccc4"))
    service = AgentExecutionAdmissionService(
        identities=identities,
        executions=executions,
        mode="required",
        id_factory=lambda: next(ids),
        clock=lambda: NOW_DT,
    )
    return sessions, identities, executions, service


class _Agents:
    candidate = {
        "schema_version": "2.1",
        "tenant_id": TENANT,
        "agent_id": AGENT_ID,
        "agent_type": "PA",
        "profile_ref": PROFILE,
        "status": "ACTIVE",
        "project_id": PROJECT,
        "created_at": NOW,
        "version": 1,
    }

    def list_agents(self, **kwargs):
        return [dict(self.candidate)]

    def get_agent(self, **kwargs):
        return dict(self.candidate)


class _Authorization:
    def effective_authorization(self, **kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate", "work:claim"],
            "revision_hash": "d" * 64,
        }


def _work_payload():
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-s4",
            "tenant_id": TENANT,
            "parent_agent_execution_id": "parent-execution-s4",
            "parent_executable_plan_id": "parent-plan-s4",
            "parent_executable_step_id": "parent-step-s4",
            "delegation_revision": 1,
            "goal": "Check project budget",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": "urn:nex:result:budget:1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "trace-s4",
            "causation_id": "cause-s4",
        },
        "requester": {"entity_type": "USER", "entity_id": REQUESTER},
        "accountable_owner": {"entity_type": "USER", "entity_id": REQUESTER},
    }


def _claimed_work():
    work_repository = InMemoryWorkItemRepository()
    item = WorkItemService(
        work_repository,
        authorization_source=_Authorization(),
        id_factory=lambda: "11111111-1111-4111-8111-111111111114",
        clock=lambda: NOW_DT,
    ).create(_work_payload())["work_item"]
    ids = iter(
        (
            "22222222-2222-4222-8222-222222222224",
            "33333333-3333-4333-8333-333333333334",
            "44444444-4444-4444-8444-444444444444",
            "55555555-5555-4555-8555-555555555554",
            "66666666-6666-4666-8666-666666666664",
            "77777777-7777-4777-8777-777777777774",
        )
    )
    repository = InMemoryCoordinationRepository(work_repository)
    service = WorkCoordinationService(
        repository,
        candidate_source=_Agents(),
        authorization_source=_Authorization(),
        id_factory=lambda: next(ids),
        token_factory=lambda: "lease-s4",
        clock=lambda: NOW_DT,
    )
    service.route(tenant_id=TENANT, work_item_id=item["work_item_id"], expected_version=1)
    claimed = service.claim(
        tenant_id=TENANT, work_item_id=item["work_item_id"], expected_version=2
    )
    return repository, claimed


class _DirectAdmissionClient:
    def __init__(self, admission):
        self.admission = admission

    def deliver(self, envelope):
        admitted = self.admission.admit_claimed_work(
            event_id=envelope["event_id"],
            requester_ref=envelope["requester_ref"],
            handoff=envelope["handoff"],
            planning_source=envelope["planning_source"],
        )
        return {"agent_execution_id": admitted.execution["agent_execution_id"]}


def test_s4_outbox_bridge_worker_and_claimed_admission_are_idempotent():
    sessions, _, executions, admission = _ae_admission()
    store, claimed = _claimed_work()
    queue = InMemoryJobQueue()

    jobs = enqueue_pending_handoffs(
        store=store, queue=queue, clock=lambda: NOW_DT
    )
    assert len(jobs) == 1
    assert jobs[0]["payload"] == {
        "outbox_id": claimed["outbox_id"],
        "event_id": claimed["event_id"],
    }
    assert set(jobs[0]["payload"]) == {"outbox_id", "event_id"}
    assert enqueue_pending_handoffs(store=store, queue=queue) == []

    heartbeat = WorkerHeartbeatEmitter(
        service_id="nex-wc",
        worker_id="wc-handoff-delivery-worker-001",
        worker_type="wc.claim_handoff.delivery.worker",
        store=InMemoryWorkerHeartbeatStore(),
        started_at=NOW,
    )
    execution = run_handoff_delivery_worker_once(
        queue=queue,
        store=store,
        client=_DirectAdmissionClient(admission),
        heartbeat_emitter=heartbeat,
        clock=lambda: NOW,
    )
    assert execution.status == "SUCCEEDED"
    assert execution.handler_result["delivery_state"] == "DELIVERED"
    admitted = executions.get(TENANT, EXECUTION_ID)
    assert admitted["source_type"] == "CLAIMED_WORKITEM"
    assert admitted["work_item_ref"] == claimed["work_item"]["work_item_id"]
    assert admitted["claim_generation"] == 1
    assert admitted["requester_ref"] == REQUESTER
    assert executions.get_claimed_planning_source(
        TENANT, EXECUTION_ID
    ) == claimed["planning_source"]

    repeated = run_handoff_delivery_job(
        execution.job,
        store=store,
        client=_DirectAdmissionClient(admission),
        clock=lambda: NOW_DT,
    )
    assert repeated["agent_execution_id"] == EXECUTION_ID
    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM ae_agent_execution")).scalar_one() == 1
        assert session.execute(text("SELECT count(*) FROM ae_claim_handoff_inbox")).scalar_one() == 1

    with sessions.begin() as session:
        session.execute(
            text(
                "UPDATE ae_claim_handoff_inbox "
                "SET planning_source_json = NULL"
            )
        )
    assert executions.get_claimed_planning_source(TENANT, EXECUTION_ID) is None


def test_s4_claimed_admission_fails_closed_for_semantic_and_identity_drift():
    sessions, identities, _, admission = _ae_admission()
    _, claimed = _claimed_work()
    handoff = claimed["handoff"]
    first = admission.admit_claimed_work(
        event_id=claimed["event_id"],
        requester_ref=REQUESTER,
        handoff=handoff,
        planning_source=claimed["planning_source"],
    )
    assert first.execution["agent_execution_id"] == EXECUTION_ID

    with pytest.raises(AgentExecutionError) as semantic_conflict:
        admission.admit_claimed_work(
            event_id=claimed["event_id"],
            requester_ref=REQUESTER,
            handoff={**handoff, "claim_ref": "different-claim"},
            planning_source=claimed["planning_source"],
        )
    assert semantic_conflict.value.error_code == "ae.agent_execution_trigger_conflict"

    with sessions.begin() as session:
        session.execute(
            text("UPDATE ae_agent_identity SET status = 'SUSPENDED' WHERE agent_id = :agent"),
            {"agent": AGENT_ID},
        )
    assert identities.get_agent(tenant_id=TENANT, agent_id=AGENT_ID)["status"] == "SUSPENDED"
    with pytest.raises(AgentExecutionError) as identity_conflict:
        admission.admit_claimed_work(
            event_id="88888888-8888-4888-8888-888888888884",
            requester_ref=REQUESTER,
            handoff={**handoff, "handoff_id": "99999999-9999-4999-8999-999999999994"},
            planning_source=claimed["planning_source"],
        )
    assert identity_conflict.value.error_code == "ae.claimed_work_identity_forbidden"


@pytest.mark.parametrize(
    "mutation",
    (
        lambda source: source.update(unexpected=True),
        lambda source: source.update(schema_version="unsupported"),
        lambda source: source.update(project_ref={"entity_type": "TENANT", "entity_id": PROJECT}),
        lambda source: source.update(artifact_refs="not-an-array"),
        lambda source: source.update(artifact_refs=[{"entity_type": "ARTIFACT"}]),
        lambda source: source.update(
            artifact_refs=[
                {
                    "entity_type": "ARTIFACT",
                    "entity_id": "artifact-1",
                    "claim_ref": "must-not-cross-planning-boundary",
                }
            ]
        ),
        lambda source: source.update(source_ref="different-work-item"),
    ),
)
def test_s4_claimed_planning_source_validation_fails_closed(mutation):
    _, _, _, admission = _ae_admission()
    _, claimed = _claimed_work()
    source = copy.deepcopy(claimed["planning_source"])
    mutation(source)

    with pytest.raises(AgentExecutionError):
        admission.admit_claimed_work(
            event_id=claimed["event_id"],
            requester_ref=REQUESTER,
            handoff=claimed["handoff"],
            planning_source=source,
        )


def test_s4_claimed_planning_source_reload_failures_are_typed():
    sessions, _, repository, admission = _ae_admission()
    _, claimed = _claimed_work()
    admission.admit_claimed_work(
        event_id=claimed["event_id"],
        requester_ref=REQUESTER,
        handoff=claimed["handoff"],
        planning_source=claimed["planning_source"],
    )
    assert repository.get_claimed_planning_source(TENANT, "missing") is None
    with sessions.begin() as session:
        session.execute(
            text(
                "UPDATE ae_claim_handoff_inbox "
                "SET planning_source_json = '{invalid-json'"
            )
        )
    with pytest.raises(AgentExecutionError) as malformed:
        repository.get_claimed_planning_source(TENANT, EXECUTION_ID)
    assert malformed.value.retryable is True

    unavailable = SqlAlchemyAgentExecutionRepository(
        sessionmaker(bind=create_engine("sqlite+pysqlite://"), expire_on_commit=False)
    )
    with pytest.raises(AgentExecutionError) as store:
        unavailable.get_claimed_planning_source(TENANT, EXECUTION_ID)
    assert store.value.retryable is True

    enriched = copy.deepcopy(claimed["planning_source"])
    enriched["project_ref"].update(version=1, status="ACTIVE")
    assert execution_module._validate_claimed_planning_source(enriched)[
        "project_ref"
    ]["version"] == 1


def _claimed_trigger(**overrides):
    values = {
        "trigger_id": "55555555-5555-4555-8555-555555555554",
        "source_type": "CLAIMED_WORKITEM",
        "source_ref": "11111111-1111-4111-8111-111111111114",
        "tenant_id": TENANT,
        "agent_type": "PA",
        "agent_id": AGENT_ID,
        "project_id": PROJECT,
        "correlation_id": "trace-s4",
        "causation_id": "cause-s4",
        "received_at": NOW,
        "work_item_ref": "11111111-1111-4111-8111-111111111114",
        "claim_ref": "44444444-4444-4444-8444-444444444444",
        "claim_generation": 1,
        "assignment_ref": "33333333-3333-4333-8333-333333333334",
        "requester_ref": REQUESTER,
    }
    return ExecutionTriggerV21(**{**values, **overrides})


def test_s4_repository_and_receipt_failures_are_typed(monkeypatch):
    sessions, _, repository, admission = _ae_admission()
    original_load_by_trigger = execution_module._load_by_trigger
    prompt_trigger = ExecutionTriggerV21(
        trigger_id="prompt-trigger",
        source_type="PROMPT",
        source_ref="prompt-source",
        tenant_id=TENANT,
        agent_type="IA",
        agent_id="ia-agent",
        project_id=None,
        correlation_id="trace",
        received_at=NOW,
    )
    with pytest.raises(AgentExecutionError):
        repository.admit_claimed_work(
            event_id="event",
            handoff_semantic_hash="sha256:" + "a" * 64,
            planning_source={},
            trigger=prompt_trigger,
            principal_id=REQUESTER,
            agent_execution_id=EXECUTION_ID,
            now=NOW,
        )

    _, claimed = _claimed_work()
    monkeypatch.setattr(execution_module, "_load_by_trigger", lambda *args: None)
    with pytest.raises(AgentExecutionError) as missing_execution:
        admission.admit_claimed_work(
            event_id=claimed["event_id"],
            requester_ref=REQUESTER,
            handoff=claimed["handoff"],
            planning_source=claimed["planning_source"],
        )
    assert missing_execution.value.error_code == "ae.agent_execution_write_conflict"

    sessions, _, repository, admission = _ae_admission()
    monkeypatch.setattr(
        execution_module,
        "_load_by_trigger",
        original_load_by_trigger,
    )
    monkeypatch.setattr(execution_module, "_load_claim_handoff_receipt", lambda *args, **kwargs: None)
    with pytest.raises(AgentExecutionError) as missing_receipt:
        admission.admit_claimed_work(
            event_id=claimed["event_id"],
            requester_ref=REQUESTER,
            handoff=claimed["handoff"],
            planning_source=claimed["planning_source"],
        )
    assert missing_receipt.value.error_code == "ae.claim_handoff_write_conflict"

    unavailable = SqlAlchemyAgentExecutionRepository(
        sessionmaker(bind=create_engine("sqlite+pysqlite://"), expire_on_commit=False)
    )
    with pytest.raises(AgentExecutionError) as unavailable_error:
        unavailable.admit_claimed_work(
            event_id="event",
            handoff_semantic_hash="sha256:" + "a" * 64,
            planning_source=claimed["planning_source"],
            trigger=_claimed_trigger(),
            principal_id=REQUESTER,
            agent_execution_id=EXECUTION_ID,
            now=NOW,
        )
    assert unavailable_error.value.retryable is True


@pytest.mark.parametrize(
    "handoff",
    (
        None,
        {"schema_version": "2.1", "unexpected": True},
        {"schema_version": "1.0"},
        {
            "schema_version": "2.1",
            "handoff_id": "handoff",
            "tenant_id": TENANT,
            "work_item_ref": "work",
            "claim_ref": "claim",
            "claim_generation": 1,
            "claimant_agent_ref": AGENT_ID,
            "claimant_agent_type": "IA",
            "project_id": PROJECT,
            "assignment_ref": "assignment",
            "correlation_id": "trace",
            "occurred_at": NOW,
        },
        {
            "schema_version": "2.1",
            "handoff_id": "handoff",
            "tenant_id": TENANT,
            "work_item_ref": "work",
            "claim_ref": "claim",
            "claim_generation": 0,
            "claimant_agent_ref": AGENT_ID,
            "claimant_agent_type": "PA",
            "project_id": PROJECT,
            "assignment_ref": "assignment",
            "correlation_id": "trace",
            "occurred_at": NOW,
        },
    ),
)
def test_s4_handoff_contract_validation_fails_closed(handoff):
    _, _, _, admission = _ae_admission()
    _, claimed = _claimed_work()
    with pytest.raises(AgentExecutionError):
        admission.admit_claimed_work(
            event_id="event",
            requester_ref=REQUESTER,
            handoff=handoff,
            planning_source=claimed["planning_source"],
        )


def test_s4_background_admission_requires_required_mode():
    sessions, identities, repository, _ = _ae_admission()
    disabled = AgentExecutionAdmissionService(
        identities=identities,
        executions=repository,
        mode="disabled",
    )
    _, claimed = _claimed_work()
    with pytest.raises(AgentExecutionError) as error:
        disabled.admit_claimed_work(
            event_id=claimed["event_id"],
            requester_ref=REQUESTER,
            handoff=claimed["handoff"],
            planning_source=claimed["planning_source"],
        )
    assert error.value.error_code == "ae.background_agent_runtime_disabled"


class _ApiAdmission:
    def admit_claimed_work(self, **kwargs):
        return AgentRuntimeAdmission(
            mode="required", execution={"agent_execution_id": EXECUTION_ID}
        )


class _FailingApiAdmission:
    def admit_claimed_work(self, **kwargs):
        raise AgentExecutionError("ae.claim.failed", "failed", True)


def test_s4_ae_handoff_api_requires_wc_service_authority():
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_claim_handoff_routes(app, admission=_ApiAdmission())
    client = TestClient(app)
    payload = {
        "event_id": "event-s4",
        "event_type": "CLAIM_EXECUTION_HANDOFF",
        "requester_ref": REQUESTER,
        "handoff": {"handoff_id": "handoff-s4"},
    }
    assert client.post("/internal/v1/work-handoffs", json=payload).status_code == 401
    ag_token = issue_mock_service_token(service_id="nex-ag", audience="nex-ae-api")
    assert client.post(
        "/internal/v1/work-handoffs",
        json=payload,
        headers={"Authorization": f"Bearer {ag_token.access_token}"},
    ).status_code == 403
    wc_token = issue_mock_service_token(service_id="nex-wc", audience="nex-ae-api")
    response = client.post(
        "/internal/v1/work-handoffs",
        json=payload,
        headers={"Authorization": f"Bearer {wc_token.access_token}"},
    )
    assert response.status_code == 200
    assert response.json()["execution"]["agent_execution_id"] == EXECUTION_ID
    invalid_event = client.post(
        "/internal/v1/work-handoffs",
        json={**payload, "event_type": "OTHER"},
        headers={"Authorization": f"Bearer {wc_token.access_token}"},
    )
    assert invalid_event.status_code == 409

    failing_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_claim_handoff_routes(failing_app, admission=_FailingApiAdmission())
    assert TestClient(failing_app).post(
        "/internal/v1/work-handoffs",
        json=payload,
        headers={"Authorization": f"Bearer {wc_token.access_token}"},
    ).status_code == 503

    unavailable_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_claim_handoff_routes(unavailable_app, admission=None)
    assert TestClient(unavailable_app).post(
        "/internal/v1/work-handoffs",
        json=payload,
        headers={"Authorization": f"Bearer {wc_token.access_token}"},
    ).status_code == 503


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({"execution": {"agent_execution_id": EXECUTION_ID}}).encode()


def test_s4_http_delivery_client_and_failure_guards(monkeypatch):
    monkeypatch.setattr(delivery_module, "urlopen", lambda *args, **kwargs: _Response())
    client = HttpClaimHandoffClient(base_url="http://ae/", service_token="token")
    assert client.deliver({"event_id": "event"})["agent_execution_id"] == EXECUTION_ID
    with pytest.raises(HandoffDeliveryError):
        HttpClaimHandoffClient(base_url="http://ae", service_token="").deliver({})

    store, claimed = _claimed_work()
    queue = InMemoryJobQueue()
    job = enqueue_pending_handoffs(store=store, queue=queue, clock=lambda: NOW_DT)[0]
    with pytest.raises(HandoffDeliveryError):
        run_handoff_delivery_job(
            {**job, "payload": {"outbox_id": claimed["outbox_id"]}},
            store=store,
            client=client,
        )
    with pytest.raises(HandoffDeliveryError):
        enqueue_pending_handoffs(store=store, queue=queue, limit=0)
    assert str(HandoffDeliveryError("code", "detail")) == "detail"


def test_s4_delivery_job_and_outbox_state_fail_closed():
    store, claimed = _claimed_work()
    with pytest.raises(CoordinationError):
        store.mark_handoff_enqueued(
            outbox_id="missing",
            event_id="missing",
            job_id="job",
            updated_at=NOW,
        )
    with pytest.raises(CoordinationError):
        store.load_handoff_event(outbox_id="missing", event_id="missing")
    with pytest.raises(CoordinationError):
        store.mark_handoff_delivered(
            outbox_id=claimed["outbox_id"],
            event_id=claimed["event_id"],
            job_id="job",
            updated_at=NOW,
        )

    queue = InMemoryJobQueue()
    job = enqueue_pending_handoffs(store=store, queue=queue, clock=lambda: NOW_DT)[0]
    with pytest.raises(CoordinationError):
        store.mark_handoff_enqueued(
            outbox_id=claimed["outbox_id"],
            event_id=claimed["event_id"],
            job_id="different-job",
            updated_at=NOW,
        )
    with pytest.raises(CoordinationError):
        store.mark_handoff_delivered(
            outbox_id=claimed["outbox_id"],
            event_id=claimed["event_id"],
            job_id="different-job",
            updated_at=NOW,
        )

    class _Client:
        def deliver(self, envelope):
            return {"agent_execution_id": EXECUTION_ID}

    for changed in (
        {**job, "job_type": "OTHER"},
        {**job, "subject_ref": {"type": "OTHER", "id": claimed["outbox_id"]}},
        {**job, "idempotency_key": "different-event"},
    ):
        with pytest.raises(HandoffDeliveryError):
            run_handoff_delivery_job(changed, store=store, client=_Client())

    class _MissingPlanningSourceStore:
        def __getattr__(self, name):
            return getattr(store, name)

        def load_handoff_event(self, **kwargs):
            event = store.load_handoff_event(**kwargs)
            event.pop("planning_source")
            return event

    with pytest.raises(HandoffDeliveryError) as missing_source:
        run_handoff_delivery_job(
            job,
            store=_MissingPlanningSourceStore(),
            client=_Client(),
        )
    assert missing_source.value.error_code == "wc.handoff_planning_source_invalid"

    key = (TENANT, claimed["outbox_id"])
    store._outbox[key]["event_type"] = "OTHER"
    with pytest.raises(HandoffDeliveryError):
        run_handoff_delivery_job(job, store=store, client=_Client())


def test_s4_bridge_rejects_invalid_pending_outbox():
    store, claimed = _claimed_work()
    store._outbox[(TENANT, claimed["outbox_id"])]["event_payload"] = None
    with pytest.raises(HandoffDeliveryError):
        enqueue_pending_handoffs(store=store, queue=InMemoryJobQueue())


def test_s4_http_delivery_failures_and_store_failures(monkeypatch):
    client = HttpClaimHandoffClient(base_url="http://ae", service_token="token")
    monkeypatch.setattr(
        delivery_module,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HTTPError("http://ae", 409, "conflict", {}, None)
        ),
    )
    with pytest.raises(HandoffDeliveryError) as http_error:
        client.deliver({"event_id": "event"})
    assert http_error.value.retryable is False

    monkeypatch.setattr(
        delivery_module,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("down")),
    )
    with pytest.raises(HandoffDeliveryError) as unavailable:
        client.deliver({"event_id": "event"})
    assert unavailable.value.retryable is True

    monkeypatch.setattr(delivery_module, "urlopen", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(_Response, "read", lambda self: b"{}")
    with pytest.raises(HandoffDeliveryError):
        client.deliver({"event_id": "event"})

    repository = SqlAlchemyCoordinationRepository(
        sessionmaker(bind=create_engine("sqlite+pysqlite://"), expire_on_commit=False)
    )
    for operation in (
        lambda: repository.list_pending_handoffs(limit=1),
        lambda: repository.load_handoff_event(outbox_id="outbox", event_id="event"),
        lambda: repository.mark_handoff_enqueued(
            outbox_id="outbox", event_id="event", job_id="job", updated_at=NOW
        ),
        lambda: repository.mark_handoff_delivered(
            outbox_id="outbox", event_id="event", job_id="job", updated_at=NOW
        ),
    ):
        with pytest.raises(CoordinationError):
            operation()
