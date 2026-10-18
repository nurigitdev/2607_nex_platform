from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import ClassVar
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.work_result_event_api import register_work_result_event_routes
from nex_ae_api.work_result_events import (
    SqlAlchemyWorkResultEventService,
    WorkResultEventError,
    deterministic_resume_job_id,
    validate_work_result_event,
)
from nex_ae_api.work_result_publication import (
    HttpWcWorkResultClient,
    WorkResultPublicationError,
)
from nex_runtime import (
    SERVICE_SPECS,
    InMemoryJobQueue,
    build_service_app,
    issue_mock_service_token,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc.coordination import (
    InMemoryCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.work_items import InMemoryWorkItemRepository, WorkItemService
from nex_wc.work_result_api import register_work_result_routes
from nex_wc.work_result_delivery import (
    HttpWorkResultEventClient,
    WorkResultDeliveryError,
    enqueue_pending_result_events,
    run_work_result_delivery_job,
)
from nex_wc.work_results import (
    InMemoryWorkResultRepository,
    WorkResultError,
    WorkResultService,
    validate_work_result,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW_DT = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
NOW = "2026-10-18T12:00:00Z"
TENANT = "tenant-p7-s6"
PROJECT = "project-p7-s6"
REQUESTER = "requester-p7-s6"
AGENT_ID = "11111111-1111-4111-8111-111111111116"
PARENT_ID = "22222222-2222-4222-8222-222222222226"
CHILD_ID = "33333333-3333-4333-8333-333333333336"
STEP_ID = "44444444-4444-4444-8444-444444444446"
WAIT_ID = "55555555-5555-4555-8555-555555555556"
WORK_ITEM_ID = "66666666-6666-4666-8666-666666666666"
CLAIM_ID = "77777777-7777-4777-8777-777777777776"
ASSIGNMENT_ID = "88888888-8888-4888-8888-888888888886"
RESULT_ID = "result-p7-s6"
EVENT_ID = "99999999-9999-4999-8999-999999999996"
CONTRACT = "urn:nex:result:project-margin:1"
CORRELATION = "trace-p7-s6"


class _Agents:
    candidate: ClassVar[dict[str, object]] = {
        "schema_version": "2.1",
        "tenant_id": TENANT,
        "agent_id": AGENT_ID,
        "agent_type": "PA",
        "profile_ref": "agent-profile://pa/project-budget-read/v1",
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
            "scopes": ["work:claim", "work:result:submit"],
            "revision_hash": "a" * 64,
        }


def _work_payload():
    return {
        "work_item_id": WORK_ITEM_ID,
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-p7-s6",
            "tenant_id": TENANT,
            "parent_agent_execution_id": PARENT_ID,
            "parent_executable_plan_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6",
            "parent_executable_step_id": STEP_ID,
            "delegation_revision": 1,
            "goal": "Prepare project margin evidence.",
            "work_class": "ANALYSIS",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": CONTRACT,
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": CORRELATION,
            "causation_id": STEP_ID,
        },
        "requester": {"entity_type": "USER", "entity_id": REQUESTER},
        "accountable_owner": {"entity_type": "USER", "entity_id": REQUESTER},
    }


def _wc_runtime():
    work_repository = InMemoryWorkItemRepository()
    item = WorkItemService(work_repository, clock=lambda: NOW_DT).create(
        _work_payload()
    )["work_item"]
    ids = iter(
        (
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb6",
            ASSIGNMENT_ID,
            CLAIM_ID,
            "cccccccc-cccc-4ccc-8ccc-ccccccccccc6",
            "dddddddd-dddd-4ddd-8ddd-ddddddddddd6",
            "ffffffff-ffff-4fff-8fff-fffffffffff6",
        )
    )
    coordination = InMemoryCoordinationRepository(work_repository)
    service = WorkCoordinationService(
        coordination,
        candidate_source=_Agents(),
        authorization_source=_Authorization(),
        id_factory=lambda: next(ids),
        token_factory=lambda: "lease-p7-s6",
        clock=lambda: NOW_DT,
    )
    service.route(
        tenant_id=TENANT,
        work_item_id=item["work_item_id"],
        expected_version=1,
    )
    claimed = service.claim(
        tenant_id=TENANT,
        work_item_id=item["work_item_id"],
        expected_version=2,
    )
    repository = InMemoryWorkResultRepository(coordination)
    result_ids = iter(
        (
            "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee6",
            EVENT_ID,
            "12121212-1212-4212-8212-121212121216",
            "13131313-1313-4313-8313-131313131316",
            "14141414-1414-4414-8414-141414141416",
            "15151515-1515-4515-8515-151515151516",
        )
    )
    results = WorkResultService(
        repository,
        authorization_source=_Authorization(),
        id_factory=lambda: next(result_ids),
        clock=lambda: NOW_DT,
    )
    return coordination, repository, results, claimed


def _work_result(claimed):
    return {
        "schema_version": "2.1",
        "tenant_id": TENANT,
        "result_id": RESULT_ID,
        "work_item_id": WORK_ITEM_ID,
        "revision_no": 1,
        "result_type": "PROJECT_MARGIN_ANALYSIS",
        "summary": "Project margin evidence is ready.",
        "payload": {"result_ref": "agent-result://p7-s6"},
        "schema_ref": CONTRACT,
        "technical_outcome": "SUCCEEDED",
        "business_outcome": "VERIFIED",
        "artifact_refs": [],
        "evidence_refs": [],
        "business_object_refs": [],
        "source_execution_ref": CHILD_ID,
        "source_plan_ref": "plan-p7-s6",
        "claim_ref": claimed["claim"]["claim_id"],
        "claim_generation": claimed["claim"]["claim_generation"],
        "assignment_ref": claimed["assignment"]["assignment_id"],
        "submitted_by": {"entity_type": "AGENT", "entity_id": AGENT_ID},
        "trace": {"correlation_id": CORRELATION, "causation_id": CHILD_ID},
        "submitted_at": NOW,
    }


def _accepted_result():
    _, repository, service, claimed = _wc_runtime()
    result = _work_result(claimed)
    accepted = service.submit(
        tenant_id=TENANT,
        work_item_id=WORK_ITEM_ID,
        expected_version=claimed["work_item"]["version"],
        work_result=result,
    )
    event = repository.list_pending_result_events(limit=1)[0]["event_payload"]
    return repository, service, claimed, result, accepted, event


def test_s6_wc_work_result_atomic_commit_idempotency_and_authority_guards():
    repository, service, claimed, result, accepted, event = _accepted_result()
    assert accepted["created"] is True
    assert accepted["result_hash"] == semantic_sha256_hash_ref(result)
    assert event["event_name"] == "WORK_RESULT_SUBMITTED"
    assert event["resume_match_ref"] == WORK_ITEM_ID
    assert (
        repository.get_submission_context(tenant_id=TENANT, work_item_id=WORK_ITEM_ID)[
            "work_item"
        ]["state"]
        == "RESULT_SUBMITTED"
    )

    duplicate = service.submit(
        tenant_id=TENANT,
        work_item_id=WORK_ITEM_ID,
        expected_version=claimed["work_item"]["version"],
        work_result=result,
    )
    assert duplicate == {**accepted, "created": False}

    drifted = copy.deepcopy(result)
    drifted["summary"] = "Different semantics"
    with pytest.raises(WorkResultError, match="different semantics"):
        service.submit(
            tenant_id=TENANT,
            work_item_id=WORK_ITEM_ID,
            expected_version=claimed["work_item"]["version"],
            work_result=drifted,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(schema_ref="urn:nex:wrong"),
        lambda value: value.update(claim_generation=2),
        lambda value: value["submitted_by"].update(
            entity_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6"
        ),
    ],
)
def test_s6_wc_rejects_contract_and_current_authority_drift(mutation):
    _, _, service, claimed = _wc_runtime()
    result = _work_result(claimed)
    mutation(result)
    with pytest.raises(WorkResultError):
        service.submit(
            tenant_id=TENANT,
            work_item_id=WORK_ITEM_ID,
            expected_version=claimed["work_item"]["version"],
            work_result=result,
        )


def test_s6_work_result_contract_validation_rejects_private_shape_drift():
    _, _, _, claimed = _wc_runtime()
    result = _work_result(claimed)
    assert validate_work_result(result)["claim_ref"] == CLAIM_ID
    for mutation in (
        lambda value: value.update(extra=True),
        lambda value: value.update(schema_version="1.0"),
        lambda value: value.update(revision_no=0),
        lambda value: value.update(technical_outcome="MAYBE"),
        lambda value: value.update(
            submitted_by={"entity_type": "USER", "entity_id": "u"}
        ),
    ):
        candidate = copy.deepcopy(result)
        mutation(candidate)
        with pytest.raises(WorkResultError):
            validate_work_result(candidate)


def _ae_sessions(*, parent_state: str = "WAITING_DEPENDENCY", with_wait: bool = True):
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text("""
            CREATE TABLE ae_agent_execution (
                tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, source_type TEXT NOT NULL,
                work_item_ref TEXT, claim_ref TEXT, claim_generation INTEGER,
                assignment_ref TEXT, state TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                PRIMARY KEY (tenant_id, agent_execution_id)
            )
        """)
        )
        connection.execute(
            text("""
            CREATE TABLE ae_executable_step (
                tenant_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, state TEXT NOT NULL,
                executor_kind TEXT NOT NULL,
                PRIMARY KEY (tenant_id, executable_step_id)
            )
        """)
        )
        connection.execute(
            text("""
            CREATE TABLE ae_wait_registration (
                wait_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                wait_type TEXT NOT NULL, external_ref TEXT NOT NULL,
                result_contract_ref TEXT NOT NULL, state TEXT NOT NULL,
                matched_event_id TEXT, resume_runtime_job_id TEXT,
                version INTEGER NOT NULL, created_at TEXT NOT NULL,
                satisfied_at TEXT, updated_at TEXT,
                PRIMARY KEY (tenant_id, wait_id)
            )
        """)
        )
        connection.execute(
            text("""
            CREATE TABLE ae_external_event_inbox (
                tenant_id TEXT NOT NULL, event_id TEXT NOT NULL,
                event_type TEXT NOT NULL, event_semantic_hash TEXT NOT NULL,
                external_ref TEXT NOT NULL, result_id TEXT NOT NULL,
                result_contract_ref TEXT, event_payload TEXT NOT NULL,
                state TEXT NOT NULL, rejection_reason TEXT,
                received_at TEXT NOT NULL, processed_at TEXT,
                PRIMARY KEY (tenant_id, event_id)
            )
        """)
        )
        connection.execute(
            text("""
            CREATE TABLE ae_runtime_job (
                tenant_id TEXT NOT NULL, runtime_job_id TEXT NOT NULL,
                job_type TEXT NOT NULL, execution_id TEXT NOT NULL,
                executable_step_id TEXT, wait_id TEXT, reconciliation_id TEXT,
                result_delivery_id TEXT, publication_reconciliation_id TEXT,
                state TEXT NOT NULL, dedup_key TEXT NOT NULL,
                attempt_no INTEGER NOT NULL, run_after TEXT NOT NULL,
                lease_owner TEXT, lease_token TEXT, lease_until TEXT,
                payload_json TEXT NOT NULL, correlation_id TEXT NOT NULL,
                causation_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, runtime_job_id),
                UNIQUE (tenant_id, dedup_key)
            )
        """)
        )
        connection.execute(
            text("""
                INSERT INTO ae_agent_execution (
                    tenant_id, agent_execution_id, agent_id, source_type, state,
                    correlation_id
                ) VALUES (:tenant, :parent, :agent, 'PROMPT', :state, :correlation)
            """),
            {
                "tenant": TENANT,
                "parent": PARENT_ID,
                "agent": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa7",
                "state": parent_state,
                "correlation": CORRELATION,
            },
        )
        connection.execute(
            text("""
                INSERT INTO ae_agent_execution (
                    tenant_id, agent_execution_id, agent_id, source_type,
                    work_item_ref, claim_ref, claim_generation, assignment_ref,
                    state, correlation_id
                ) VALUES (
                    :tenant, :child, :agent, 'CLAIMED_WORKITEM', :work_item,
                    :claim, 1, :assignment, 'RUNNING', :correlation
                )
            """),
            {
                "tenant": TENANT,
                "child": CHILD_ID,
                "agent": AGENT_ID,
                "work_item": WORK_ITEM_ID,
                "claim": CLAIM_ID,
                "assignment": ASSIGNMENT_ID,
                "correlation": CORRELATION,
            },
        )
        connection.execute(
            text("""
                INSERT INTO ae_executable_step VALUES (
                    :tenant, :step, :parent, 'WAITING', 'WC_DELEGATE_WORK'
                )
            """),
            {"tenant": TENANT, "step": STEP_ID, "parent": PARENT_ID},
        )
        if with_wait:
            _insert_wait(connection)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _insert_wait(connection):
    connection.execute(
        text("""
            INSERT INTO ae_wait_registration (
                wait_id, tenant_id, agent_execution_id, executable_step_id,
                wait_type, external_ref, result_contract_ref, state, version,
                created_at, updated_at
            ) VALUES (
                :wait, :tenant, :parent, :step, 'WORK_RESULT', :work_item,
                :contract, 'PENDING', 1, :now, :now
            )
        """),
        {
            "wait": WAIT_ID,
            "tenant": TENANT,
            "parent": PARENT_ID,
            "step": STEP_ID,
            "work_item": WORK_ITEM_ID,
            "contract": CONTRACT,
            "now": NOW,
        },
    )


def _event():
    return {
        "schema_version": "2.1",
        "event_id": EVENT_ID,
        "event_name": "WORK_RESULT_SUBMITTED",
        "tenant_id": TENANT,
        "work_item_id": WORK_ITEM_ID,
        "result_id": RESULT_ID,
        "revision_no": 1,
        "result_type": "PROJECT_MARGIN_ANALYSIS",
        "result_schema_ref": CONTRACT,
        "technical_outcome": "SUCCEEDED",
        "business_outcome": "VERIFIED",
        "source_execution_ref": CHILD_ID,
        "claim_ref": CLAIM_ID,
        "claim_generation": 1,
        "assignment_ref": ASSIGNMENT_ID,
        "submitted_by": {"entity_type": "AGENT", "entity_id": AGENT_ID},
        "resume_match_ref": WORK_ITEM_ID,
        "correlation_id": CORRELATION,
        "causation_id": RESULT_ID,
        "occurred_at": NOW,
    }


def _event_service(sessions):
    queue = SqlAlchemyRuntimeJobQueue(sessions)
    return SqlAlchemyWorkResultEventService(
        sessions, runtime_jobs=queue, clock=lambda: NOW_DT
    )


def test_s6_wait_first_event_ingest_is_atomic_and_exactly_once():
    sessions = _ae_sessions()
    service = _event_service(sessions)
    first = service.ingest(_event())
    assert first["inbox_state"] == "MATCHED"
    assert first["wait_state"] == "RESUME_QUEUED"
    assert first["resume_runtime_job_id"] == deterministic_resume_job_id(
        tenant_id=TENANT, wait_id=WAIT_ID, event_id=EVENT_ID
    )
    duplicate = service.ingest(_event())
    assert duplicate == {**first, "created": False}
    with sessions() as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM ae_external_event_inbox")
            ).scalar_one()
            == 1
        )
        assert (
            session.execute(text("SELECT count(*) FROM ae_runtime_job")).scalar_one()
            == 1
        )
        row = (
            session.execute(
                text("SELECT job_type, wait_id, payload_json FROM ae_runtime_job")
            )
            .mappings()
            .one()
        )
        assert row["job_type"] == "RESUME_EXECUTION"
        assert row["wait_id"] == WAIT_ID
        assert "Project margin" not in row["payload_json"]


def test_s6_event_before_wait_converges_through_reconciliation():
    sessions = _ae_sessions(with_wait=False)
    service = _event_service(sessions)
    received = service.ingest(_event())
    assert received["inbox_state"] == "RECEIVED"
    assert received["resume_runtime_job_id"] is None
    with sessions.begin() as session:
        _insert_wait(session)
    reconciled = service.reconcile_pending()
    assert reconciled[0]["inbox_state"] == "MATCHED"
    assert service.reconcile_pending() == []


@pytest.mark.parametrize(
    ("parent_state", "event_change", "reason", "wait_state"),
    [
        ("CANCELLED", None, "PARENT_CANCELLED", "CANCELLED"),
        (
            "WAITING_DEPENDENCY",
            {"result_schema_ref": "urn:nex:wrong"},
            "RESULT_CONTRACT_MISMATCH",
            "PENDING",
        ),
        (
            "WAITING_DEPENDENCY",
            {"claim_generation": 2},
            "CURRENT_AUTHORITY_MISMATCH",
            "PENDING",
        ),
    ],
)
def test_s6_parent_terminal_contract_and_authority_fail_closed(
    parent_state, event_change, reason, wait_state
):
    sessions = _ae_sessions(parent_state=parent_state)
    service = _event_service(sessions)
    event = _event()
    if event_change:
        event.update(event_change)
    result = service.ingest(event)
    assert result["inbox_state"] == "REJECTED"
    assert result["rejection_reason"] == reason
    assert result["wait_state"] == wait_state
    with sessions() as session:
        assert (
            session.execute(text("SELECT count(*) FROM ae_runtime_job")).scalar_one()
            == 0
        )


def test_s6_event_contract_and_idempotency_drift_are_rejected():
    assert validate_work_result_event(_event())["event_id"] == EVENT_ID
    for change in (
        {"resume_match_ref": CLAIM_ID},
        {"event_name": "OTHER"},
        {"occurred_at": "not-time"},
        {"extra": True},
    ):
        event = {**_event(), **change}
        with pytest.raises(WorkResultEventError):
            validate_work_result_event(event)

    sessions = _ae_sessions(with_wait=False)
    service = _event_service(sessions)
    service.ingest(_event())
    changed = _event()
    changed["business_outcome"] = "REVISED"
    with pytest.raises(WorkResultEventError, match="different semantics"):
        service.ingest(changed)


class _DirectEventClient:
    def __init__(self, service):
        self.service = service

    def deliver(self, event):
        return self.service.ingest(event)


def test_s6_wc_outbox_uses_common_ref_only_job_and_delivers_to_ae():
    repository, _, _, _, _, _ = _accepted_result()
    ae = _event_service(_ae_sessions())
    queue = InMemoryJobQueue()
    jobs = enqueue_pending_result_events(
        store=repository, queue=queue, clock=lambda: NOW_DT
    )
    assert len(jobs) == 1
    assert set(jobs[0]["payload"]) == {"outbox_id", "event_id"}
    assert enqueue_pending_result_events(store=repository, queue=queue) == []
    delivered = run_work_result_delivery_job(
        jobs[0],
        store=repository,
        client=_DirectEventClient(ae),
        clock=lambda: NOW_DT,
    )
    assert delivered["delivery_state"] == "DELIVERED"
    assert delivered["wait_state"] == "RESUME_QUEUED"


def test_s6_service_routes_are_service_authenticated():
    _, _, service, claimed = _wc_runtime()
    wc_app = build_service_app(SERVICE_SPECS["nex-wc"])
    register_work_result_routes(wc_app, service=service)
    payload = {
        "expected_version": claimed["work_item"]["version"],
        "work_result": _work_result(claimed),
    }
    assert (
        TestClient(wc_app)
        .post(
            f"/api/v1/work-items/{WORK_ITEM_ID}/results",
            json=payload,
            headers={"X-NeX-Tenant-Id": TENANT},
        )
        .status_code
        == 401
    )
    token = issue_mock_service_token(
        service_id="nex-ae-api", audience="nex-wc"
    ).access_token
    assert (
        TestClient(wc_app)
        .post(
            f"/api/v1/work-items/{WORK_ITEM_ID}/results",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "X-NeX-Tenant-Id": TENANT},
        )
        .status_code
        == 201
    )
    wrong_wc_caller = issue_mock_service_token(
        service_id="nex-cx", audience="nex-wc"
    ).access_token
    assert (
        TestClient(wc_app)
        .post(
            f"/api/v1/work-items/{WORK_ITEM_ID}/results",
            json=payload,
            headers={
                "Authorization": f"Bearer {wrong_wc_caller}",
                "X-NeX-Tenant-Id": TENANT,
            },
        )
        .status_code
        == 403
    )
    invalid = copy.deepcopy(payload)
    invalid["expected_version"] = 0
    assert (
        TestClient(wc_app)
        .post(
            f"/api/v1/work-items/{WORK_ITEM_ID}/results",
            json=invalid,
            headers={"Authorization": f"Bearer {token}", "X-NeX-Tenant-Id": TENANT},
        )
        .status_code
        == 400
    )

    ae_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_work_result_event_routes(ae_app, admission=_event_service(_ae_sessions()))
    wrong = issue_mock_service_token(
        service_id="nex-cx", audience="nex-ae-api"
    ).access_token
    assert (
        TestClient(ae_app)
        .post(
            "/internal/v1/work-result-events",
            json=_event(),
            headers={"Authorization": f"Bearer {wrong}"},
        )
        .status_code
        == 403
    )
    wc_token = issue_mock_service_token(
        service_id="nex-wc", audience="nex-ae-api"
    ).access_token
    assert (
        TestClient(ae_app)
        .post(
            "/internal/v1/work-result-events",
            json=_event(),
            headers={"Authorization": f"Bearer {wc_token}"},
        )
        .status_code
        == 201
    )


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        import json

        return json.dumps(self.payload).encode()


def test_s6_http_clients_require_exact_ack_and_classify_transport(monkeypatch):
    _, _, _, claimed = _wc_runtime()
    result = _work_result(claimed)
    expected_hash = semantic_sha256_hash_ref(result)
    client = HttpWcWorkResultClient(base_url="http://wc", service_token="token")
    monkeypatch.setattr(
        "nex_ae_api.work_result_publication.urlopen",
        lambda *args, **kwargs: _Response(
            {
                "work_item_id": WORK_ITEM_ID,
                "result_id": RESULT_ID,
                "result_hash": expected_hash,
            }
        ),
    )
    assert (
        client.submit(expected_version=3, work_result=result)["result_hash"]
        == expected_hash
    )
    monkeypatch.setattr(
        "nex_ae_api.work_result_publication.urlopen",
        lambda *args, **kwargs: _Response(
            {
                "work_item_id": WORK_ITEM_ID,
                "result_id": "other",
                "result_hash": expected_hash,
            }
        ),
    )
    with pytest.raises(WorkResultPublicationError, match="exact WorkResult"):
        client.submit(expected_version=3, work_result=result)

    event_client = HttpWorkResultEventClient(
        base_url="http://ae", service_token="token"
    )
    monkeypatch.setattr(
        "nex_wc.work_result_delivery.urlopen",
        lambda *args, **kwargs: _Response(
            {"event_id": EVENT_ID, "inbox_state": "MATCHED"}
        ),
    )
    assert event_client.deliver(_event())["inbox_state"] == "MATCHED"
    monkeypatch.setattr(
        "nex_wc.work_result_delivery.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")),
    )
    with pytest.raises(WorkResultDeliveryError, match="unavailable"):
        event_client.deliver(_event())


def test_s6_invalid_bridge_and_missing_tokens_fail_closed():
    repository, _, _, _, _, _ = _accepted_result()
    with pytest.raises(WorkResultDeliveryError):
        enqueue_pending_result_events(
            store=repository, queue=InMemoryJobQueue(), limit=0
        )
    with pytest.raises(WorkResultPublicationError):
        HttpWcWorkResultClient(base_url="http://wc", service_token="").submit(
            expected_version=1,
            work_result={"work_item_id": WORK_ITEM_ID, "result_id": RESULT_ID},
        )
    with pytest.raises(WorkResultDeliveryError):
        HttpWorkResultEventClient(base_url="http://ae", service_token="").deliver(
            _event()
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("result_id"),
        lambda value: value.update(business_outcome="MAYBE"),
        lambda value: value.update(summary=42),
        lambda value: value.update(artifact_refs="not-an-array"),
        lambda value: value.update(artifact_refs=["not-an-entity-ref"]),
        lambda value: value.update(
            artifact_refs=[{"entity_type": "ARTIFACT", "entity_id": "a", "x": 1}]
        ),
        lambda value: value.update(trace={"correlation_id": CORRELATION, "x": 1}),
        lambda value: value.update(payload={"invalid": {1, 2}}),
        lambda value: value.update(work_item_id="not-a-uuid"),
        lambda value: value.update(submitted_at="not-a-time"),
        lambda value: value.update(submitted_at="2026-10-18T12:00:00"),
        lambda value: value.update(result_type=" "),
    ],
)
def test_s6_work_result_validation_rejects_each_guarded_shape(mutation):
    _, _, _, claimed = _wc_runtime()
    candidate = _work_result(claimed)
    mutation(candidate)
    with pytest.raises(WorkResultError):
        validate_work_result(candidate)


def test_s6_work_result_validation_rejects_non_object():
    with pytest.raises(WorkResultError, match="must be an object"):
        validate_work_result([])


class _AuthorizationFailure:
    def effective_authorization(self, **_kwargs):
        raise RuntimeError("OA unavailable")


class _AuthorizationPayload:
    def __init__(self, payload):
        self.payload = payload

    def effective_authorization(self, **_kwargs):
        return self.payload


@pytest.mark.parametrize(
    "authorization",
    [
        {"active": False, "scopes": ["work:result:submit"], "revision_hash": "a"},
        {"active": True, "scopes": "work:result:submit", "revision_hash": "a"},
        {"active": True, "scopes": ["work:claim"], "revision_hash": "a"},
    ],
)
def test_s6_work_result_service_denies_inactive_or_missing_authority(authorization):
    _, repository, _, claimed = _wc_runtime()
    service = WorkResultService(
        repository,
        authorization_source=_AuthorizationPayload(authorization),
        clock=lambda: NOW_DT,
    )
    with pytest.raises(WorkResultError, match="lacks active"):
        service.submit(
            tenant_id=TENANT,
            work_item_id=WORK_ITEM_ID,
            expected_version=claimed["work_item"]["version"],
            work_result=_work_result(claimed),
        )


def test_s6_work_result_service_fails_closed_for_missing_context_and_oa_failure():
    _, repository, _, claimed = _wc_runtime()
    service = WorkResultService(
        repository,
        authorization_source=_AuthorizationFailure(),
        clock=lambda: NOW_DT,
    )
    with pytest.raises(WorkResultError, match="unavailable"):
        service.submit(
            tenant_id=TENANT,
            work_item_id=WORK_ITEM_ID,
            expected_version=claimed["work_item"]["version"],
            work_result=_work_result(claimed),
        )
    with pytest.raises(WorkResultError, match="path lineage"):
        service.submit(
            tenant_id="other-tenant",
            work_item_id=WORK_ITEM_ID,
            expected_version=claimed["work_item"]["version"],
            work_result=_work_result(claimed),
        )
    missing_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa61"
    missing = _work_result(claimed)
    missing["work_item_id"] = missing_id
    with pytest.raises(WorkResultError, match="not found"):
        service.submit(
            tenant_id=TENANT,
            work_item_id=missing_id,
            expected_version=claimed["work_item"]["version"],
            work_result=missing,
        )


@pytest.mark.parametrize(
    ("context_change", "message"),
    [
        (lambda context: context["work_item"].update(version=99), "expected ASSIGNED"),
        (lambda context: context.update(claim=None), "active Claim"),
        (lambda context: context.update(assignment=None), "active Assignment"),
    ],
)
def test_s6_repository_rechecks_version_claim_and_assignment(context_change, message):
    _, repository, _, claimed = _wc_runtime()
    result = validate_work_result(_work_result(claimed))
    context = repository.get_submission_context(
        tenant_id=TENANT, work_item_id=WORK_ITEM_ID
    )
    context_change(context)
    original = repository.get_submission_context
    repository.get_submission_context = lambda **_kwargs: context
    try:
        with pytest.raises(WorkResultError, match=message):
            repository.commit_result(
                work_result=result,
                result_hash=semantic_sha256_hash_ref(result),
                expected_version=claimed["work_item"]["version"],
                authorization={"revision_hash": "a" * 64},
                outbox_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa62",
                event_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa63",
                now=NOW,
            )
    finally:
        repository.get_submission_context = original


def test_s6_in_memory_outbox_guards_missing_conflict_and_terminal_replay():
    repository, _, _, _, accepted, _ = _accepted_result()
    with pytest.raises(WorkResultError, match="not found"):
        repository.load_result_event(outbox_id="missing", event_id="missing")
    with pytest.raises(WorkResultError, match="not found"):
        repository.mark_result_event_enqueued(
            outbox_id="missing", event_id="missing", job_id="job", updated_at=NOW
        )
    enqueued = repository.mark_result_event_enqueued(
        outbox_id=accepted["outbox_id"],
        event_id=accepted["event_id"],
        job_id="job-1",
        updated_at=NOW,
    )
    assert enqueued["delivery_state"] == "ENQUEUED"
    with pytest.raises(WorkResultError, match="another delivery job"):
        repository.mark_result_event_enqueued(
            outbox_id=accepted["outbox_id"],
            event_id=accepted["event_id"],
            job_id="job-2",
            updated_at=NOW,
        )
    repository.mark_result_event_delivered(
        outbox_id=accepted["outbox_id"],
        event_id=accepted["event_id"],
        job_id="job-1",
        updated_at=NOW,
    )
    terminal = repository.mark_result_event_enqueued(
        outbox_id=accepted["outbox_id"],
        event_id=accepted["event_id"],
        job_id="job-1",
        updated_at=NOW,
    )
    assert terminal["delivery_state"] == "DELIVERED"


class _AckClient:
    def __init__(self, event_id):
        self.event_id = event_id

    def deliver(self, _event):
        return {"event_id": self.event_id}


def test_s6_delivery_worker_rejects_job_and_stored_event_drift():
    repository, _, _, _, _, _ = _accepted_result()
    queue = InMemoryJobQueue()
    job = enqueue_pending_result_events(store=repository, queue=queue)[0]
    for mutation in (
        lambda value: value.update(job_type="OTHER"),
        lambda value: value.update(payload={"event_id": EVENT_ID}),
        lambda value: value.update(subject_ref={"type": "WC_OUTBOX", "id": "other"}),
        lambda value: value.update(idempotency_key="other"),
    ):
        changed = copy.deepcopy(job)
        mutation(changed)
        with pytest.raises(WorkResultDeliveryError):
            run_work_result_delivery_job(
                changed,
                store=repository,
                client=_AckClient(EVENT_ID),
            )
    with pytest.raises(WorkResultDeliveryError, match="different WorkResult event"):
        run_work_result_delivery_job(
            job,
            store=repository,
            client=_AckClient("other-event"),
        )
    row = next(
        item
        for item in repository._coordination._outbox.values()
        if item["event_type"] == "WORK_RESULT_SUBMITTED"
    )
    row["event_payload"] = []
    with pytest.raises(WorkResultDeliveryError, match="Stored WorkResult event"):
        run_work_result_delivery_job(
            job,
            store=repository,
            client=_AckClient(EVENT_ID),
        )


class _MalformedPendingStore:
    def __init__(self, row):
        self.row = row

    def list_pending_result_events(self, *, limit):
        return [self.row]


@pytest.mark.parametrize(
    "row",
    [
        {"event_id": EVENT_ID, "event_type": "WORK_RESULT_SUBMITTED", "event_payload": _event()},
        {"outbox_id": "outbox", "event_id": EVENT_ID, "event_type": "OTHER", "event_payload": _event()},
    ],
)
def test_s6_delivery_bridge_rejects_malformed_pending_rows(row):
    with pytest.raises(WorkResultDeliveryError):
        enqueue_pending_result_events(
            store=_MalformedPendingStore(row),
            queue=InMemoryJobQueue(),
        )


def test_s6_delivery_http_client_rejects_http_and_response_failures(monkeypatch):
    client = HttpWorkResultEventClient(base_url="http://ae", service_token="token")
    monkeypatch.setattr(
        "nex_wc.work_result_delivery.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HTTPError("http://ae", 503, "unavailable", None, None)
        ),
    )
    with pytest.raises(WorkResultDeliveryError, match="HTTP 503") as captured:
        client.deliver(_event())
    assert captured.value.retryable is True
    monkeypatch.setattr(
        "nex_wc.work_result_delivery.urlopen",
        lambda *args, **kwargs: _Response({"event_id": "wrong"}),
    )
    with pytest.raises(WorkResultDeliveryError, match="response is invalid"):
        client.deliver(_event())
