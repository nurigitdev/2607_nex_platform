from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError

import nex_ae_api.delegated_work as delegated_work_module
import pytest
from nex_ae_api.agent_plans import build_deterministic_agent_plan
from nex_ae_api.delegated_work import (
    DelegatedWorkError,
    HttpWcWorkItemClient,
    SqlAlchemyDelegationRuntimeRepository,
    SqlAlchemyWaitRegistrationRepository,
    delegation_dispatch,
)
from nex_ae_api.executable_plans import compile_executable_plan
from nex_ae_api.multi_step_engine import StepExecutionContext
from nex_ae_api.plan_candidate_generation import (
    PlanCandidateStageError,
    parse_plan_candidate,
)
from nex_ae_api.plan_validation import validate_agent_plan
from nex_ae_api.planning_capabilities import build_capability_snapshot
from nex_ae_api.step_executors import (
    DelegateWorkExecutorDependencies,
    P5StepExecutorError,
    P7DelegateWorkExecutor,
    validate_delegate_work_executor_dependencies,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TENANT = "tenant-p7-s5"
PROJECT = "project-p7-s5"
EXECUTION_ID = "11111111-1111-4111-8111-111111111115"
INTENT_ID = "22222222-2222-4222-8222-222222222225"
CONTEXT_ID = "33333333-3333-4333-8333-333333333335"
SNAPSHOT_ID = "44444444-4444-4444-8444-444444444445"
PLAN_ID = "55555555-5555-4555-8555-555555555555"
VALIDATION_ID = "66666666-6666-4666-8666-666666666665"
EXECUTABLE_PLAN_ID = "77777777-7777-4777-8777-777777777775"
STEP_ID = "88888888-8888-4888-8888-888888888885"
NOW = "2026-10-18T10:00:00Z"


def _intent():
    value = {
        "schema_version": "1.1",
        "work_intent_id": INTENT_ID,
        "intent_revision": 1,
        "execution_id": EXECUTION_ID,
        "compatibility_execution_mode": "GENERAL_ANSWER",
        "intent_label": "Delegate project analysis",
        "goal": "Prepare project margin evidence.",
        "work_class": "ANALYSIS",
        "completion_criteria": [
            {
                "criterion_id": "C1",
                "description": "The delegated result is accepted.",
                "required": True,
            }
        ],
        "clarification": {"status": "NOT_REQUIRED", "reasons": [], "questions": []},
        "entity_selectors": [],
    }
    value["intent_hash"] = semantic_sha256_hash_ref(value)
    return value


def _context(intent):
    value = {
        "schema_version": "1.1",
        "context_id": CONTEXT_ID,
        "context_generation": 1,
        "execution_id": EXECUTION_ID,
        "work_intent_ref": {
            "id": INTENT_ID,
            "version": 1,
            "hash": intent["intent_hash"],
        },
        "identity": {"tenant_id": TENANT, "subject_id": "subject-p7-s5"},
        "project_ref": {
            "system": "ENTERPRISE_OS",
            "resource_type": "PROJECT",
            "resource_id": PROJECT,
        },
        "runtime_policy_ref": {
            "rule_id": "p7-runtime",
            "rule_version": "1",
            "rule_hash": semantic_sha256_hash_ref({"max_steps": 12}),
        },
        "authority_ref": "authority://oa/subject-p7-s5/v1",
        "resolved_entities": [],
        "retrieval_refs": [],
        "evidence_refs": [],
        "conflicts": [],
        "degradations": [],
    }
    value["context_hash"] = semantic_sha256_hash_ref(value)
    return value


def _snapshot():
    return build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id=SNAPSHOT_ID,
        snapshot_version=1,
        created_at=NOW,
    )


def _delegate_plan():
    intent = _intent()
    context = _context(intent)
    snapshot = _snapshot()
    plan = build_deterministic_agent_plan(
        work_intent=intent,
        agent_context=context,
        capability_snapshot=snapshot,
        agent_plan_id=PLAN_ID,
    )
    step = plan["steps"][0]
    step.update(
        {
            "step_type": "DELEGATE_WORK",
            "title": "Delegate project margin analysis",
            "objective": "Prepare project margin evidence.",
            "required_capability": "FINANCE.PROJECT_MARGIN_READ",
            "capability_version_constraint": None,
            "output_contract_ref": "urn:nex:result:project-margin:1",
            "completion_criteria": ["A bounded WorkResult is accepted."],
            "delegation": {
                "work_class": "ANALYSIS",
                "required_agent_type": "PA",
                "project_scope_ref": PROJECT,
                "result_contract_ref": "urn:nex:result:project-margin:1",
                "completion_policy": "OWNER_SUBMITS",
            },
        }
    )
    plan["planning_constraints"]["max_delegation_depth"] = 1
    plan["plan_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in plan.items() if key != "plan_hash"}
    )
    return intent, context, snapshot, plan


def _candidate():
    return {
        "schema_version": "p7.plan_candidate.v1",
        "suggested_plan_kind": "DIRECT",
        "goal": "Prepare project margin evidence.",
        "logical_steps": [
            {
                "step_id": "S1",
                "step_type": "DELEGATE_WORK",
                "title": "Delegate project margin analysis",
                "objective": "Prepare project margin evidence.",
                "depends_on": [],
                "capability_hint": "FINANCE.PROJECT_MARGIN_READ",
                "completion_criteria": ["A bounded WorkResult is accepted."],
                "delegation": {
                    "work_class": "ANALYSIS",
                    "required_agent_type": "PA",
                    "project_scope_ref": PROJECT,
                    "result_contract_ref": "urn:nex:result:project-margin:1",
                    "completion_policy": "OWNER_SUBMITS",
                },
            }
        ],
        "completion_mapping": [
            {"criterion_id": "C1", "terminal_step_refs": ["S1"]}
        ],
        "confidence": 0.95,
    }


def test_s5_p7_candidate_requires_bounded_delegation_without_assignee():
    assert parse_plan_candidate(json.dumps(_candidate()))["logical_steps"][0][
        "delegation"
    ]["required_agent_type"] == "PA"

    legacy = _candidate()
    legacy["schema_version"] = "p65.plan_candidate.v1"
    with pytest.raises(PlanCandidateStageError):
        parse_plan_candidate(json.dumps(legacy))

    allocated = _candidate()
    allocated["logical_steps"][0]["delegation"]["actual_assignee_ref"] = "pa-1"
    with pytest.raises(PlanCandidateStageError):
        parse_plan_candidate(json.dumps(allocated))


def test_s5_valid_plan_compiles_provider_free_stable_delegate_identity():
    intent, context, snapshot, plan = _delegate_plan()
    validation = validate_agent_plan(
        agent_plan=plan,
        work_intent=intent,
        agent_context=context,
        capability_snapshot=snapshot,
        validation_result_id=VALIDATION_ID,
        validated_at=NOW,
    )
    assert validation["status"] == "VALID"

    first_ids = iter((STEP_ID, EXECUTABLE_PLAN_ID))
    first = compile_executable_plan(
        agent_plan=plan,
        validation_result=validation,
        agent_context=context,
        capability_snapshot=snapshot,
        compiled_at=NOW,
        id_factory=lambda: next(first_ids),
    )
    other_ids = iter(
        (
            "99999999-9999-4999-8999-999999999995",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5",
        )
    )
    second = compile_executable_plan(
        agent_plan=plan,
        validation_result=validation,
        agent_context=context,
        capability_snapshot=snapshot,
        compiled_at=NOW,
        id_factory=lambda: next(other_ids),
    )

    step = first["steps"][0]
    assert first["schema_version"] == "1.3"
    assert first["compiler_version"] == "p7.1"
    assert (step["step_type"], step["executor_kind"]) == (
        "DELEGATE_WORK",
        "WC_DELEGATE_WORK",
    )
    assert step["delegation"] == second["steps"][0]["delegation"]
    assert "actual_assignee_ref" not in step["delegation"]

    changed_context = copy.deepcopy(context)
    changed_context["project_ref"]["resource_id"] = "another-project"
    changed_context["context_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in changed_context.items()
            if key != "context_hash"
        }
    )
    changed_plan = copy.deepcopy(plan)
    changed_plan["agent_context_ref"]["hash"] = changed_context["context_hash"]
    changed_plan["plan_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in changed_plan.items() if key != "plan_hash"}
    )
    rejected = validate_agent_plan(
        agent_plan=changed_plan,
        work_intent=intent,
        agent_context=changed_context,
        capability_snapshot=snapshot,
        validation_result_id=VALIDATION_ID,
        validated_at=NOW,
    )
    assert rejected["status"] == "INVALID_TERMINAL"
    assert rejected["issues"][0]["code"] == "DELEGATION_PROJECT_SCOPE_MISMATCH"


def _runtime(compiled):
    return {
        "tenant_id": TENANT,
        "agent_execution_id": EXECUTION_ID,
        "executable_plan_id": compiled["executable_plan_id"],
        "executable_step_id": compiled["steps"][0]["executable_step_id"],
        "agent_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb5",
        "agent_type": "IA",
        "requester_ref": "user-p7-s5",
        "correlation_id": "corr-p7-s5",
        "causation_id": "cause-p7-s5",
        "delegation": compiled["steps"][0]["delegation"],
    }


class _RuntimeRepository:
    def __init__(self, runtime, calls):
        self.runtime = runtime
        self.calls = calls

    def load(self, **kwargs):
        self.calls.append("runtime")
        assert kwargs["tenant_id"] == TENANT
        return self.runtime


class _WaitRepository:
    def __init__(self, calls):
        self.calls = calls
        self.saved = None

    def register(self, **record):
        self.calls.append("wait")
        self.saved = {
            **record,
            "wait_type": "WORK_RESULT",
            "state": "PENDING",
            "version": 1,
            "satisfied_at": None,
        }
        return self.saved


class _WorkItems:
    def __init__(self, calls, *, mismatch=False):
        self.calls = calls
        self.mismatch = mismatch
        self.payload = None

    def create_work_item(self, payload):
        self.calls.append("wc")
        self.payload = payload
        return {
            "created": True,
            "work_item": {
                "tenant_id": TENANT,
                "work_item_id": (
                    "cccccccc-cccc-4ccc-8ccc-ccccccccccc5"
                    if self.mismatch
                    else payload["work_item_id"]
                ),
                "state": "CREATED",
            },
        }


def test_s5_executor_persists_wait_before_idempotent_wc_creation():
    _, context, snapshot, plan = _delegate_plan()
    validation = validate_agent_plan(
        agent_plan=plan,
        work_intent=_intent(),
        agent_context=context,
        capability_snapshot=snapshot,
        validation_result_id=VALIDATION_ID,
        validated_at=NOW,
    )
    ids = iter((STEP_ID, EXECUTABLE_PLAN_ID))
    compiled = compile_executable_plan(
        agent_plan=plan,
        validation_result=validation,
        agent_context=context,
        capability_snapshot=snapshot,
        compiled_at=NOW,
        id_factory=lambda: next(ids),
    )
    calls = []
    wait = _WaitRepository(calls)
    work_items = _WorkItems(calls)
    executor = P7DelegateWorkExecutor(
        dependencies=DelegateWorkExecutorDependencies(
            runtime_repository=_RuntimeRepository(_runtime(compiled), calls),
            wait_repository=wait,
            work_item_client=work_items,
        ),
        clock=lambda: datetime(2026, 10, 18, 10, 0, tzinfo=UTC),
    )
    context_record = StepExecutionContext(
        job={"tenant_id": TENANT},
        attempt={},
        step={
            **compiled["steps"][0],
            "agent_execution_id": EXECUTION_ID,
            "executable_plan_id": EXECUTABLE_PLAN_ID,
        },
        dependency_results=(),
        existing_result=None,
    )

    outcome = executor.execute(context_record)

    assert calls == ["runtime", "wait", "wc"]
    assert outcome.state == "WAITING"
    assert outcome.wait_id == wait.saved["wait_id"]
    assert outcome.wait_external_ref == work_items.payload["work_item_id"]
    assert work_items.payload["delegation_spec"]["parent_executable_step_id"] == STEP_ID
    assert work_items.payload["requester"]["entity_type"] == "AGENT"
    assert work_items.payload["accountable_owner"]["entity_type"] == "USER"

    mismatch = P7DelegateWorkExecutor(
        dependencies=DelegateWorkExecutorDependencies(
            runtime_repository=_RuntimeRepository(_runtime(compiled), []),
            wait_repository=_WaitRepository([]),
            work_item_client=_WorkItems([], mismatch=True),
        )
    )
    with pytest.raises(P5StepExecutorError, match="mismatched"):
        mismatch.execute(context_record)


def test_s5_wait_repository_is_restart_safe_and_conflict_detecting():
    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE ae_wait_registration ("
                "wait_id TEXT NOT NULL, tenant_id TEXT NOT NULL, "
                "agent_execution_id TEXT NOT NULL, executable_step_id TEXT NOT NULL, "
                "wait_type TEXT NOT NULL, external_ref TEXT NOT NULL, "
                "result_contract_ref TEXT NOT NULL, state TEXT NOT NULL, "
                "version INTEGER NOT NULL, created_at TEXT NOT NULL, satisfied_at TEXT, "
                "PRIMARY KEY (tenant_id, wait_id), "
                "UNIQUE (tenant_id, agent_execution_id, executable_step_id, wait_type))"
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repository = SqlAlchemyWaitRegistrationRepository(factory)
    dispatch = delegation_dispatch(
        {
            **_runtime(
                {
                    "executable_plan_id": EXECUTABLE_PLAN_ID,
                    "steps": [
                        {
                            "executable_step_id": STEP_ID,
                            "delegation": _delegate_plan()[3]["steps"][0][
                                "delegation"
                            ],
                        }
                    ],
                }
            ),
            "delegation": compile_executable_plan(
                agent_plan=_delegate_plan()[3],
                validation_result=validate_agent_plan(
                    agent_plan=_delegate_plan()[3],
                    work_intent=_delegate_plan()[0],
                    agent_context=_delegate_plan()[1],
                    capability_snapshot=_delegate_plan()[2],
                    validation_result_id=VALIDATION_ID,
                    validated_at=NOW,
                ),
                agent_context=_delegate_plan()[1],
                capability_snapshot=_delegate_plan()[2],
                executable_plan_id=EXECUTABLE_PLAN_ID,
                compiled_at=NOW,
                id_factory=lambda: STEP_ID,
            )["steps"][0]["delegation"],
        },
        created_at=NOW,
    )
    first = repository.register(**dispatch["wait"])
    assert repository.register(**dispatch["wait"]) == first
    retried = repository.register(
        **{**dispatch["wait"], "created_at": "2026-10-18T10:05:00Z"}
    )
    assert retried == first
    assert (
        SqlAlchemyWaitRegistrationRepository(factory).get(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            executable_step_id=STEP_ID,
        )
        == first
    )
    conflict = {**dispatch["wait"], "result_contract_ref": "urn:changed"}
    with pytest.raises(DelegatedWorkError) as exc_info:
        repository.register(**conflict)
    assert exc_info.value.error_code == "ae.wait_registration_immutable_conflict"


def test_s5_runtime_repository_requires_exact_active_compiled_lineage():
    _, context, snapshot, plan = _delegate_plan()
    validation = validate_agent_plan(
        agent_plan=plan,
        work_intent=_intent(),
        agent_context=context,
        capability_snapshot=snapshot,
        validation_result_id=VALIDATION_ID,
        validated_at=NOW,
    )
    ids = iter((STEP_ID, EXECUTABLE_PLAN_ID))
    compiled = compile_executable_plan(
        agent_plan=plan,
        validation_result=validation,
        agent_context=context,
        capability_snapshot=snapshot,
        compiled_at=NOW,
        id_factory=lambda: next(ids),
    )
    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ae_agent_execution (
                tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                agent_id TEXT NOT NULL, agent_type TEXT NOT NULL,
                principal_id TEXT NOT NULL, requester_ref TEXT,
                correlation_id TEXT NOT NULL, causation_id TEXT,
                state TEXT NOT NULL, phase TEXT NOT NULL,
                PRIMARY KEY (tenant_id, agent_execution_id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_executable_plan (
                tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                executable_plan_id TEXT NOT NULL, plan_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, executable_plan_id)
            )
        """))
        connection.execute(
            text(
                "INSERT INTO ae_agent_execution VALUES "
                "(:tenant, :execution, 'agent-s5', 'IA', 'principal-s5', NULL, "
                "'corr-s5', NULL, 'RUNNING', 'STEP_EXECUTION')"
            ),
            {"tenant": TENANT, "execution": EXECUTION_ID},
        )
        connection.execute(
            text("INSERT INTO ae_executable_plan VALUES (:tenant, :execution, :plan, :body)"),
            {
                "tenant": TENANT,
                "execution": EXECUTION_ID,
                "plan": EXECUTABLE_PLAN_ID,
                "body": json.dumps(compiled),
            },
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repository = SqlAlchemyDelegationRuntimeRepository(factory)

    loaded = repository.load(
        tenant_id=TENANT,
        agent_execution_id=EXECUTION_ID,
        executable_plan_id=EXECUTABLE_PLAN_ID,
        executable_step_id=STEP_ID,
    )
    assert loaded["requester_ref"] == "principal-s5"
    assert loaded["causation_id"] is None
    assert loaded["delegation"]["required_agent_type"] == "PA"

    mismatched = copy.deepcopy(compiled)
    mismatched["execution_id"] = "99999999-9999-4999-8999-999999999995"
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_executable_plan SET plan_json = :body"),
            {"body": json.dumps(mismatched)},
        )
    with pytest.raises(DelegatedWorkError, match="execution lineage"):
        repository.load(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            executable_plan_id=EXECUTABLE_PLAN_ID,
            executable_step_id=STEP_ID,
        )

    missing_step = {**compiled, "steps": []}
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_executable_plan SET plan_json = :body"),
            {"body": json.dumps(missing_step)},
        )
    with pytest.raises(DelegatedWorkError, match="compiled step lineage"):
        repository.load(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            executable_plan_id=EXECUTABLE_PLAN_ID,
            executable_step_id=STEP_ID,
        )

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_executable_plan SET plan_json = :body"),
            {"body": json.dumps(compiled)},
        )
        connection.execute(text("UPDATE ae_agent_execution SET state = 'WAITING_DEPENDENCY'"))
    with pytest.raises(DelegatedWorkError, match="active execution authority"):
        repository.load(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            executable_plan_id=EXECUTABLE_PLAN_ID,
            executable_step_id=STEP_ID,
        )

    with pytest.raises(DelegatedWorkError) as missing:
        repository.load(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            executable_plan_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5",
            executable_step_id=STEP_ID,
        )
    assert missing.value.error_code == "ae.delegate_runtime_not_found"


def test_s5_persistence_failures_and_wait_reload_fail_closed(monkeypatch):
    empty_engine = create_engine("sqlite+pysqlite://", future=True)
    factory = sessionmaker(bind=empty_engine, expire_on_commit=False)
    with pytest.raises(DelegatedWorkError) as runtime_error:
        SqlAlchemyDelegationRuntimeRepository(factory).load(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            executable_plan_id=EXECUTABLE_PLAN_ID,
            executable_step_id=STEP_ID,
        )
    assert runtime_error.value.error_code == "ae.delegate_runtime_store_unavailable"
    with pytest.raises(DelegatedWorkError) as wait_error:
        SqlAlchemyWaitRegistrationRepository(factory).get(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            executable_step_id=STEP_ID,
        )
    assert wait_error.value.error_code == "ae.wait_registration_store_unavailable"
    with pytest.raises(DelegatedWorkError) as wait_write_error:
        SqlAlchemyWaitRegistrationRepository(factory).register(
            wait_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5",
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            executable_step_id=STEP_ID,
            external_ref="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb5",
            result_contract_ref="urn:nex:result:test:1",
            created_at=NOW,
        )
    assert wait_write_error.value.error_code == "ae.wait_registration_store_unavailable"

    engine = create_engine("sqlite+pysqlite://", future=True)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE ae_wait_registration (wait_id TEXT, tenant_id TEXT, "
            "agent_execution_id TEXT, executable_step_id TEXT, wait_type TEXT, "
            "external_ref TEXT, result_contract_ref TEXT, state TEXT, "
            "version INTEGER, created_at TEXT, satisfied_at TEXT, "
            "UNIQUE (tenant_id, agent_execution_id, executable_step_id, wait_type))"
        ))
    repository = SqlAlchemyWaitRegistrationRepository(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    assert repository.get(
        tenant_id=TENANT,
        agent_execution_id=EXECUTION_ID,
        executable_step_id=STEP_ID,
    ) is None
    monkeypatch.setattr(delegated_work_module, "_load_wait", lambda *_args, **_kwargs: None)
    with pytest.raises(DelegatedWorkError) as reload_error:
        repository.register(
            wait_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5",
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
            executable_step_id=STEP_ID,
            external_ref="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb5",
            result_contract_ref="urn:nex:result:test:1",
            created_at=NOW,
        )
    assert reload_error.value.error_code == "ae.wait_registration_write_conflict"
    assert reload_error.value.retryable is True


class _HttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def test_s5_wc_http_client_success_and_failure_semantics(monkeypatch):
    client = HttpWcWorkItemClient(
        base_url="http://wc.local/", service_token="signed-token", timeout_seconds=9
    )
    captured = {}

    def success(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _HttpResponse(b'{"work_item":{"work_item_id":"item-1"}}')

    monkeypatch.setattr(delegated_work_module, "urlopen", success)
    result = client.create_work_item({"work_item_id": "item-1"})
    assert result["work_item"]["work_item_id"] == "item-1"
    assert captured["request"].full_url == "http://wc.local/api/v1/work-items"
    assert captured["request"].get_header("Authorization") == "Bearer signed-token"
    assert captured["timeout"] == 9

    with pytest.raises(DelegatedWorkError) as missing_token:
        HttpWcWorkItemClient(base_url="http://wc.local", service_token=" ").create_work_item({})
    assert missing_token.value.error_code == "ae.wc_service_token_missing"

    monkeypatch.setattr(
        delegated_work_module,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPError("http://wc.local", 503, "failed", None, None)
        ),
    )
    with pytest.raises(DelegatedWorkError) as http_error:
        client.create_work_item({})
    assert http_error.value.error_code == "ae.wc_work_item_http_failed"
    assert http_error.value.retryable is True

    monkeypatch.setattr(
        delegated_work_module,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")),
    )
    with pytest.raises(DelegatedWorkError) as unavailable:
        client.create_work_item({})
    assert unavailable.value.error_code == "ae.wc_work_item_unavailable"
    assert unavailable.value.retryable is True

    monkeypatch.setattr(
        delegated_work_module,
        "urlopen",
        lambda *_args, **_kwargs: _HttpResponse(b'{"unexpected":true}'),
    )
    with pytest.raises(DelegatedWorkError) as invalid:
        client.create_work_item({})
    assert invalid.value.error_code == "ae.delegate_work_invalid"


def test_s5_delegate_dependency_composition_fails_closed():
    with pytest.raises(P5StepExecutorError, match="dependencies"):
        validate_delegate_work_executor_dependencies(None)
    with pytest.raises(P5StepExecutorError, match="WC client"):
        validate_delegate_work_executor_dependencies(
            DelegateWorkExecutorDependencies(
                runtime_repository=_RuntimeRepository({}, []),
                wait_repository=_WaitRepository([]),
                work_item_client=object(),
            )
        )
