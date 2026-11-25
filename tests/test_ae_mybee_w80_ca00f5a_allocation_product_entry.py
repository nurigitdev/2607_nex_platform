from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from nex_ae_api.accounting_allocation_authority import (
    ACCOUNTING_ALLOCATION_OPERATION,
    validate_accounting_allocation_work_intent,
)
from nex_ae_api.accounting_allocation_intent_activation import (
    ACCOUNTING_ALLOCATION_BINDING_FIELD,
    AccountingAllocationIntentActivationError,
    AccountingAllocationIntentActivator,
)
from nex_ae_api.accounting_allocation_product_coordinator import (
    ACCOUNTING_ALLOCATION_COORDINATOR_ID,
    ACCOUNTING_ALLOCATION_READY_STATE,
    AccountingAllocationProductCoordinatorError,
    InstalledAccountingAllocationProductCoordinator,
    InstalledAccountingAllocationProductPlanActivation,
    build_accounting_allocation_activation_documents,
    build_accounting_allocation_product_coordinator_registration,
    load_accounting_allocation_coordinator_activation,
)
from nex_ae_api.agent_context import build_agent_context
from nex_ae_api.m1_installed_skill_runtime import M1InstalledSkillRuntime
from nex_ae_api.planning_capabilities import build_capability_snapshot
from nex_ae_api.product_capabilities import load_product_capability_registry
from nex_ae_api.product_capability_retirements import (
    ProductCapabilityRetirementProjection,
)
from nex_ae_api.product_controlled_skill import (
    ProductControlledSkillError,
    _oa_revision_hash_ref,
)
from nex_ae_api.product_domain_intent_activators import (
    build_active_product_domain_intent_activator_registry,
)
from nex_ae_api.product_planning_coordinators import (
    ProductPlanningCoordinatorRegistry,
)
from nex_ae_api.product_planning_runtime import (
    InstalledProductCoordinatorRuntime,
    InstalledProductCoordinatorRuntimeRegistry,
    ProductPlanningRuntimeError,
    PublicProductPlanningRouter,
    build_installed_accounting_allocation_coordinator_runtime,
)
from nex_ae_api.work_intent import validate_work_intent
from nex_runtime import psycopg_database_url
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from test_ae_mybee_w70_cp_m1_e2e_fx_01b5_plan_materialization import (
    _agent_context as _persisted_agent_context,
)
from test_ae_mybee_w70_cp_m1_e2e_fx_01b6b4_postgres import _seed_lineage
from test_ae_mybee_w80_ca00f5_split_journeys import (
    _catalog,
)
from test_ae_mybee_w80_ca00f5_split_journeys import (
    _snapshot as _installed_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
TENANT = "VO00"
SUBJECT = "employee-590"
EXECUTION = "59000000-0000-4000-8000-000000000001"
WORK_INTENT = "59000000-0000-4000-8000-000000000002"
COMPANY = "59000000-0000-4000-8000-000000000003"
JOURNAL = "59000000-0000-4000-8000-000000000004"
CONTEXT = "59000000-0000-4000-8000-000000000005"
AGENT = "59000000-0000-4000-8000-000000000006"
SNAPSHOT = "59000000-0000-4000-8000-000000000007"
WORKSPACE = "59000000-0000-4000-8000-000000000008"
CONVERSATION = "59000000-0000-4000-8000-000000000009"
INTERACTION = "59000000-0000-4000-8000-000000000010"
NOW = "2026-11-25T02:00:00Z"
DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_AE_MYBEE_W80_CA00F5_POSTGRES_SMOKE") == "1"


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("a" * 64, "sha256:" + "a" * 64),
        ("B" * 64, "sha256:" + "b" * 64),
        ("sha256:" + "c" * 64, "sha256:" + "c" * 64),
    ),
)
def test_oa_revision_digest_is_normalized_to_platform_hash_ref(
    value: str, expected: str
) -> None:
    assert _oa_revision_hash_ref(value) == expected


@pytest.mark.parametrize("value", (None, "", " sha256:" + "a" * 64, "not-a-hash"))
def test_invalid_oa_revision_digest_fails_closed(value: object) -> None:
    with pytest.raises(ProductControlledSkillError, match="revision is invalid"):
        _oa_revision_hash_ref(value)


def _capabilities():
    return load_product_capability_registry(
        {
            "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
                ROOT / "deployment/environments/"
                "ae-product-capability-registry.mybee-m1.v5.json"
            )
        }
    )


def test_ca00f5a_installed_activator_identity_is_bounded_and_deterministic():
    capabilities = _capabilities()
    kwargs = {
        "product_capability_registry": capabilities,
        "retirement_projection": ProductCapabilityRetirementProjection(),
        "session_factory": object(),
    }

    first = build_active_product_domain_intent_activator_registry({}, **kwargs)
    replay = build_active_product_domain_intent_activator_registry({}, **kwargs)
    registration = first.resolve(ACCOUNTING_ALLOCATION_OPERATION, required=True)

    assert registration is not None
    assert len(registration.source_identity) <= 256
    assert registration.source_identity.startswith(
        "nex-ae:accounting-allocation-domain-intent:v1:sha256:"
    )
    assert first.to_projection() == replay.to_projection()


def _candidate(*, ratios=("0.25", "0.75")) -> dict:
    values = [
        ("company_id", COMPANY),
        ("journal_id", JOURNAL),
        ("source_record_line_ref", f"eos.posted-journal-line:{JOURNAL}:1"),
        ("source_kind", "SERVICE"),
        ("allocation_project_code_1", "VO00D260111"),
        ("allocation_ratio_1", ratios[0]),
        ("allocation_project_code_2", "VO00O260112"),
        ("allocation_ratio_2", ratios[1]),
    ]
    return {
        "schema_version": "p65.intent_candidate.v1",
        "intent_label": ACCOUNTING_ALLOCATION_OPERATION,
        "suggested_execution_mode": "GENERAL_ANSWER",
        "entity_selectors": [],
        "parameter_candidates": [
            {"name": name, "value": value, "confidence": 0.98} for name, value in values
        ],
        "clarification": {"required": False, "reasons": [], "questions": []},
        "confidence": 0.98,
    }


def _work_intent(*, subject: str = SUBJECT) -> dict:
    value = {
        "schema_version": "1.1",
        "work_intent_id": WORK_INTENT,
        "intent_revision": 1,
        "supersedes_work_intent_id": None,
        "execution_id": EXECUTION,
        "source": {
            "source_type": "PROMPT",
            "source_ref": "AE:INTERACTION:allocation-590",
            "actor_ref": f"OA:SUBJECT:{subject}",
            "received_at": NOW,
        },
        "execution_mode": "INTERACTIVE",
        "compatibility_execution_mode": "GENERAL_ANSWER",
        "project_ref": None,
        "intent_label": ACCOUNTING_ALLOCATION_OPERATION,
        "goal": "Answer the admitted user request.",
        "work_class": "QUERY",
        "required_capability_hints": ["AE.CHAT.COMPATIBILITY"],
        "entity_selectors": [],
        "parameter_candidates": [],
        "constraints": [],
        "completion_criteria": [
            {
                "criterion_id": "C1",
                "description": "A direct response is returned.",
                "required": True,
                "result_contract_ref": "contract://nex/ae/general-answer/v1",
            }
        ],
        "clarification": {"status": "NOT_REQUIRED", "reasons": [], "questions": []},
        "confidence": {
            "overall": 0.98,
            "intent": 0.98,
            "entities": None,
            "parameters": None,
        },
        "provenance": {},
    }
    value["intent_hash"] = semantic_sha256_hash_ref(value)
    return validate_work_intent(value)


def _activated():
    return AccountingAllocationIntentActivator().activate(
        candidate=_candidate(),
        work_intent=_work_intent(),
        tenant_id=TENANT,
        principal_id=SUBJECT,
        resolved_at=NOW,
    )


def _context(work_intent: dict) -> dict:
    return build_agent_context(
        tenant_id=TENANT,
        principal_id=SUBJECT,
        agent_id=AGENT,
        execution_id=EXECUTION,
        workspace_id=WORKSPACE,
        conversation_id=CONVERSATION,
        interaction_id=INTERACTION,
        work_intent=work_intent,
        runtime_policy_ref={
            "rule_id": "allocation-product-entry",
            "rule_version": "1.0.0",
            "rule_hash": "sha256:" + "a" * 64,
        },
        resolver=_activated().context_resolver,
        context_id=CONTEXT,
        built_at=NOW,
    )


def _snapshot() -> dict:
    capabilities = _capabilities()
    return build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id=SNAPSHOT,
        snapshot_version=1,
        created_at=NOW,
        capabilities=tuple(item.capability for item in capabilities.registrations),
    )


def test_ca00f5a_admits_generic_candidate_into_typed_hash_bound_work_intent():
    result = _activated()
    intent = result.work_intent
    allocation = validate_accounting_allocation_work_intent(
        intent[ACCOUNTING_ALLOCATION_BINDING_FIELD]
    )

    assert intent["intent_label"] == ACCOUNTING_ALLOCATION_OPERATION
    assert intent["required_capability_hints"] == [ACCOUNTING_ALLOCATION_OPERATION]
    assert allocation["tenant_id"] == TENANT
    assert allocation["company_id"] == COMPANY
    assert allocation["journal_id"] == JOURNAL
    assert allocation["publication"] == {
        "target": "IA_WORKSPACE",
        "target_ref": "AE:INTERACTION:allocation-590",
    }
    assert allocation["projects"] == [
        {"project_code": "VO00D260111", "allocation_ratio": "0.250000000000"},
        {"project_code": "VO00O260112", "allocation_ratio": "0.750000000000"},
    ]
    assert intent["intent_hash"] == semantic_sha256_hash_ref(
        {key: value for key, value in intent.items() if key != "intent_hash"}
    )


@pytest.mark.parametrize(
    ("mutate", "error_code"),
    [
        (
            lambda value: value["parameter_candidates"].pop(0),
            "ACCOUNTING_ALLOCATION_CLARIFICATION_REQUIRED",
        ),
        (
            lambda value: value["parameter_candidates"].pop(),
            "ACCOUNTING_ALLOCATION_CLARIFICATION_REQUIRED",
        ),
        (
            lambda value: value["parameter_candidates"].append(
                {
                    "name": "allocation_project_code_3",
                    "value": "VO00D260111",
                    "confidence": 0.98,
                }
            ),
            "ACCOUNTING_ALLOCATION_CLARIFICATION_REQUIRED",
        ),
        (
            lambda value: value["parameter_candidates"].__setitem__(
                5,
                {"name": "allocation_ratio_1", "value": "0.20", "confidence": 0.98},
            ),
            "ACCOUNTING_ALLOCATION_INTENT_INVALID",
        ),
    ],
)
def test_ca00f5a_fails_closed_for_incomplete_duplicate_or_unbalanced_candidates(
    mutate, error_code
):
    candidate = deepcopy(_candidate())
    mutate(candidate)
    with pytest.raises(AccountingAllocationIntentActivationError) as raised:
        AccountingAllocationIntentActivator().activate(
            candidate=candidate,
            work_intent=_work_intent(),
            tenant_id=TENANT,
            principal_id=SUBJECT,
            resolved_at=NOW,
        )
    assert raised.value.error_code == error_code


def test_ca00f5a_accepts_live_provider_numeric_ratio_candidates():
    candidate = _candidate(ratios=(0.4, 0.6))

    activated = AccountingAllocationIntentActivator().activate(
        candidate=candidate,
        work_intent=_work_intent(),
        tenant_id=TENANT,
        principal_id=SUBJECT,
        resolved_at=NOW,
    )

    assert activated.work_intent["accounting_allocation_work_intent"]["projects"] == [
        {"project_code": "VO00D260111", "allocation_ratio": "0.400000000000"},
        {"project_code": "VO00O260112", "allocation_ratio": "0.600000000000"},
    ]


@pytest.mark.parametrize(
    "parameter_candidates",
    [
        None,
        ["malformed"],
        [{"name": "unsupported", "value": "x", "confidence": 0.9}],
        [
            {"name": "company_id", "value": COMPANY, "confidence": 0.9},
            {"name": "company_id", "value": COMPANY, "confidence": 0.9},
        ],
        [{"name": "company_id", "value": " padded ", "confidence": 0.9}],
    ],
)
def test_ca00f5a_rejects_malformed_candidate_shapes(parameter_candidates):
    candidate = _candidate()
    candidate["parameter_candidates"] = parameter_candidates

    with pytest.raises(AccountingAllocationIntentActivationError) as raised:
        AccountingAllocationIntentActivator().activate(
            candidate=candidate,
            work_intent=_work_intent(),
            tenant_id=TENANT,
            principal_id=SUBJECT,
            resolved_at=NOW,
        )

    assert raised.value.error_code == "ACCOUNTING_ALLOCATION_INTENT_INVALID"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("company_id", "not-a-uuid"),
        ("company_id", "59000000-0000-4000-8000-0000000000AB"),
        ("allocation_ratio_1", "not-a-number"),
        ("allocation_ratio_1", "0"),
        ("allocation_ratio_1", True),
        ("allocation_project_code_2", "VO00D260111"),
    ],
)
def test_ca00f5a_rejects_invalid_typed_candidate_values(name, value):
    candidate = _candidate()
    for item in candidate["parameter_candidates"]:
        if item["name"] == name:
            item["value"] = value
            break

    with pytest.raises(AccountingAllocationIntentActivationError) as raised:
        AccountingAllocationIntentActivator().activate(
            candidate=candidate,
            work_intent=_work_intent(),
            tenant_id=TENANT,
            principal_id=SUBJECT,
            resolved_at=NOW,
        )

    assert str(raised.value)
    assert raised.value.error_code == "ACCOUNTING_ALLOCATION_INTENT_INVALID"


def test_ca00f5a_rejects_wrong_capability_and_noncontiguous_project_indexes():
    intent = _work_intent()
    intent["intent_label"] = "FINANCE.PROJECT_PNL.GET"
    with pytest.raises(AccountingAllocationIntentActivationError):
        AccountingAllocationIntentActivator().activate(
            candidate=_candidate(),
            work_intent=intent,
            tenant_id=TENANT,
            principal_id=SUBJECT,
            resolved_at=NOW,
        )

    candidate = _candidate()
    candidate["parameter_candidates"] = [
        item
        for item in candidate["parameter_candidates"]
        if not item["name"].endswith("_2")
    ]
    candidate["parameter_candidates"].extend(
        [
            {
                "name": "allocation_project_code_3",
                "value": "VO00O260113",
                "confidence": 0.9,
            },
            {"name": "allocation_ratio_3", "value": "0.75", "confidence": 0.9},
        ]
    )
    with pytest.raises(AccountingAllocationIntentActivationError) as raised:
        AccountingAllocationIntentActivator().activate(
            candidate=candidate,
            work_intent=_work_intent(),
            tenant_id=TENANT,
            principal_id=SUBJECT,
            resolved_at=NOW,
        )
    assert raised.value.error_code == "ACCOUNTING_ALLOCATION_CLARIFICATION_REQUIRED"


def test_ca00f5a_context_is_agent_scoped_and_does_not_cache_authority():
    activated = _activated()
    assert activated.context_resolver.resolve(None).authority_ref is None
    with pytest.raises(AccountingAllocationIntentActivationError) as mismatch:
        activated.context_resolver.resolve(
            SimpleNamespace(
                tenant_id="OTHER",
                principal_id=SUBJECT,
                agent_type="IA",
                source_type="IA_PROMPT",
            )
        )
    assert mismatch.value.error_code == "ACCOUNTING_ALLOCATION_CONTEXT_SCOPE_MISMATCH"

    with pytest.raises(AccountingAllocationIntentActivationError) as missing_project:
        activated.context_resolver.resolve(
            SimpleNamespace(
                tenant_id=TENANT,
                principal_id=SUBJECT,
                agent_type="PA",
                source_type="CLAIMED_WORKITEM",
            )
        )
    assert missing_project.value.error_code == "ACCOUNTING_ALLOCATION_INTENT_INVALID"


class _Checkpoints:
    def __init__(self):
        self.saved = None

    def append(self, checkpoint):
        self.saved = dict(checkpoint)
        return self.saved

    def latest(self, **_values):
        return self.saved


class _Activation:
    def __init__(self, registration):
        self.registration = registration
        self.calls = []

    def activate(self, **values):
        self.calls.append(values)
        return {"activation_hash": "sha256:" + "b" * 64}


def _coordinator(checkpoints=None):
    registration = build_accounting_allocation_product_coordinator_registration(
        product_capabilities=_capabilities(), activation_status="ACTIVE"
    )
    return registration, InstalledAccountingAllocationProductCoordinator(
        registration=registration,
        checkpoints=checkpoints or _Checkpoints(),
    )


def test_ca00f5a_ready_coordinator_activates_common_runtime_on_begin_and_replay():
    capabilities = _capabilities()
    registration = build_accounting_allocation_product_coordinator_registration(
        product_capabilities=capabilities,
        activation_status="ACTIVE",
    )
    registry = ProductPlanningCoordinatorRegistry(
        (registration,), registry_id="test-allocation", registry_version=1
    )
    checkpoints = _Checkpoints()
    coordinator = InstalledAccountingAllocationProductCoordinator(
        registration=registration,
        checkpoints=checkpoints,
    )
    activation = _Activation(registration)
    runtimes = InstalledProductCoordinatorRuntimeRegistry(
        registry,
        (
            InstalledProductCoordinatorRuntime(
                registration=registration,
                coordinator=coordinator,
                activation=activation,
                planning_source_types=("IA_PROMPT",),
            ),
        ),
    )
    router = PublicProductPlanningRouter(registry, runtimes)
    work_intent = dict(_activated().work_intent)
    context = _context(work_intent)
    execution = {"execution_id": EXECUTION}

    first = router.begin_if_registered(
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=_snapshot(),
        execution=execution,
        planning_source_type="IA_PROMPT",
    )
    replay = router.replay_if_registered(
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=_snapshot(),
        execution=execution,
        planning_source_type="IA_PROMPT",
    )

    assert first["stage"] == ACCOUNTING_ALLOCATION_READY_STATE
    assert first["ready"] is True
    assert replay["replayed"] is True
    assert len(activation.calls) == 2
    assert checkpoints.saved["coordinator_id"] == ACCOUNTING_ALLOCATION_COORDINATOR_ID


def test_ca00f5a_router_admits_allocation_only_from_its_installed_source_type():
    capabilities = _capabilities()
    registration = build_accounting_allocation_product_coordinator_registration(
        product_capabilities=capabilities,
        activation_status="ACTIVE",
    )
    registry = ProductPlanningCoordinatorRegistry(
        (registration,), registry_id="test-allocation-source", registry_version=1
    )
    coordinator = InstalledAccountingAllocationProductCoordinator(
        registration=registration,
        checkpoints=_Checkpoints(),
    )
    runtime = InstalledProductCoordinatorRuntime(
        registration=registration,
        coordinator=coordinator,
        activation=_Activation(registration),
        planning_source_types=("IA_PROMPT",),
    )
    router = PublicProductPlanningRouter(
        registry,
        InstalledProductCoordinatorRuntimeRegistry(registry, (runtime,)),
    )

    assert (
        router.resolve_registration(
            work_intent=_activated().work_intent,
            capability_snapshot=_snapshot(),
            planning_source_type="IA_PROMPT",
        )
        == registration
    )
    assert (
        router.resolve_registration(
            work_intent=_activated().work_intent,
            capability_snapshot=_snapshot(),
            planning_source_type="CLAIMED_WORKITEM",
        )
        is None
    )
    with pytest.raises(ProductPlanningRuntimeError) as raised:
        router.resolve_registration(
            work_intent=_activated().work_intent,
            capability_snapshot=_snapshot(),
            planning_source_type="UNKNOWN",
        )
    assert raised.value.error_code == "ae.product_planning_runtime_invalid"


def test_ca00f5a_coordinator_rejects_invalid_dependencies_and_plan_proposals():
    registration, coordinator = _coordinator()
    with pytest.raises(AccountingAllocationProductCoordinatorError):
        InstalledAccountingAllocationProductCoordinator(
            registration=replace(registration, coordinator_id="OTHER"),
            checkpoints=_Checkpoints(),
        )
    with pytest.raises(AccountingAllocationProductCoordinatorError) as proposal:
        coordinator.begin(
            work_intent=dict(_activated().work_intent),
            agent_context=_context(dict(_activated().work_intent)),
            capability_snapshot=_snapshot(),
            execution={"execution_id": EXECUTION},
            planning_proposal={"unexpected": True},
        )
    assert str(proposal.value)


def test_ca00f5a_coordinator_fails_closed_for_replay_drift_and_lineage_mismatch():
    checkpoints = _Checkpoints()
    _registration, coordinator = _coordinator(checkpoints)
    work_intent = dict(_activated().work_intent)
    context = _context(work_intent)
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": _snapshot(),
        "execution": {"execution_id": EXECUTION},
    }
    assert coordinator.replay_begin(**values) is None
    coordinator.begin(**values)
    checkpoints.saved["stage"] = "DRIFTED"
    with pytest.raises(AccountingAllocationProductCoordinatorError) as drift:
        coordinator.replay_begin(**values)
    assert (
        drift.value.error_code == "ACCOUNTING_ALLOCATION_PRODUCT_COORDINATOR_CONFLICT"
    )

    changed = deepcopy(work_intent)
    changed["execution_id"] = str(uuid.uuid4())
    with pytest.raises(AccountingAllocationProductCoordinatorError) as lineage:
        coordinator.begin(**{**values, "work_intent": changed})
    assert (
        lineage.value.error_code == "ACCOUNTING_ALLOCATION_PRODUCT_COORDINATOR_CONFLICT"
    )


def test_ca00f5a_coordinator_has_no_approval_wait_and_requires_source():
    _registration, coordinator = _coordinator()
    for operation in (
        coordinator.accept_approval_notification,
        coordinator.resume_approval,
    ):
        with pytest.raises(AccountingAllocationProductCoordinatorError):
            operation()

    work_intent = dict(_activated().work_intent)
    work_intent.pop("source")
    with pytest.raises(AccountingAllocationProductCoordinatorError) as raised:
        coordinator.begin(
            work_intent=work_intent,
            agent_context=_context(dict(_activated().work_intent)),
            capability_snapshot=_snapshot(),
            execution={"execution_id": EXECUTION},
        )
    assert (
        raised.value.error_code == "ACCOUNTING_ALLOCATION_PRODUCT_COORDINATOR_INVALID"
    )


def test_ca00f5a_plan_activation_wrapper_is_strict_and_forwards_typed_intent():
    registration, _coordinator_value = _coordinator()
    with pytest.raises(AccountingAllocationProductCoordinatorError):
        InstalledAccountingAllocationProductPlanActivation(
            registration=registration,
            activation=object(),
        )

    activation = _Activation(registration)
    wrapper = InstalledAccountingAllocationProductPlanActivation(
        registration=registration,
        activation=activation,
    )
    work_intent = dict(_activated().work_intent)
    result = wrapper.activate(
        work_intent=work_intent,
        agent_context=_context(work_intent),
        capability_snapshot=_snapshot(),
    )
    assert result["activation_hash"].startswith("sha256:")
    assert (
        activation.calls[0]["allocation_work_intent"]
        == work_intent[ACCOUNTING_ALLOCATION_BINDING_FIELD]
    )


def test_ca00f5a_immutable_locks_and_prompt_publish_no_business_defaults():
    capabilities = _capabilities()
    activation, rollback = build_accounting_allocation_activation_documents(
        product_capabilities=capabilities
    )
    assert activation == json.loads(
        (
            ROOT / "deployment/locks/"
            "ae-accounting-allocation-product-coordinator-activation.v1.json"
        ).read_text()
    )
    assert rollback == json.loads(
        (
            ROOT / "deployment/locks/"
            "ae-accounting-allocation-product-coordinator-rollback.v1.json"
        ).read_text()
    )
    prompt_source = (ROOT / "services/nex-ae-api/nex_ae_api/prompts.py").read_text()
    for forbidden in ("40/60", "VO00D260111", "VO00O260112"):
        assert forbidden not in prompt_source
    assert "FINANCE.COST_ALLOCATION.RUN" in prompt_source


def test_ca00f5a_activation_lock_loader_accepts_exact_files_and_rejects_drift(tmp_path):
    capabilities = _capabilities()
    admitted = load_accounting_allocation_coordinator_activation(
        product_capabilities=capabilities,
        environ={},
    )
    assert admitted.registration.activation_status == "ACTIVE"
    assert admitted.activation_lock["activation_state"] == "ACTIVE"

    activation, rollback = build_accounting_allocation_activation_documents(
        product_capabilities=capabilities
    )
    activation["activation_state"] = "DRIFTED"
    activation_path = tmp_path / "activation.json"
    rollback_path = tmp_path / "rollback.json"
    activation_path.write_text(json.dumps(activation), encoding="utf-8")
    rollback_path.write_text(json.dumps(rollback), encoding="utf-8")
    environ = {
        "NEX_AE_ACCOUNTING_ALLOCATION_COORDINATOR_ACTIVATION_PATH": str(
            activation_path
        ),
        "NEX_AE_ACCOUNTING_ALLOCATION_COORDINATOR_ROLLBACK_PATH": str(rollback_path),
    }
    with pytest.raises(AccountingAllocationProductCoordinatorError) as raised:
        load_accounting_allocation_coordinator_activation(
            product_capabilities=capabilities,
            environ=environ,
        )
    assert "drifted" in str(raised.value)

    activation_path.write_text("[]", encoding="utf-8")
    with pytest.raises(AccountingAllocationProductCoordinatorError) as malformed:
        load_accounting_allocation_coordinator_activation(
            product_capabilities=capabilities,
            environ=environ,
        )
    assert "JSON object" in str(malformed.value)


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W80 CA00F.5A AE PostgreSQL smoke is disabled",
)
def test_ca00f5a_actual_postgres_product_entry_restart_replay_and_zero_residue():
    target = make_url(DATABASE_URL)
    assert (target.username, target.database) == ("nex_ae_user", "nex_ae_test")
    schema_name = f"mybee_w80_ca00f5a_{uuid.uuid4().hex}"
    postgres_url = psycopg_database_url(DATABASE_URL)
    with psycopg.connect(postgres_url, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone() == ("nex_ae_test", "nex_ae_user")
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    scoped_url = target.update_query_dict(
        {"options": f"-csearch_path={schema_name},public"}
    ).render_as_string(hide_password=False)
    engines = []
    try:
        migration = run_service_migrations(
            "nex-ae-api", database_url=scoped_url, profile="test"
        )
        assert migration.applied[-1] == load_migrations("nex-ae-api")[-1].version
        activated = AccountingAllocationIntentActivator().activate(
            candidate=_candidate(),
            work_intent=_work_intent(subject="employee-100"),
            tenant_id=TENANT,
            principal_id="employee-100",
            resolved_at=NOW,
        )
        work_intent = dict(activated.work_intent)
        context = _persisted_agent_context(work_intent)
        catalog = _catalog()
        snapshot = _installed_snapshot(catalog)

        engine = create_engine(scoped_url, poolclass=NullPool, pool_pre_ping=True)
        engines.append(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        _seed_lineage(
            sessions,
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
        )
        materializer = object.__new__(M1InstalledSkillRuntime)
        materializer._catalog = catalog
        registration = build_accounting_allocation_product_coordinator_registration(
            product_capabilities=_capabilities(),
            activation_status="ACTIVE",
        )
        registry = ProductPlanningCoordinatorRegistry(
            (registration,),
            registry_id="postgres-accounting-allocation",
            registry_version=1,
        )
        installed = build_installed_accounting_allocation_coordinator_runtime(
            sessions=sessions,
            registration=registration,
            materializer=materializer,
        )
        router = PublicProductPlanningRouter(
            registry,
            InstalledProductCoordinatorRuntimeRegistry(registry, (installed,)),
        )
        first = router.begin_if_registered(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution={"execution_id": work_intent["execution_id"]},
        )
        assert first["ready"] is True

        engine.dispose()
        engine = create_engine(scoped_url, poolclass=NullPool, pool_pre_ping=True)
        engines.append(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        replay_materializer = object.__new__(M1InstalledSkillRuntime)
        replay_materializer._catalog = catalog
        replay_runtime = build_installed_accounting_allocation_coordinator_runtime(
            sessions=sessions,
            registration=registration,
            materializer=replay_materializer,
        )
        replay = PublicProductPlanningRouter(
            registry,
            InstalledProductCoordinatorRuntimeRegistry(registry, (replay_runtime,)),
        ).replay_if_registered(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution={"execution_id": work_intent["execution_id"]},
        )
        assert replay["replayed"] is True
        with sessions() as session:
            counts = {
                table: int(
                    session.execute(
                        text(f"SELECT count(*) FROM {table} WHERE tenant_id=:tenant"),
                        {"tenant": TENANT},
                    ).scalar_one()
                )
                for table in (
                    "ae_product_prep_checkpoint",
                    "ae_agent_plan",
                    "ae_plan_validation",
                    "ae_executable_plan",
                    "ae_executable_step",
                    "ae_runtime_job",
                )
            }
        assert counts == {
            "ae_product_prep_checkpoint": 1,
            "ae_agent_plan": 1,
            "ae_plan_validation": 1,
            "ae_executable_plan": 1,
            "ae_executable_step": 1,
            "ae_runtime_job": 1,
        }
    finally:
        for engine in engines:
            engine.dispose()
        with psycopg.connect(postgres_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            assert connection.execute(
                "SELECT to_regnamespace(%s)", (schema_name,)
            ).fetchone() == (None,)
