from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from nex_ae_api.agent_execution import (
    AgentExecutionError,
    _validate_claimed_planning_source,
)
from nex_ae_api.agent_plans import AgentPlanError, _validate_delegation
from nex_ae_api.background_planning import (
    BackgroundPlanningError,
    _require_execution_source,
)
from nex_ae_api.delegated_work import delegation_dispatch
from nex_ae_api.executable_plans import (
    ExecutablePlanError,
    _compile_delegation,
    validate_compiled_delegation,
)
from nex_ae_api.intent_policy import resolve_validated_intent_candidate
from nex_ae_api.plan_candidate_generation import (
    PlanCandidateStageError,
    _candidate_delegation,
    _delegation_with_business_context,
)
from nex_ae_api.work_intent import (
    WorkIntentError,
    _validate_business_work_intent,
    build_work_intent_from_claimed_work,
)
from nex_ae_api.work_intent import (
    _claimed_planning_source as _work_intent_claimed_planning_source,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc.coordination import RoutingPolicy, _planning_source
from nex_wc.work_items import (
    InMemoryWorkItemRepository,
    WorkItemError,
    WorkItemService,
    validate_delegation_spec,
)

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_EXAMPLE = (
    ROOT
    / "contracts"
    / "examples"
    / "service"
    / "ae_work_intent.business_transaction.v1_2.json"
)
MIGRATION = (
    ROOT
    / "database"
    / "nex-ae-api"
    / "migrations"
    / "2516_ae_m1_work_intent.sql"
)

TENANT = "VO00"
PROJECT_ID = "77777777-7777-4777-8777-777777777777"
IA_AGENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3"
OWNER = "employee-100"
EXECUTION_ID = "33333333-3333-4333-8333-333333333333"
PLAN_ID = "55555555-5555-4555-8555-555555555555"
STEP_ID = "66666666-6666-4666-8666-666666666666"
NOW_DT = datetime(2026, 11, 16, 6, 0, tzinfo=UTC)
NOW = "2026-11-16T06:00:00Z"


class _Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate"],
            "revision_hash": "f" * 64,
        }


def _context() -> dict:
    return json.loads(CONTEXT_EXAMPLE.read_text(encoding="utf-8"))[
        "business_request_context"
    ]


def _compiled_delegation(context: dict | None = None) -> dict:
    selected = context or _context()
    return _compile_delegation(
        {
            "step_id": "S1",
            "objective": "Prepare the admitted Project transaction.",
            "required_capability": "FINANCE.VOUCHER.APPROVE_AND_POST",
            "delegation": {
                "work_class": "BUSINESS_TRANSACTION",
                "required_agent_type": "PA",
                "project_scope_ref": PROJECT_ID,
                "result_contract_ref": (
                    "contract://nex/mybee/finance/journal-posting-result/v1"
                ),
                "completion_policy": "OWNER_SUBMITS",
                "business_request_context": selected,
                "business_context_hash": selected["context_hash"],
            },
        },
        execution_id=EXECUTION_ID,
        agent_plan_version=1,
    )


def _dispatch(context: dict | None = None) -> dict:
    return delegation_dispatch(
        {
            "tenant_id": TENANT,
            "agent_execution_id": EXECUTION_ID,
            "executable_plan_id": PLAN_ID,
            "executable_step_id": STEP_ID,
            "agent_id": IA_AGENT_ID,
            "requester_ref": OWNER,
            "correlation_id": EXECUTION_ID,
            "delegation": _compiled_delegation(context),
        },
        created_at=NOW,
    )


def _service(repository: InMemoryWorkItemRepository) -> WorkItemService:
    return WorkItemService(
        repository,
        authorization_source=_Authorization(),
        clock=lambda: NOW_DT,
    )


def _claimed_source() -> dict:
    repository = InMemoryWorkItemRepository()
    created = _service(repository).create(_dispatch()["work_item_request"])
    stored = repository.get(
        tenant_id=TENANT,
        work_item_id=created["work_item"]["work_item_id"],
    )
    assert stored is not None
    return _planning_source(stored["work_item"], stored["delegation_spec"])


def _agent_plan_delegation() -> dict:
    context = _context()
    return {
        "work_class": "BUSINESS_TRANSACTION",
        "required_agent_type": "PA",
        "project_scope_ref": PROJECT_ID,
        "result_contract_ref": (
            "contract://nex/mybee/finance/journal-posting-result/v1"
        ),
        "completion_policy": "OWNER_SUBMITS",
        "business_request_context": context,
        "business_context_hash": context["context_hash"],
    }


def test_01b3_exact_context_crosses_compile_wc_claim_and_pa_work_intent() -> None:
    context = _context()
    compiled = validate_compiled_delegation(_compiled_delegation(context))
    assert compiled["schema_version"] == "1.2"
    assert compiled["business_request_context"] == context

    dispatched = _dispatch(context)
    repository = InMemoryWorkItemRepository()
    created = _service(repository).create(dispatched["work_item_request"])
    assert created["created"] is True
    stored = repository.get(tenant_id=TENANT, work_item_id=created["work_item"]["work_item_id"])
    assert stored is not None
    assert stored["delegation_spec"]["business_request_context"] == context

    source = _planning_source(stored["work_item"], stored["delegation_spec"])
    assert source["schema_version"] == "p7.claimed_work_planning_source.v2"
    assert source["delegation_identity"] == {
        "delegation_id": stored["delegation_spec"]["delegation_id"],
        "delegation_revision": 1,
        "requester_ref": OWNER,
        "parent_agent_execution_id": EXECUTION_ID,
    }
    assert source["business_request_context"] == context
    assert source["business_context_hash"] == context["context_hash"]

    decision = resolve_validated_intent_candidate(
        {
            "intent_label": "provider_selected_untrusted_label",
            "suggested_execution_mode": "GENERAL_ANSWER",
            "confidence": 0.96,
        }
    )
    background = build_work_intent_from_claimed_work(
        execution_id=str(uuid4()),
        actor_ref=f"OA:SUBJECT:{OWNER}",
        received_at=NOW,
        planning_source=source,
        intent_decision=decision,
        input_context_hash="sha256:" + "9" * 64,
        work_intent_id=str(uuid4()),
    )
    assert background["schema_version"] == "1.2"
    assert background["source"]["source_type"] == "CLAIMED_WORKITEM"
    assert background["intent_label"] == "FINANCE.VOUCHER.APPROVE_AND_POST"
    assert background["business_request_context"] == context
    assert background["business_context_hash"] == context["context_hash"]


def test_01b3_same_context_replays_and_changed_context_conflicts() -> None:
    repository = InMemoryWorkItemRepository()
    service = _service(repository)
    request = _dispatch()["work_item_request"]
    first = service.create(request)
    replay = service.create(copy.deepcopy(request))
    assert first["created"] is True
    assert replay == {"work_item": first["work_item"], "created": False}

    changed = _context()
    changed["transaction"]["amount"] = "2451.00"
    changed["context_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in changed.items() if key != "context_hash"}
    )
    changed_request = _dispatch(changed)["work_item_request"]
    with pytest.raises(WorkItemError) as conflict:
        service.create(changed_request)
    assert conflict.value.error_code == "wc.work_item_idempotency_conflict"
    assert conflict.value.status_code == 409


def test_01b3_product_project_agent_profile_is_admitted_for_m1_routing() -> None:
    policy = RoutingPolicy()

    assert policy.profile_is_admitted(
        "FINANCE.VOUCHER.APPROVE_AND_POST",
        "agent-profile://nex-platform/project-agent/v1",
    )
    assert not policy.profile_is_admitted(
        "FINANCE.VOUCHER.APPROVE_AND_POST",
        "agent-profile://pa/project-budget-read/v1",
    )


def test_01b3_migration_admits_work_intent_v12_business_transaction() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "BUSINESS_TRANSACTION" in sql
    assert "intent_json ->> 'schema_version' IN ('1.1', '1.2')" in sql
    assert "2516_ae_m1_work_intent" in sql
    assert "CREATE TABLE" not in sql


@pytest.mark.parametrize(
    "mutation",
    (
        lambda spec: spec.pop("business_request_context"),
        lambda spec: spec.update(business_context_hash="sha256:" + "0" * 64),
        lambda spec: spec.update(required_capability="FINANCE.PROJECT.GET"),
    ),
)
def test_01b3_delegation_v12_fails_closed_for_missing_tampered_or_wrong_profile(
    mutation,
) -> None:
    spec = _dispatch()["work_item_request"]["delegation_spec"]
    mutation(spec)
    with pytest.raises(WorkItemError):
        validate_delegation_spec(spec)


def test_01b3_m1_legacy_source_and_requester_drift_fail_closed() -> None:
    context = _context()
    legacy = {
        "schema_version": "p7.claimed_work_planning_source.v1",
        "source_type": "CLAIMED_WORKITEM",
        "source_ref": str(uuid4()),
        "goal": "Prepare the admitted transaction.",
        "work_class": "BUSINESS_TRANSACTION",
        "required_capability": "FINANCE.VOUCHER.APPROVE_AND_POST",
        "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT_ID},
        "artifact_refs": [],
        "evidence_refs": [],
        "completion_policy": "OWNER_SUBMITS",
        "result_contract_ref": (
            "contract://nex/mybee/finance/journal-posting-result/v1"
        ),
    }
    decision = resolve_validated_intent_candidate(
        {
            "intent_label": "FINANCE.VOUCHER.APPROVE_AND_POST",
            "suggested_execution_mode": "GENERAL_ANSWER",
            "confidence": 0.9,
        }
    )
    with pytest.raises(WorkIntentError, match="planning source v2"):
        build_work_intent_from_claimed_work(
            execution_id=str(uuid4()),
            actor_ref=f"OA:SUBJECT:{OWNER}",
            received_at=NOW,
            planning_source=legacy,
            intent_decision=decision,
            input_context_hash="sha256:" + "8" * 64,
            work_intent_id=str(uuid4()),
        )

    source = {
        **legacy,
        "schema_version": "p7.claimed_work_planning_source.v2",
        "delegation_identity": {
            "delegation_id": "m1-delegation",
            "delegation_revision": 1,
            "requester_ref": OWNER,
            "parent_agent_execution_id": EXECUTION_ID,
        },
        "business_request_context": context,
        "business_context_hash": context["context_hash"],
    }
    execution = {
        "source_type": "CLAIMED_WORKITEM",
        "agent_type": "PA",
        "work_item_ref": source["source_ref"],
        "project_id": PROJECT_ID,
        "requester_ref": "different-owner",
    }
    with pytest.raises(BackgroundPlanningError) as conflict:
        _require_execution_source(execution, source)
    assert conflict.value.error_code == "ae.background_planning_lineage_conflict"


def test_01b3_legacy_non_m1_delegation_and_planning_source_remain_valid() -> None:
    compiled = {
        **_compiled_delegation(),
        "schema_version": "1.0",
    }
    compiled.pop("business_request_context")
    compiled.pop("business_context_hash")
    compiled.update(
        {
            "work_class": "ANALYSIS",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "result_contract_ref": "urn:nex:result:budget:1",
        }
    )
    assert validate_compiled_delegation(compiled)["schema_version"] == "1.0"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("work_class", "UNKNOWN"),
        ("required_agent_type", "IA"),
        ("project_scope_ref", ""),
        ("result_contract_ref", "contract://wrong"),
        ("completion_policy", "UNKNOWN"),
        ("business_context_hash", "sha256:" + "0" * 64),
    ),
)
def test_01b3_agent_plan_delegation_rejects_profile_and_lineage_drift(
    field: str,
    value: str,
) -> None:
    delegation = _agent_plan_delegation()
    delegation[field] = value

    with pytest.raises(AgentPlanError):
        _validate_delegation(
            delegation,
            "contract://nex/mybee/finance/journal-posting-result/v1",
            "FINANCE.VOUCHER.APPROVE_AND_POST",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("work_class", "ANALYSIS"),
        ("required_agent_type", "CA"),
        ("required_capability", "FINANCE.PROJECT.GET"),
        ("business_context_hash", "sha256:" + "0" * 64),
    ),
)
def test_01b3_compiled_delegation_rejects_business_profile_drift(
    field: str,
    value: str,
) -> None:
    delegation = _compiled_delegation()
    delegation[field] = value

    with pytest.raises(
        ExecutablePlanError,
        match="business delegation profile|context hash",
    ):
        validate_compiled_delegation(delegation)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda source: source.update(work_class="ANALYSIS"),
        lambda source: source["delegation_identity"].update(
            delegation_revision=True
        ),
        lambda source: source["delegation_identity"].pop("requester_ref"),
        lambda source: source.update(business_context_hash="sha256:" + "0" * 64),
        lambda source: source.update(project_ref={"entity_type": "TENANT"}),
        lambda source: source.update(artifact_refs="not-a-list"),
    ),
)
def test_01b3_execution_planning_source_rejects_malformed_lineage(mutation) -> None:
    source = _claimed_source()
    mutation(source)

    with pytest.raises(AgentExecutionError):
        _validate_claimed_planning_source(source)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda record: record.update(intent_label="FINANCE.PROJECT.GET"),
        lambda record: record.update(business_context_hash="sha256:" + "0" * 64),
        lambda record: record["source"].update(source_ref="different-prompt"),
        lambda record: record["provenance"].update(
            input_context_hash="sha256:" + "0" * 64
        ),
        lambda record: (
            record["source"].update(source_type="CLAIMED_WORKITEM"),
            record.update(project_ref=None),
        ),
    ),
)
def test_01b3_business_work_intent_rejects_profile_provenance_and_authority_drift(
    mutation,
) -> None:
    context = _context()
    record = {
        "intent_label": "FINANCE.VOUCHER.APPROVE_AND_POST",
        "work_class": "BUSINESS_TRANSACTION",
        "required_capability_hints": ["FINANCE.VOUCHER.APPROVE_AND_POST"],
        "business_request_context": context,
        "business_context_hash": context["context_hash"],
        "source": {
            "source_type": "PROMPT",
            "source_ref": context["source_prompt_ref"],
        },
        "provenance": dict(context["candidate_provenance"]),
        "project_ref": {"resource_id": PROJECT_ID},
    }
    mutation(record)

    with pytest.raises(WorkIntentError):
        _validate_business_work_intent(record)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("work_class", "UNKNOWN"),
        ("required_agent_type", "IA"),
        ("completion_policy", "UNKNOWN"),
    ),
)
def test_01b3_plan_candidate_rejects_invalid_delegation_enums(
    field: str,
    value: str,
) -> None:
    delegation = _agent_plan_delegation()
    delegation.pop("business_request_context")
    delegation.pop("business_context_hash")
    delegation[field] = value

    with pytest.raises(PlanCandidateStageError):
        _candidate_delegation(delegation)


def test_01b3_plan_candidate_business_context_binding_fails_closed() -> None:
    metadata = _agent_plan_delegation()
    metadata.pop("business_request_context")
    metadata.pop("business_context_hash")
    context = _context()

    assert _delegation_with_business_context(
        metadata,
        required_capability="FINANCE.PROJECT.GET",
        work_intent={},
    ) == metadata
    with pytest.raises(PlanCandidateStageError, match="WorkIntent v1.2"):
        _delegation_with_business_context(
            metadata,
            required_capability="FINANCE.VOUCHER.APPROVE_AND_POST",
            work_intent={"schema_version": "1.1"},
        )
    with pytest.raises(PlanCandidateStageError, match="fields are invalid"):
        _delegation_with_business_context(
            metadata,
            required_capability="FINANCE.VOUCHER.APPROVE_AND_POST",
            work_intent={
                "schema_version": "1.2",
                "business_request_context": {},
            },
        )
    with pytest.raises(PlanCandidateStageError, match="hash is inconsistent"):
        _delegation_with_business_context(
            metadata,
            required_capability="FINANCE.VOUCHER.APPROVE_AND_POST",
            work_intent={
                "schema_version": "1.2",
                "business_request_context": context,
                "business_context_hash": "sha256:" + "0" * 64,
            },
        )


def test_01b3_ae_and_work_intent_planning_source_validators_close_v2_edges() -> None:
    source = _claimed_source()
    assert (
        _validate_claimed_planning_source(source)["business_request_context"]
        == _context()
    )

    malformed_context = copy.deepcopy(source)
    malformed_context["business_request_context"].pop("transaction")
    with pytest.raises(AgentExecutionError):
        _validate_claimed_planning_source(malformed_context)

    for mutation in (
        lambda value: value.update(work_class="ANALYSIS"),
        lambda value: value.update(business_context_hash="sha256:" + "0" * 64),
        lambda value: value["delegation_identity"].pop("requester_ref"),
        lambda value: value["business_request_context"].pop("transaction"),
    ):
        malformed = copy.deepcopy(source)
        mutation(malformed)
        with pytest.raises(WorkIntentError):
            _work_intent_claimed_planning_source(malformed)

    with pytest.raises(WorkIntentError):
        _work_intent_claimed_planning_source(None)  # type: ignore[arg-type]
