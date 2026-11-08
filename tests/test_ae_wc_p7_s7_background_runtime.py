from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import nex_ae_api.background_planning as background_module
import nex_ae_api.semantic_candidate_admission as semantic_module
import pytest
from nex_ae_api.agent_execution import AgentExecutionError
from nex_ae_api.background_planning import (
    BackgroundAgentPlanningService,
    BackgroundPlanningError,
)
from nex_ae_api.intent_policy import resolve_validated_intent_candidate
from nex_ae_api.semantic_candidate_admission import SemanticCandidateAdmissionError
from nex_ae_api.work_intent import (
    WorkIntentError,
    build_work_intent_from_claimed_work,
)
from nex_ae_api.work_result_publication import (
    HttpWcWorkResultClient,
    SqlAlchemyWcWorkResultPublisher,
    WorkResultPublicationError,
    build_wc_work_result,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc.work_results import validate_work_result
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "tenant-p7-s7"
EXECUTION_ID = "11111111-1111-4111-8111-111111111117"
AGENT_ID = "22222222-2222-4222-8222-222222222227"
WORK_ITEM_ID = "33333333-3333-4333-8333-333333333337"
PROJECT_ID = "project-p7-s7"
CLAIM_ID = "44444444-4444-4444-8444-444444444447"
ASSIGNMENT_ID = "55555555-5555-4555-8555-555555555557"
RESULT_ID = "66666666-6666-4666-8666-666666666667"
DELIVERY_ID = "77777777-7777-4777-8777-777777777777"
PLAN_ID = "88888888-8888-4888-8888-888888888887"
NOW = "2026-10-19T09:00:00Z"
RESULT_CONTRACT = "urn:nex:result:background-analysis:1"


def _planning_source() -> dict:
    return {
        "schema_version": "p7.claimed_work_planning_source.v1",
        "source_type": "CLAIMED_WORKITEM",
        "source_ref": WORK_ITEM_ID,
        "goal": "Summarize the authorized project evidence.",
        "work_class": "ANALYSIS",
        "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
        "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT_ID},
        "artifact_refs": [
            {"entity_type": "ARTIFACT", "entity_id": "artifact-p7-s7"}
        ],
        "evidence_refs": [],
        "completion_policy": "OWNER_SUBMITS",
        "result_contract_ref": RESULT_CONTRACT,
    }


def _execution(agent_type: str = "PA") -> dict:
    return {
        "tenant_id": TENANT,
        "agent_execution_id": EXECUTION_ID,
        "agent_id": AGENT_ID,
        "agent_type": agent_type,
        "source_type": "CLAIMED_WORKITEM",
        "source_ref": WORK_ITEM_ID,
        "work_item_ref": WORK_ITEM_ID,
        "project_id": PROJECT_ID,
        "requester_ref": "employee-100",
        "correlation_id": "p7-s7-correlation",
        "causation_id": WORK_ITEM_ID,
        "received_at": NOW,
    }


class _Executions:
    def __init__(self, *, agent_type: str = "PA", source: dict | None = None):
        self.execution = _execution(agent_type)
        self.source = source or _planning_source()

    def get(self, tenant_id, execution_id):
        if tenant_id == TENANT and execution_id == EXECUTION_ID:
            return dict(self.execution)
        return None

    def get_claimed_planning_source(self, tenant_id, execution_id):
        if tenant_id == TENANT and execution_id == EXECUTION_ID:
            return None if self.source is None else dict(self.source)
        return None


class _Capabilities:
    def get_latest(self, *, tenant_id):
        return {"tenant_id": tenant_id, "snapshot": "active"}


class _SemanticAdmission:
    def __init__(self):
        self.capabilities = _Capabilities()
        self.requests = []

    def admit_and_compile(self, request):
        self.requests.append(request)
        return SimpleNamespace(status="COMPILED", executable_plan_id=PLAN_ID)


class _MissingCapabilities:
    def get_latest(self, *, tenant_id):
        return None


class _FailingSemanticAdmission:
    def __init__(self, *, capabilities=None):
        self.capabilities = capabilities or _Capabilities()

    def admit_and_compile(self, request):
        raise SemanticCandidateAdmissionError(
            503,
            "SEMANTIC_STAGE_FAILED",
            "semantic admission failed",
            True,
            semantic_stage="PLAN",
        )


@pytest.mark.parametrize("agent_type", ["CA", "PA", "EA"])
def test_background_planning_routes_claimed_agents_through_existing_admission(
    agent_type: str,
) -> None:
    admission = _SemanticAdmission()
    service = BackgroundAgentPlanningService(
        semantic_admission=admission,
        executions=_Executions(agent_type=agent_type),
    )

    result = service.plan_claimed_execution(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        runtime_policy_ref={
            "rule_id": "ae.background.default",
            "rule_version": "v1",
            "rule_hash": "sha256:" + "a" * 64,
        },
    )

    assert result.status == "COMPILED"
    request = admission.requests[0]
    assert request.existing_execution_id == EXECUTION_ID
    assert request.planning_source_type == "CLAIMED_WORKITEM"
    assert request.agent_type == agent_type
    assert request.project_id == PROJECT_ID
    assert request.source_ref == WORK_ITEM_ID
    assert request.planning_source == _planning_source()
    assert request.trusted_execution_mode == "DOCUMENT_SUMMARY"
    assert request.retrieval_enabled is True
    resolved = request.context_resolver.resolve(
        SimpleNamespace(
            tenant_id=TENANT,
            principal_id="employee-100",
            agent_id=AGENT_ID,
            execution_id=EXECUTION_ID,
            agent_type=agent_type,
            source_type="CLAIMED_WORKITEM",
            source_ref=WORK_ITEM_ID,
        )
    )
    assert resolved.project_ref["resource_id"] == PROJECT_ID
    assert resolved.authority_ref == f"WC:WORK_ITEM:{WORK_ITEM_ID}"


def test_claimed_work_intent_keeps_wc_authority_over_provider_candidate() -> None:
    decision = resolve_validated_intent_candidate(
        {
            "intent_label": "provider_selected_untrusted_label",
            "suggested_execution_mode": "GROUNDED_ANSWER",
            "confidence": 0.91,
        }
    )
    intent = build_work_intent_from_claimed_work(
        execution_id=EXECUTION_ID,
        actor_ref="employee-100",
        received_at=NOW,
        planning_source=_planning_source(),
        intent_decision=decision,
        input_context_hash="sha256:" + "b" * 64,
        work_intent_id="99999999-9999-4999-8999-999999999997",
    )

    assert intent["source"] == {
        "source_type": "CLAIMED_WORKITEM",
        "source_ref": WORK_ITEM_ID,
        "actor_ref": "employee-100",
        "received_at": NOW,
    }
    assert intent["goal"] == _planning_source()["goal"]
    assert intent["project_ref"]["resource_id"] == PROJECT_ID
    assert intent["required_capability_hints"] == [
        "FINANCE.PROJECT_BUDGET_CHECK"
    ]
    assert "claimant" not in json.dumps(intent)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda decision, source: decision.update(
            intent_decision_schema_version="unsupported"
        ),
        lambda decision, source: decision.update(raw_prompt_included=True),
        lambda decision, source: decision.update(execution_mode="UNSUPPORTED"),
        lambda decision, source: decision.update(confidence=True),
        lambda decision, source: decision.update(confidence=2.0),
        lambda decision, source: source.update(unexpected=True),
        lambda decision, source: source.update(schema_version="unsupported"),
        lambda decision, source: source.update(project_ref=None),
    ),
)
def test_claimed_work_intent_rejects_untrusted_decision_and_source_drift(
    mutation,
) -> None:
    decision = dict(
        resolve_validated_intent_candidate(
            {
                "intent_label": "analysis",
                "suggested_execution_mode": "GROUNDED_ANSWER",
                "confidence": 0.9,
            }
        )
    )
    source = _planning_source()
    mutation(decision, source)

    with pytest.raises(WorkIntentError):
        build_work_intent_from_claimed_work(
            execution_id=EXECUTION_ID,
            actor_ref="employee-100",
            received_at=NOW,
            planning_source=source,
            intent_decision=decision,
            input_context_hash="sha256:" + "b" * 64,
            work_intent_id="99999999-9999-4999-8999-999999999997",
        )


def test_claimed_execution_semantic_authority_guards() -> None:
    request = SimpleNamespace(
        tenant_id=TENANT,
        agent_type="PA",
        project_id=PROJECT_ID,
        source_ref=WORK_ITEM_ID,
        owner_subject_id="employee-100",
        planning_source=_planning_source(),
    )
    with pytest.raises(SemanticCandidateAdmissionError) as missing:
        semantic_module._require_claimed_execution(None, request)
    assert missing.value.error_code == "CLAIMED_EXECUTION_NOT_FOUND"

    with pytest.raises(SemanticCandidateAdmissionError) as lineage:
        semantic_module._require_claimed_execution(
            {**_execution(), "project_id": "different-project"}, request
        )
    assert lineage.value.error_code == "CLAIMED_EXECUTION_LINEAGE_CONFLICT"

    missing_source = SimpleNamespace(**{**vars(request), "planning_source": None})
    with pytest.raises(SemanticCandidateAdmissionError) as source:
        semantic_module._require_claimed_execution(_execution(), missing_source)
    assert source.value.error_code == "CLAIMED_PLANNING_SOURCE_CONFLICT"

    with pytest.raises(SemanticCandidateAdmissionError) as invalid_request:
        semantic_module._request_text_value("execution", " ", 64)
    assert invalid_request.value.error_code == "PLANNING_REQUEST_INVALID"
    assert semantic_module._request_text_value("execution", " id ", 64) == "id"


def test_background_planning_failure_boundaries_are_typed() -> None:
    class _UnavailableExecutions(_Executions):
        def get(self, tenant_id, execution_id):
            raise AgentExecutionError("ae.store_unavailable", "offline", True)

    with pytest.raises(BackgroundPlanningError) as unavailable:
        BackgroundAgentPlanningService(
            semantic_admission=_SemanticAdmission(),
            executions=_UnavailableExecutions(),
        ).plan_claimed_execution(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            runtime_policy_ref={"rule_id": "x"},
        )
    assert unavailable.value.retryable is True

    missing_source = _Executions()
    missing_source.source = None
    with pytest.raises(BackgroundPlanningError) as missing:
        BackgroundAgentPlanningService(
            semantic_admission=_SemanticAdmission(),
            executions=missing_source,
        ).plan_claimed_execution(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            runtime_policy_ref={"rule_id": "x"},
        )
    assert missing.value.error_code == "ae.background_planning_source_missing"

    semantic = _FailingSemanticAdmission(capabilities=_MissingCapabilities())
    with pytest.raises(BackgroundPlanningError) as no_capability:
        BackgroundAgentPlanningService(
            semantic_admission=semantic,
            executions=_Executions(),
        ).plan_claimed_execution(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            runtime_policy_ref={"rule_id": "x"},
        )
    assert (
        no_capability.value.error_code
        == "ae.background_planning_capability_snapshot_missing"
    )

    with pytest.raises(BackgroundPlanningError) as semantic_failure:
        BackgroundAgentPlanningService(
            semantic_admission=_FailingSemanticAdmission(),
            executions=_Executions(),
        ).plan_claimed_execution(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            runtime_policy_ref={"rule_id": "x"},
        )
    assert semantic_failure.value.error_code == "SEMANTIC_STAGE_FAILED"
    assert semantic_failure.value.retryable is True


def test_background_context_and_execution_profiles_fail_closed() -> None:
    admission = _SemanticAdmission()
    BackgroundAgentPlanningService(
        semantic_admission=admission,
        executions=_Executions(),
    ).plan_claimed_execution(
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
        runtime_policy_ref={"rule_id": "x"},
    )
    request = admission.requests[0]
    with pytest.raises(BackgroundPlanningError) as mismatch:
        request.context_resolver.resolve(
            SimpleNamespace(
                tenant_id="other-tenant",
                principal_id="employee-100",
                agent_id=AGENT_ID,
                execution_id=EXECUTION_ID,
                agent_type="PA",
                source_type="CLAIMED_WORKITEM",
                source_ref=WORK_ITEM_ID,
            )
        )
    assert mismatch.value.error_code == "ae.background_context_scope_mismatch"

    assert background_module._trusted_execution_profile(
        {"work_class": "DOCUMENT"}
    ) == ("DOCUMENT_GENERATION", True)
    assert background_module._trusted_execution_profile(
        {"work_class": "QUERY", "artifact_refs": [{}]}
    ) == ("GROUNDED_ANSWER", True)
    assert background_module._trusted_execution_profile(
        {"work_class": "QUERY", "artifact_refs": [], "evidence_refs": []}
    ) == ("GENERAL_ANSWER", False)
    assert background_module._resource_ref(
        {"entity_type": "ARTIFACT", "entity_id": "a", "version": 3}
    )["version"] == "3"


def _publisher_sessions():
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    result = {
        "schema_version": "2.1",
        "tenant_id": TENANT,
        "result_id": RESULT_ID,
        "agent_execution_id": EXECUTION_ID,
        "agent_id": AGENT_ID,
        "agent_type": "PA",
        "status": "SUCCEEDED",
        "structured_result": {"answer": "Authorized project evidence summary."},
        "artifact_refs": ["artifact-p7-s7"],
        "evidence_refs": [],
        "business_refs": [],
        "provenance": {"executable_plan_id": PLAN_ID},
    }
    result["result_hash"] = semantic_sha256_hash_ref(result)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ae_agent_execution (
                tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, agent_type TEXT NOT NULL,
                project_id TEXT, work_item_ref TEXT, claim_ref TEXT,
                claim_generation INTEGER, assignment_ref TEXT,
                correlation_id TEXT, causation_id TEXT,
                state TEXT NOT NULL, phase TEXT NOT NULL, version INTEGER NOT NULL,
                result_id TEXT, completed_at TEXT, updated_at TEXT,
                PRIMARY KEY (tenant_id, agent_execution_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_agent_result (
                tenant_id TEXT NOT NULL, result_id TEXT NOT NULL,
                result_envelope_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, result_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_result_delivery (
                tenant_id TEXT NOT NULL, delivery_id TEXT NOT NULL,
                result_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                target_type TEXT NOT NULL, target_ref TEXT NOT NULL,
                state TEXT NOT NULL, attempt_no INTEGER NOT NULL,
                external_delivery_ref TEXT, latest_preflight_ref TEXT,
                created_at TEXT, updated_at TEXT, acknowledged_at TEXT,
                PRIMARY KEY (tenant_id, delivery_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_claim_handoff_inbox (
                tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                planning_source_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, agent_execution_id)
            )
        """))
        connection.execute(
            text("""
                INSERT INTO ae_agent_execution VALUES (
                    :tenant_id, :execution_id, :agent_id, 'PA', :project_id,
                    :work_item_id, :claim_id, 1, :assignment_id,
                    'p7-s7-correlation', :work_item_id,
                    'RUNNING', 'RESULT_PUBLISH', 4, :result_id, NULL, :now
                )
            """),
            {
                "tenant_id": TENANT,
                "execution_id": EXECUTION_ID,
                "agent_id": AGENT_ID,
                "project_id": PROJECT_ID,
                "work_item_id": WORK_ITEM_ID,
                "claim_id": CLAIM_ID,
                "assignment_id": ASSIGNMENT_ID,
                "result_id": RESULT_ID,
                "now": NOW,
            },
        )
        connection.execute(
            text("INSERT INTO ae_agent_result VALUES (:tenant_id, :result_id, :value)"),
            {"tenant_id": TENANT, "result_id": RESULT_ID, "value": json.dumps(result)},
        )
        connection.execute(
            text("""
                INSERT INTO ae_result_delivery VALUES (
                    :tenant_id, :delivery_id, :result_id, :execution_id,
                    'WC_WORK_RESULT', :work_item_id, 'PENDING', 0,
                    NULL, NULL, :now, :now, NULL
                )
            """),
            {
                "tenant_id": TENANT,
                "delivery_id": DELIVERY_ID,
                "result_id": RESULT_ID,
                "execution_id": EXECUTION_ID,
                "work_item_id": WORK_ITEM_ID,
                "now": NOW,
            },
        )
        connection.execute(
            text("INSERT INTO ae_claim_handoff_inbox VALUES (:tenant_id, :execution_id, :value)"),
            {
                "tenant_id": TENANT,
                "execution_id": EXECUTION_ID,
                "value": json.dumps(_planning_source()),
            },
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class _WcClient:
    def __init__(self):
        self.status_calls = 0
        self.submit_calls = 0
        self.work_result = None

    def status(self, *, tenant_id, work_item_id):
        self.status_calls += 1
        return {"tenant_id": tenant_id, "work_item_id": work_item_id, "version": 7}

    def submit(self, *, expected_version, work_result):
        self.submit_calls += 1
        self.work_result = dict(work_result)
        assert expected_version == 7
        return {
            "work_item_id": WORK_ITEM_ID,
            "work_item_version": 8,
            "result_id": RESULT_ID,
            "result_hash": semantic_sha256_hash_ref(work_result),
            "created": True,
        }


class _HttpResponse:
    def __init__(self, payload, *, raw: bool = False):
        self.payload = payload if raw else json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def test_wc_http_client_status_and_transport_guards(monkeypatch) -> None:
    client = HttpWcWorkResultClient(base_url="http://wc", service_token="token")
    monkeypatch.setattr(
        "nex_ae_api.work_result_publication.urlopen",
        lambda *args, **kwargs: _HttpResponse(
            {"tenant_id": TENANT, "work_item_id": WORK_ITEM_ID, "version": 7}
        ),
    )
    assert client.status(tenant_id=TENANT, work_item_id=WORK_ITEM_ID)["version"] == 7

    for payload in (
        {"tenant_id": "other", "work_item_id": WORK_ITEM_ID, "version": 7},
        {"tenant_id": TENANT, "work_item_id": WORK_ITEM_ID, "version": True},
        {"tenant_id": TENANT, "work_item_id": WORK_ITEM_ID, "version": 0},
    ):
        monkeypatch.setattr(
            "nex_ae_api.work_result_publication.urlopen",
            lambda *args, payload=payload, **kwargs: _HttpResponse(payload),
        )
        with pytest.raises(WorkResultPublicationError) as invalid:
            client.status(tenant_id=TENANT, work_item_id=WORK_ITEM_ID)
        assert invalid.value.error_code == "ae.wc_work_result_ack_invalid"

    with pytest.raises(WorkResultPublicationError) as missing_token:
        HttpWcWorkResultClient(base_url="http://wc", service_token="").status(
            tenant_id=TENANT, work_item_id=WORK_ITEM_ID
        )
    assert missing_token.value.retryable is False

    monkeypatch.setattr(
        "nex_ae_api.work_result_publication.urlopen",
        lambda *args, **kwargs: _HttpResponse(b"not-json", raw=True),
    )
    with pytest.raises(WorkResultPublicationError) as malformed:
        client.status(tenant_id=TENANT, work_item_id=WORK_ITEM_ID)
    assert malformed.value.error_code == "ae.wc_work_result_unavailable"

    for status, retryable in ((503, True), (400, False)):
        monkeypatch.setattr(
            "nex_ae_api.work_result_publication.urlopen",
            lambda *args, status=status, **kwargs: (_ for _ in ()).throw(
                HTTPError("http://wc", status, "failed", None, None)
            ),
        )
        with pytest.raises(WorkResultPublicationError) as failed:
            client.status(tenant_id=TENANT, work_item_id=WORK_ITEM_ID)
        assert failed.value.retryable is retryable

    monkeypatch.setattr(
        "nex_ae_api.work_result_publication.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")),
    )
    with pytest.raises(WorkResultPublicationError) as offline:
        client.status(tenant_id=TENANT, work_item_id=WORK_ITEM_ID)
    assert offline.value.retryable is True

    monkeypatch.setattr(
        "nex_ae_api.work_result_publication.urlopen",
        lambda *args, **kwargs: _HttpResponse([]),
    )
    with pytest.raises(WorkResultPublicationError) as non_object:
        client.status(tenant_id=TENANT, work_item_id=WORK_ITEM_ID)
    assert non_object.value.error_code == "ae.wc_work_result_ack_invalid"


def test_wc_ack_is_the_background_child_success_barrier() -> None:
    sessions = _publisher_sessions()
    client = _WcClient()
    publisher = SqlAlchemyWcWorkResultPublisher(sessions, client)

    with sessions() as session:
        before = session.execute(
            text("SELECT state, phase FROM ae_agent_execution")
        ).mappings().one()
    assert dict(before) == {"state": "RUNNING", "phase": "RESULT_PUBLISH"}

    published = publisher.publish(
        tenant_id=TENANT, delivery_id=DELIVERY_ID, now=NOW
    )

    assert published["delivery_state"] == "ACKNOWLEDGED"
    assert published["execution_state"] == "SUCCEEDED"
    assert validate_work_result(client.work_result)["schema_ref"] == RESULT_CONTRACT
    with sessions() as session:
        execution = session.execute(
            text("SELECT state, phase, completed_at FROM ae_agent_execution")
        ).mappings().one()
        delivery = session.execute(
            text("SELECT state, attempt_no, acknowledged_at FROM ae_result_delivery")
        ).mappings().one()
    assert dict(execution) == {
        "state": "SUCCEEDED",
        "phase": "FINALIZE",
        "completed_at": NOW,
    }
    assert dict(delivery) == {
        "state": "ACKNOWLEDGED",
        "attempt_no": 1,
        "acknowledged_at": NOW,
    }

    replay = publisher.publish(tenant_id=TENANT, delivery_id=DELIVERY_ID, now=NOW)
    assert replay["created"] is False
    assert client.status_calls == client.submit_calls == 1


def test_background_planning_and_publication_fail_closed_on_lineage_drift() -> None:
    drifted = _planning_source()
    drifted["source_ref"] = "different-work-item"
    with pytest.raises(BackgroundPlanningError, match="does not match"):
        BackgroundAgentPlanningService(
            semantic_admission=_SemanticAdmission(),
            executions=_Executions(source=drifted),
        ).plan_claimed_execution(
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
            runtime_policy_ref={"rule_id": "x"},
        )

    sessions = _publisher_sessions()
    with sessions.begin() as session:
        session.execute(
            text("UPDATE ae_result_delivery SET target_ref = 'different-work-item'")
        )
    with pytest.raises(WorkResultPublicationError, match="outside"):
        SqlAlchemyWcWorkResultPublisher(sessions, _WcClient()).publish(
            tenant_id=TENANT, delivery_id=DELIVERY_ID, now=NOW
        )


def test_wc_publication_state_store_and_result_shape_guards() -> None:
    sessions = _publisher_sessions()
    publisher = SqlAlchemyWcWorkResultPublisher(sessions, _WcClient())
    with pytest.raises(WorkResultPublicationError) as missing:
        publisher.publish(tenant_id=TENANT, delivery_id="missing", now=NOW)
    assert missing.value.error_code == "ae.wc_work_result_delivery_not_found"

    with sessions.begin() as session:
        session.execute(
            text("UPDATE ae_result_delivery SET state = 'CANCELLED'")
        )
    with pytest.raises(WorkResultPublicationError) as state:
        publisher.publish(tenant_id=TENANT, delivery_id=DELIVERY_ID, now=NOW)
    assert state.value.error_code == "ae.wc_work_result_delivery_state_invalid"

    conflict_sessions = _publisher_sessions()
    with conflict_sessions.begin() as session:
        session.execute(
            text("UPDATE ae_agent_execution SET phase = 'STEP_EXECUTION'")
        )
    with pytest.raises(WorkResultPublicationError) as conflict:
        SqlAlchemyWcWorkResultPublisher(
            conflict_sessions, _WcClient()
        ).publish(tenant_id=TENANT, delivery_id=DELIVERY_ID, now=NOW)
    assert conflict.value.error_code == "ae.wc_work_result_execution_conflict"

    unavailable = sessionmaker(
        bind=create_engine("sqlite+pysqlite://"),
        autoflush=False,
        expire_on_commit=False,
    )
    with pytest.raises(WorkResultPublicationError) as store:
        SqlAlchemyWcWorkResultPublisher(unavailable, _WcClient()).publish(
            tenant_id=TENANT, delivery_id=DELIVERY_ID, now=NOW
        )
    assert store.value.error_code == "ae.wc_work_result_store_unavailable"

    base_result = {
        "tenant_id": TENANT,
        "result_id": RESULT_ID,
        "agent_execution_id": EXECUTION_ID,
        "agent_id": AGENT_ID,
        "status": "UNKNOWN",
        "result_hash": "sha256:" + "a" * 64,
        "structured_result": {},
        "artifact_refs": None,
        "evidence_refs": [],
        "business_refs": [],
        "provenance": "invalid",
    }
    execution = {
        "agent_execution_id": EXECUTION_ID,
        "work_item_ref": WORK_ITEM_ID,
        "claim_ref": CLAIM_ID,
        "claim_generation": 1,
        "assignment_ref": ASSIGNMENT_ID,
        "correlation_id": "corr",
        "causation_id": None,
    }
    built = build_wc_work_result(
        agent_result=base_result,
        execution=execution,
        planning_source=_planning_source(),
        submitted_at=NOW,
    )
    assert built["technical_outcome"] == "FAILED"
    assert built["artifact_refs"] == []
    assert built["source_plan_ref"] is None

    for invalid_refs in ("not-a-list", ["x" * 161]):
        with pytest.raises(WorkResultPublicationError):
            build_wc_work_result(
                agent_result={**base_result, "artifact_refs": invalid_refs},
                execution=execution,
                planning_source=_planning_source(),
                submitted_at=NOW,
            )
