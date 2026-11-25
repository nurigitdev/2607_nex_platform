from __future__ import annotations

from types import SimpleNamespace

import pytest
from nex_ae_api.controlled_skill_runtime import ControlledSkillRuntimeError
from nex_ae_api.m1_installed_skill_runtime import (
    _journal_business_result_seed,
    _M1JournalControlledRuntime,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

TENANT = "V101"
PROJECT_CODE = "V101D260001"
PROJECT_ID = "11111111-1111-4111-8111-111111111114"
JOURNAL_ID = "22222222-2222-4222-8222-222222222224"
HASH = "sha256:" + "a" * 64


def _context(*, include_primary: bool = True) -> dict:
    value = {
        "schema_version": "ae.business_request_context.v1",
        "request_kind": "FINANCE_VOUCHER_POSTING",
        "source_prompt_ref": "AE:INTERACTION:w80-ca00f5c",
        "company_selector": {"kind": "CODE", "value": "NURIVOICE"},
        "document": {
            "document_type": "BUSINESS_PROPOSAL",
            "subject_ref": "외부 인건비 전표",
            "subject_revision": 1,
            "content_hash": HASH,
            "attachment_manifest_hash": None,
        },
        "transaction": {
            "counterparty_selector": "협력사",
            "amount": "1250000.00",
            "currency": "KRW",
            "recognition_date": "2026-11-25",
            "description": "외부 인건비",
        },
        "requested_allocation": [],
        "candidate_provenance": {
            "intent_candidate_hash": HASH,
            "input_context_hash": HASH,
            "model_profile": "generation",
            "model_ref": "provider-neutral",
        },
    }
    if include_primary:
        value["primary_project_code"] = PROJECT_CODE
    value["context_hash"] = semantic_sha256_hash_ref(value)
    return value


def _preparation(context: dict) -> dict:
    return {
        "schema_version": "nex.mybee.m1-transaction-preparation.v1",
        "stage": "READY_FOR_D04",
        "business_context_hash": context["context_hash"],
        "authority": {
            "schema_version": "nex.mybee.m1-preparation-authority.v1",
            "primary_project_id": PROJECT_ID,
            "primary_project_code": PROJECT_CODE,
            "debit_semantic_key": "MB-COA-OTHER-EXPENSE",
            "credit_semantic_key": "MB-COA-ACCOUNTS-PAYABLE-FX",
        },
    }


def _seed(*, include_primary: bool = True) -> dict:
    context = _context(include_primary=include_primary)
    return _journal_business_result_seed(
        work_intent={"business_request_context": context},
        preparation=_preparation(context),
    )


def _result(*, state: str = "COMMITTED", project_codes=None):
    write_result = None
    if state == "COMMITTED":
        write_result = SimpleNamespace(
            business_reference=f"eos.posted_journal:{JOURNAL_ID}",
            value=SimpleNamespace(
                value={
                    "journal_id": JOURNAL_ID,
                    "journal_no": "V101-2026-000001",
                    "project_codes": project_codes or [PROJECT_CODE],
                }
            ),
        )
    return SimpleNamespace(
        outcome=SimpleNamespace(
            commit_state=SimpleNamespace(value=state),
            result=write_result,
        ),
        verification=(
            SimpleNamespace(status=SimpleNamespace(value="VERIFIED"))
            if state == "COMMITTED"
            else None
        ),
        write_request=SimpleNamespace(idempotency_key="journal-idempotency-key"),
    )


def _authority(seed: dict):
    return SimpleNamespace(
        business_result_seed=seed,
        runtime_metadata={
            "work_intent": {
                "business_request_context": _context(),
            }
        },
    )


def test_ca00f5c_seed_is_typed_and_legacy_primary_replay_is_compatible() -> None:
    assert _seed() == {
        "amount": "1250000.00",
        "currency": "KRW",
        "account_codes": [
            "MB-COA-OTHER-EXPENSE",
            "MB-COA-ACCOUNTS-PAYABLE-FX",
        ],
        "project_code": PROJECT_CODE,
    }
    assert _seed(include_primary=False)["project_code"] == PROJECT_CODE


def test_ca00f5c_seed_rejects_context_and_authority_drift() -> None:
    context = _context()
    preparation = _preparation(context)
    preparation["business_context_hash"] = "sha256:" + "b" * 64
    with pytest.raises(ControlledSkillRuntimeError, match="differs"):
        _journal_business_result_seed(
            work_intent={"business_request_context": context},
            preparation=preparation,
        )

    preparation = _preparation(context)
    preparation["authority"]["primary_project_code"] = "V101D260002"
    with pytest.raises(ControlledSkillRuntimeError, match="Project authority"):
        _journal_business_result_seed(
            work_intent={"business_request_context": context},
            preparation=preparation,
        )

    preparation = _preparation(context)
    preparation["authority"]["debit_semantic_key"] = " "
    with pytest.raises(ControlledSkillRuntimeError, match="account authority"):
        _journal_business_result_seed(
            work_intent={"business_request_context": context},
            preparation=preparation,
        )


def test_ca00f5c_committed_journal_builds_user_facing_business_summary() -> None:
    runtime = object.__new__(_M1JournalControlledRuntime)
    outcome = runtime._controlled_write_outcome(
        context=SimpleNamespace(job={"tenant_id": TENANT}),
        result=_result(),
        authority=_authority(_seed()),
        business_operation_id="operation-w80-ca00f5c",
    )

    assert outcome.state == "SUCCEEDED"
    assert outcome.result_payload["journal_id"] == JOURNAL_ID
    assert outcome.result_payload["business_summary"] == {
        "result_type": "FINANCE.VOUCHER_DRAFT",
        "summary_schema_version": "ae_business_result_summary.v1",
        "summary": {
            "outcome": "COMMITTED",
            "verification_status": "VERIFIED",
            "approval_state": "APPROVED",
            "business_operation_id": "operation-w80-ca00f5c",
            "voucher_number": "V101-2026-000001",
            "amount": "1250000.00",
            "currency": "KRW",
            "account_codes": [
                "MB-COA-OTHER-EXPENSE",
                "MB-COA-ACCOUNTS-PAYABLE-FX",
            ],
            "project_code": PROJECT_CODE,
            "business_object_link": None,
        },
    }


def test_ca00f5c_commit_projection_rejects_project_lineage_drift() -> None:
    runtime = object.__new__(_M1JournalControlledRuntime)
    with pytest.raises(ControlledSkillRuntimeError, match="projection is invalid"):
        runtime._controlled_write_outcome(
            context=SimpleNamespace(job={"tenant_id": TENANT}),
            result=_result(project_codes=["V101D260002"]),
            authority=_authority(_seed()),
            business_operation_id="operation-w80-ca00f5c",
        )


@pytest.mark.parametrize(
    ("state", "expected_state"),
    [
        ("NOT_COMMITTED", "FAILED"),
        ("UNKNOWN_COMMIT_STATE", "BLOCKED"),
    ],
)
def test_ca00f5c_non_committed_outcomes_retain_typed_summary(
    state: str, expected_state: str
) -> None:
    runtime = object.__new__(_M1JournalControlledRuntime)
    outcome = runtime._controlled_write_outcome(
        context=SimpleNamespace(job={"tenant_id": TENANT}),
        result=_result(state=state),
        authority=_authority(_seed()),
        business_operation_id="operation-w80-ca00f5c",
    )

    assert outcome.state == expected_state
    summary = outcome.result_payload["business_summary"]["summary"]
    assert summary["outcome"] == state
    assert summary["voucher_number"] is None


def test_ca00f5c_business_seed_is_required_for_installed_projection() -> None:
    runtime = object.__new__(_M1JournalControlledRuntime)
    authority = _authority(_seed())
    authority.business_result_seed = None
    with pytest.raises(ControlledSkillRuntimeError, match="seed is unavailable"):
        runtime._controlled_write_outcome(
            context=SimpleNamespace(job={"tenant_id": TENANT}),
            result=_result(),
            authority=authority,
            business_operation_id="operation-w80-ca00f5c",
        )
