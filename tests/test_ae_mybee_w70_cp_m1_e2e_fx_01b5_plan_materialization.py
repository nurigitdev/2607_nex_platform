from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import nex_ae_api.m1_plan_materialization as materialization_module
import pytest
from mybee_ax.integrations import M1_D04_CAPABILITY_ID, M1_D12_CAPABILITY_ID
from nex_ae_api.m1_installed_skill_runtime import M1InstalledSkillRuntime
from nex_ae_api.m1_plan_materialization import (
    M1_PLAN_MATERIALIZATION_ERROR_FAMILY,
    M1PlanMaterializationError,
    materialize_m1_transaction_plan,
)
from nex_ae_api.mybee_m1_skill_runtime import build_mybee_m1_verified_skill_catalog
from nex_ae_api.planning_capabilities import build_capability_snapshot
from nex_ae_api.product_runtime_profile import load_verified_product_runtime_config
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
TENANT = "VO00"
SUBJECT = "employee-100"
PROJECT_A_ID = "41000000-0000-4000-8000-000000000002"
PROJECT_B_ID = "41000000-0000-4000-8000-000000000003"
COMPANY_ID = "41000000-0000-4000-8000-000000000001"
CANDIDATE_ID = "41000000-0000-4000-8000-000000000010"
EVIDENCE_ID = "41000000-0000-4000-8000-000000000011"
CONTEXT_ID = "41000000-0000-4000-8000-000000000012"
SNAPSHOT_ID = "41000000-0000-4000-8000-000000000013"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
NOW = "2026-11-16T01:00:00Z"


def _environment() -> dict[str, str]:
    return {
        "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
            ROOT
            / "deployment/environments/ae-product-capability-registry.mybee-m1.v2.json"
        ),
        "NEX_OA_BASE_URL": "https://oa.example",
        "NEX_EOS_BASE_URL": "https://eos.example",
        "NEX_AE_TO_OA_SERVICE_TOKEN": "oa-token",
        "NEX_AE_TO_EOS_SERVICE_TOKEN": "eos-token",
        "NEX_AE_NSL_STATE_ROOT": "/tmp/nex-ae-m1-plan-materialization-test",
    }


def _runtime() -> M1InstalledSkillRuntime:
    sessions = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:"))
    environment = _environment()
    return M1InstalledSkillRuntime(
        sessions,
        catalog=build_mybee_m1_verified_skill_catalog(environment),
        config=load_verified_product_runtime_config(environment),
    )


def _work_intent() -> dict:
    return json.loads(
        (
            ROOT
            / "contracts/examples/service/ae_work_intent.business_transaction.v1_2.json"
        ).read_text(encoding="utf-8")
    )


def _agent_context(work_intent: dict) -> dict:
    value = {
        "context_id": CONTEXT_ID,
        "context_generation": 2,
        "execution_id": work_intent["execution_id"],
        "identity": {"tenant_id": TENANT, "subject_id": SUBJECT},
        "runtime_policy_ref": {"policy_id": "m1", "rule_hash": HASH_A},
        "authority_ref": "oa.authorization:m1-project-set",
        "resolved_entities": [
            {
                "selector_id": "E1",
                "resource_ref": {
                    "system": "nex-eos",
                    "resource_type": "PROJECT",
                    "resource_id": PROJECT_A_ID,
                    "version": "7",
                },
            }
        ],
        "conflicts": [],
        "degradations": [],
    }
    value["context_hash"] = semantic_sha256_hash_ref(value)
    return value


def _snapshot(runtime: M1InstalledSkillRuntime) -> dict:
    return build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id=SNAPSHOT_ID,
        snapshot_version=9,
        created_at=NOW,
        capabilities=tuple(
            item.capability.capability for item in runtime._catalog.selections
        ),
    )


def _preparation(work_intent: dict) -> dict:
    authority = {
        "schema_version": "nex.mybee.m1-preparation-authority.v1",
        "tenant_id": TENANT,
        "requester_subject_id": SUBJECT,
        "company_id": COMPANY_ID,
        "company_code": "NURIVOICE",
        "company_selector_kind": "CODE_OR_NAME",
        "company_selector_value": "NURIVOICE",
        "company_version": 3,
        "company_evidence_hash": HASH_A,
        "functional_currency": "KRW",
        "primary_project_id": PROJECT_A_ID,
        "primary_project_code": "VO00D260101",
        "project_refs": [
            {
                "project_id": PROJECT_A_ID,
                "project_code": "VO00D260101",
                "project_version": 7,
            },
            {
                "project_id": PROJECT_B_ID,
                "project_code": "VO00D260102",
                "project_version": 4,
            },
        ],
        "project_authorizations": [
            {
                "project_code": "VO00D260101",
                "decision_ref": "oa.authorization:m1-project-a",
                "revision_hash": HASH_A,
                "source_version": 7,
            },
            {
                "project_code": "VO00D260102",
                "decision_ref": "oa.authorization:m1-project-b",
                "revision_hash": HASH_B,
                "source_version": 4,
            },
        ],
        "debit_account_id": "41000000-0000-4000-8000-000000000004",
        "debit_semantic_key": "MB-COA-OTHER-EXPENSE",
        "debit_account_evidence_hash": HASH_A,
        "credit_account_id": "41000000-0000-4000-8000-000000000005",
        "credit_semantic_key": "MB-COA-ACCOUNTS-PAYABLE-FX",
        "credit_account_evidence_hash": HASH_B,
        "business_approval_policy_id": "41000000-0000-4000-8000-000000000006",
        "business_approval_policy_version": 3,
        "business_approval_policy_hash": HASH_A,
        "accounting_approval_policy_id": "41000000-0000-4000-8000-000000000007",
        "accounting_approval_policy_version": 2,
        "accounting_approval_policy_hash": HASH_B,
        "project_authorization_ref": "oa.authorization:m1-project-set",
        "project_authorization_revision_hash": HASH_C,
        "authority_effective_at": NOW,
    }
    authority["authority_hash"] = semantic_sha256_hash_ref(authority)
    semantics = {
        "schema_version": "nex.mybee.m1-transaction-preparation.v1",
        "stage": "READY_FOR_D04",
        "business_context_hash": work_intent["business_context_hash"],
        "authority_hash": authority["authority_hash"],
        "authority": authority,
        "adapter_identity": "mybee:m1-preparation:installed:v1",
        "identities": {
            "proposal_id": "41000000-0000-4000-8000-000000000020",
        },
        "references": {
            "candidate_id": CANDIDATE_ID,
            "candidate_version": 2,
            "candidate_revision": 1,
            "candidate_hash": HASH_A,
            "accounting_approval_evidence_id": EVIDENCE_ID,
            "accounting_proof_hash": HASH_B,
            "posting_admission_id": "41000000-0000-4000-8000-000000000021",
            "posting_admission_hash": HASH_C,
            "posting_admission_expires_at": "2026-11-16T01:05:00Z",
        },
    }
    return {**semantics, "preparation_hash": semantic_sha256_hash_ref(semantics)}


def _installed(runtime: M1InstalledSkillRuntime) -> dict:
    return {
        item.capability.capability_id: item.capability.capability
        for item in runtime._catalog.selections
    }


def _rehash_preparation(preparation: dict) -> None:
    authority = preparation["authority"]
    authority["authority_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in authority.items() if key != "authority_hash"}
    )
    preparation["authority_hash"] = authority["authority_hash"]
    preparation["preparation_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in preparation.items() if key != "preparation_hash"}
    )


def test_01b5_materializes_d12_then_d04_through_existing_compiler() -> None:
    runtime = _runtime()
    intent = _work_intent()
    context = _agent_context(intent)
    snapshot = _snapshot(runtime)
    preparation = _preparation(intent)

    first = runtime.materialize_transaction_plan(
        work_intent=intent,
        agent_context=context,
        capability_snapshot=snapshot,
        preparation_checkpoint=preparation,
    )
    replay = runtime.materialize_transaction_plan(
        work_intent=intent,
        agent_context=context,
        capability_snapshot=snapshot,
        preparation_checkpoint=preparation,
    )

    assert first == replay
    assert first.validation_result["status"] == "VALID"
    assert first.executable_plan["schema_version"] == "1.2"
    assert first.executable_plan["compiler_version"] == "p6.1"
    d12, d04 = first.executable_plan["steps"]
    assert (d12["compiled_step_key"], d12["required_capability"]) == (
        "E1",
        M1_D12_CAPABILITY_ID,
    )
    assert (d04["compiled_step_key"], d04["required_capability"]) == (
        "E2",
        M1_D04_CAPABILITY_ID,
    )
    assert d04["depends_on_compiled_step_keys"] == ["E1"]
    d04_inputs = {
        item["target_name"]: item["value"] for item in d04["compiled_input_bindings"]
    }
    assert d04_inputs.pop("m1_preparation_checkpoint") == preparation
    assert d04_inputs == {
        "schema_version": "eos.journal_posting_command.v1",
        "tenant_id": TENANT,
        "company_id": COMPANY_ID,
        "candidate_id": CANDIDATE_ID,
        "expected_candidate_version": 2,
        "expected_candidate_revision": 1,
        "expected_candidate_hash": HASH_A,
        "accounting_approval_evidence_id": EVIDENCE_ID,
    }
    assert [
        runtime._selection(SimpleNamespace(step=step)).capability.capability_id
        for step in first.executable_plan["steps"]
    ] == [M1_D12_CAPABILITY_ID, M1_D04_CAPABILITY_ID]
    assert first.projection()["compiled_step_keys"] == ["E1", "E2"]


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("stage", "M1_PLAN_READY_CHECKPOINT_REQUIRED"),
        ("authority", "M1_PLAN_PREPARATION_INTEGRITY_INVALID"),
        ("context", "M1_PLAN_WORK_INTENT_INVALID"),
        ("lineage", "M1_PLAN_IDENTITY_MISMATCH"),
    ),
)
def test_01b5_rejects_stale_or_tampered_authority_before_compile(
    mutation, expected_code
) -> None:
    runtime = _runtime()
    intent = _work_intent()
    context = _agent_context(intent)
    snapshot = _snapshot(runtime)
    preparation = _preparation(intent)

    if mutation == "stage":
        preparation["stage"] = "WAITING_ACCOUNTING_APPROVAL"
    elif mutation == "authority":
        preparation["authority"]["project_authorization_revision_hash"] = HASH_A
    elif mutation == "context":
        intent["business_context_hash"] = HASH_A
        intent["intent_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in intent.items() if key != "intent_hash"}
        )
    else:
        context["identity"]["subject_id"] = "other-user"
        context["context_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in context.items() if key != "context_hash"}
        )

    with pytest.raises(M1PlanMaterializationError) as caught:
        runtime.materialize_transaction_plan(
            work_intent=intent,
            agent_context=context,
            capability_snapshot=snapshot,
            preparation_checkpoint=preparation,
        )
    assert caught.value.error_code == expected_code
    assert caught.value.error_family == M1_PLAN_MATERIALIZATION_ERROR_FAMILY


def test_01b5_rejects_capability_revision_drift() -> None:
    runtime = _runtime()
    intent = _work_intent()
    context = _agent_context(intent)
    snapshot = _snapshot(runtime)
    preparation = _preparation(intent)
    snapshot["capabilities"][0]["output_contract_ref"] = "contract://drifted"
    snapshot["snapshot_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    )

    with pytest.raises(M1PlanMaterializationError):
        runtime.materialize_transaction_plan(
            work_intent=intent,
            agent_context=context,
            capability_snapshot=snapshot,
            preparation_checkpoint=preparation,
        )


def test_01b5_normalizes_invalid_capability_snapshot_error() -> None:
    runtime = _runtime()
    intent = _work_intent()
    snapshot = _snapshot(runtime)
    snapshot["snapshot_hash"] = HASH_A

    with pytest.raises(M1PlanMaterializationError) as caught:
        runtime.materialize_transaction_plan(
            work_intent=intent,
            agent_context=_agent_context(intent),
            capability_snapshot=snapshot,
            preparation_checkpoint=_preparation(intent),
        )

    assert caught.value.error_code == "M1_PLAN_CAPABILITY_SNAPSHOT_INVALID"
    assert caught.value.error_family == M1_PLAN_MATERIALIZATION_ERROR_FAMILY
    assert str(caught.value) == caught.value.detail


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("project", "M1_PLAN_PRIMARY_PROJECT_MISSING"),
        ("execution", "M1_PLAN_EXECUTION_MISMATCH"),
        ("conflict", "M1_PLAN_CONTEXT_CONFLICT"),
        ("degradation", "M1_PLAN_CONTEXT_DEGRADED"),
    ),
)
def test_01b7n_emits_bounded_lineage_diagnostics(mutation, expected_code) -> None:
    runtime = _runtime()
    intent = _work_intent()
    context = _agent_context(intent)
    preparation = _preparation(intent)

    if mutation == "project":
        context["resolved_entities"] = []
    elif mutation == "execution":
        context["execution_id"] = "41000000-0000-4000-8000-000000000099"
    elif mutation == "conflict":
        context["conflicts"] = [{"reason_code": "TEST_CONFLICT"}]
    else:
        context["degradations"] = [{"reason_code": "TEST_DEGRADATION"}]
    context["context_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in context.items() if key != "context_hash"}
    )

    with pytest.raises(M1PlanMaterializationError) as caught:
        runtime.materialize_transaction_plan(
            work_intent=intent,
            agent_context=context,
            capability_snapshot=_snapshot(runtime),
            preparation_checkpoint=preparation,
        )

    assert caught.value.error_code == expected_code
    assert caught.value.error_family == M1_PLAN_MATERIALIZATION_ERROR_FAMILY


@pytest.mark.parametrize(
    "mutation",
    ("context_contract", "authority_hash", "reference_hash", "uuid", "timestamp"),
)
def test_01b5_rejects_malformed_materialization_inputs(mutation) -> None:
    runtime = _runtime()
    intent = _work_intent()
    context = _agent_context(intent)
    preparation = _preparation(intent)

    if mutation == "context_contract":
        intent["business_request_context"] = {"schema_version": "1.0"}
    elif mutation == "authority_hash":
        preparation["authority"]["project_authorization_revision_hash"] = HASH_A
        preparation["preparation_hash"] = semantic_sha256_hash_ref(
            {
                key: value
                for key, value in preparation.items()
                if key != "preparation_hash"
            }
        )
    elif mutation == "reference_hash":
        preparation["references"]["candidate_hash"] = "not-a-hash"
        preparation["preparation_hash"] = semantic_sha256_hash_ref(
            {
                key: value
                for key, value in preparation.items()
                if key != "preparation_hash"
            }
        )
    elif mutation == "uuid":
        intent["execution_id"] = "not-a-uuid"
        intent["intent_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in intent.items() if key != "intent_hash"}
        )
        context["execution_id"] = "not-a-uuid"
        context["context_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in context.items() if key != "context_hash"}
        )
    else:
        preparation["authority"]["authority_effective_at"] = "not-a-timestamp"
        _rehash_preparation(preparation)

    with pytest.raises(M1PlanMaterializationError):
        materialize_m1_transaction_plan(
            work_intent=intent,
            agent_context=context,
            capability_snapshot=_snapshot(runtime),
            preparation_checkpoint=preparation,
            installed_capabilities=_installed(runtime),
        )


@pytest.mark.parametrize("mutation", ("incomplete", "unavailable"))
def test_01b5_rejects_unavailable_installed_capabilities(mutation) -> None:
    runtime = _runtime()
    intent = _work_intent()
    installed = deepcopy(_installed(runtime))
    if mutation == "incomplete":
        installed.pop(M1_D12_CAPABILITY_ID)
    else:
        installed[M1_D12_CAPABILITY_ID]["capability_version"] = "999.0.0"

    with pytest.raises(M1PlanMaterializationError):
        materialize_m1_transaction_plan(
            work_intent=intent,
            agent_context=_agent_context(intent),
            capability_snapshot=_snapshot(runtime),
            preparation_checkpoint=_preparation(intent),
            installed_capabilities=installed,
        )


def test_01b5_rejects_non_valid_plan_admission(monkeypatch) -> None:
    runtime = _runtime()
    intent = _work_intent()
    monkeypatch.setattr(
        materialization_module,
        "validate_agent_plan",
        lambda **_values: {"status": "INVALID", "issues": [{"code": "TEST"}]},
    )

    with pytest.raises(M1PlanMaterializationError):
        materialize_m1_transaction_plan(
            work_intent=intent,
            agent_context=_agent_context(intent),
            capability_snapshot=_snapshot(runtime),
            preparation_checkpoint=_preparation(intent),
            installed_capabilities=_installed(runtime),
        )
