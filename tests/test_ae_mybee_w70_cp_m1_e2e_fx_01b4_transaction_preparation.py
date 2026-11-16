from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from mybee_ax.integrations.nex_voucher_candidate_client import (
    VoucherCandidateConsumerError,
    admit_posting_admission_result,
    build_posting_admission_request,
)
from mybee_ax.orchestration import (
    M1PreparationAuthority,
    M1PreparationError,
    M1TransactionPreparationAdapter,
    load_m1_transaction_preparation_registration,
)
from nex_ae_api.m1_transaction_preparation_runtime import (
    InstalledM1TransactionPreparationError,
    build_installed_m1_transaction_preparation,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_EXAMPLE = (
    ROOT
    / "contracts"
    / "examples"
    / "service"
    / "ae_work_intent.business_transaction.v1_2.json"
)
TENANT = "VO00"
SUBJECT = "employee-100"
COMPANY_ID = "41000000-0000-4000-8000-000000000001"
PROJECT_A_ID = "41000000-0000-4000-8000-000000000002"
PROJECT_B_ID = "41000000-0000-4000-8000-000000000003"
DEBIT_ACCOUNT_ID = "41000000-0000-4000-8000-000000000004"
CREDIT_ACCOUNT_ID = "41000000-0000-4000-8000-000000000005"
BUSINESS_POLICY_ID = "41000000-0000-4000-8000-000000000006"
ACCOUNTING_POLICY_ID = "41000000-0000-4000-8000-000000000007"
EXECUTION_ID = "41000000-0000-4000-8000-000000000008"
ENVELOPE_ID = "41000000-0000-4000-8000-000000000009"
CANDIDATE_ID = "41000000-0000-4000-8000-000000000010"
EVIDENCE_ID = "41000000-0000-4000-8000-000000000011"
NOW = datetime(2026, 11, 16, 1, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _context() -> dict:
    return json.loads(CONTEXT_EXAMPLE.read_text(encoding="utf-8"))[
        "business_request_context"
    ]


def _authority(**overrides) -> M1PreparationAuthority:
    values = {
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
        "project_refs": (
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
        ),
        "project_authorizations": (
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
        ),
        "debit_account_id": DEBIT_ACCOUNT_ID,
        "debit_semantic_key": "MB-COA-OTHER-EXPENSE",
        "debit_account_evidence_hash": HASH_A,
        "credit_account_id": CREDIT_ACCOUNT_ID,
        "credit_semantic_key": "MB-COA-ACCOUNTS-PAYABLE-FX",
        "credit_account_evidence_hash": HASH_B,
        "business_approval_policy_id": BUSINESS_POLICY_ID,
        "business_approval_policy_version": 3,
        "business_approval_policy_hash": HASH_A,
        "accounting_approval_policy_id": ACCOUNTING_POLICY_ID,
        "accounting_approval_policy_version": 2,
        "accounting_approval_policy_hash": HASH_B,
        "project_authorization_ref": "oa.authorization:m1-project-set",
        "project_authorization_revision_hash": HASH_C,
        "authority_effective_at": NOW,
    }
    values.update(overrides)
    return M1PreparationAuthority(**values)


class _BusinessApprovals:
    def __init__(self) -> None:
        self.semantics_by_key: dict[str, str] = {}
        self.proposals = []

    def submit(self, proposal, **kwargs):
        semantic = semantic_sha256_hash_ref(
            {
                "proposal_hash": proposal.approval_subject_hash,
                "approval_policy_id": kwargs["approval_policy_id"],
                "expires_at": kwargs["expires_at"].isoformat(),
            }
        )
        key = kwargs["idempotency_key"]
        previous = self.semantics_by_key.setdefault(key, semantic)
        if previous != semantic:
            raise M1PreparationError(
                "M1_PREPARATION_SEMANTIC_CONFLICT",
                "same execution was retried with changed proposal semantics",
            )
        self.proposals.append((proposal, dict(kwargs)))
        return {
            "scoped_approval_case": {"case_id": kwargs["case_id"]},
            "wc_publication": {"work_item": {"work_item_id": "wc-business-work-item"}},
        }

    def get_approved_document(self, proposal, *, envelope_id):
        return {
            "schema_version": "eos_approved_document_envelope.v2",
            "tenant_id": TENANT,
            "envelope_id": envelope_id,
            "company_id": COMPANY_ID,
            "approved_document_id": proposal.proposal_id,
            "document_revision": proposal.revision,
            "document_type": proposal.document_type,
            "work_code": proposal.work_code,
            "document_content_hash": proposal.document_content_hash,
            "attachment_manifest_hash": proposal.attachment_manifest_hash,
            "business_approval_proof_id": str(uuid.uuid4()),
            "business_proof_hash": HASH_C,
            "approval_policy_id": BUSINESS_POLICY_ID,
            "approval_policy_version": 3,
            "approval_policy_hash": HASH_A,
            "scope_type": proposal.scope_type,
            "project_set_hash": HASH_B,
            "allowed_project_ids": list(proposal.project_ids),
            "allowed_project_codes": list(proposal.project_codes),
            "approved_amount": "2450.0000",
            "approved_currency": "USD",
            "remaining_amount": "2450.0000",
            "tolerance_policy_hash": None,
            "valid_from": proposal.valid_from.isoformat(),
            "valid_until": (proposal.valid_from + timedelta(days=30)).isoformat(),
            "state": "ACTIVE",
            "usable": True,
            "approved_at": (NOW + timedelta(hours=1)).isoformat(),
            "approved_by_principal_ref": {
                "type": "oa.user",
                "id": "approver-business",
            },
            "source_work_item_ref": "wc.approval-work-item:m1-business",
            "payload_hash": HASH_A,
            "created_business_operation_id": str(uuid.uuid4()),
            "created_at": (NOW + timedelta(hours=1)).isoformat(),
        }


class _VoucherCandidates:
    def __init__(self) -> None:
        self.drafts = []

    def create(self, draft, **_kwargs):
        self.drafts.append(draft)
        return {"candidate_ref": {"id": CANDIDATE_ID}}

    def validate(self, _draft, _created, *, as_of):
        assert as_of == NOW
        return {
            "candidate_version": 1,
            "revision_ref": {"revision_no": 1, "hash": HASH_A},
            "validation_hash": HASH_B,
        }

    def submit_for_review(self, _draft, _created, _validation, **kwargs):
        assert kwargs["approval_policy_id"] == ACCOUNTING_POLICY_ID
        return {
            "scoped_approval_case": {"case_id": kwargs["case_id"]},
            "wc_publication": {
                "work_item": {"work_item_id": "wc-accounting-work-item"}
            },
        }

    def get_review(self, **_kwargs):
        return {
            "candidate_version": 2,
            "current_revision_no": 1,
            "events": [
                {
                    "transition_kind": "SUBMIT",
                    "candidate_hash": HASH_A,
                }
            ],
        }

    def admit_posting(self, **kwargs):
        return {
            "candidate_id": kwargs["candidate_id"],
            "candidate_version": kwargs["expected_candidate_version"],
            "candidate_revision": kwargs["expected_candidate_revision"],
            "candidate_hash": kwargs["expected_candidate_hash"],
            "accounting_approval_evidence_id": kwargs[
                "accounting_approval_evidence_id"
            ],
            "accounting_proof_hash": HASH_B,
            "admission_id": str(uuid.uuid4()),
            "admission_hash": HASH_C,
            "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        }


def _adapter():
    business = _BusinessApprovals()
    vouchers = _VoucherCandidates()
    adapter = M1TransactionPreparationAdapter(
        load_m1_transaction_preparation_registration(),
        business,
        vouchers,
    )
    return adapter, business, vouchers


def test_01b4_installed_registry_and_authority_back_exact_replay() -> None:
    adapter, business, _vouchers = _adapter()
    context = _context()
    authority = _authority()

    first = adapter.begin_proposal(
        business_request_context=context,
        business_context_hash=context["context_hash"],
        authority=authority,
        parent_execution_id=EXECUTION_ID,
    )
    replay = adapter.begin_proposal(
        business_request_context=context,
        business_context_hash=context["context_hash"],
        authority=authority,
        parent_execution_id=EXECUTION_ID,
    )

    assert first == replay
    assert first["stage"] == "WAITING_BUSINESS_APPROVAL"
    assert first["adapter_identity"].startswith(
        "mybee:m1-preparation:MYBEE.M1.AUTHORITATIVE_TRANSACTION_PREPARATION:"
    )
    assert business.proposals[0][1]["approval_policy_id"] == BUSINESS_POLICY_ID
    assert business.proposals[0][1]["expires_at"] == NOW + timedelta(days=7)
    assert business.proposals[0][0] == business.proposals[1][0]


def test_01b4_active_product_runtime_installs_registry_selected_adapter() -> None:
    installed = build_installed_m1_transaction_preparation(
        {
            "NEX_EOS_BASE_URL": "https://eos.example/",
            "NEX_AE_TO_EOS_SERVICE_TOKEN": "signed-service-token",
            "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "17.5",
        }
    )

    readiness = installed.readiness()
    assert readiness["status"] == "READY"
    assert readiness["adapter_id"] == ("MYBEE.M1.AUTHORITATIVE_TRANSACTION_PREPARATION")
    assert readiness["operations"][-1] == "FINANCE.VOUCHER_POSTING.ADMIT"
    assert readiness["timeout_seconds"] == 17.5
    assert "signed-service-token" not in repr(installed)
    assert "signed-service-token" not in str(readiness)


@pytest.mark.parametrize(
    "environment",
    (
        {"NEX_EOS_BASE_URL": "eos.invalid", "NEX_AE_TO_EOS_SERVICE_TOKEN": "x"},
        {
            "NEX_EOS_BASE_URL": "https://eos.example",
            "NEX_AE_TO_EOS_SERVICE_TOKEN": "x",
            "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "0",
        },
        {
            "NEX_EOS_BASE_URL": "https://eos.example",
            "NEX_AE_TO_EOS_SERVICE_TOKEN": "x",
            "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "invalid",
        },
    ),
)
def test_01b4_active_product_runtime_fails_closed(environment) -> None:
    with pytest.raises(InstalledM1TransactionPreparationError):
        build_installed_m1_transaction_preparation(environment)


def test_01b4_changed_request_conflicts_under_same_execution_identity() -> None:
    adapter, _business, _vouchers = _adapter()
    context = _context()
    adapter.begin_proposal(
        business_request_context=context,
        business_context_hash=context["context_hash"],
        authority=_authority(),
        parent_execution_id=EXECUTION_ID,
    )
    changed = copy.deepcopy(context)
    changed["transaction"]["amount"] = "2500.00"
    changed["context_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in changed.items() if key != "context_hash"}
    )

    with pytest.raises(M1PreparationError) as raised:
        adapter.begin_proposal(
            business_request_context=changed,
            business_context_hash=changed["context_hash"],
            authority=_authority(),
            parent_execution_id=EXECUTION_ID,
        )

    assert raised.value.error_code == "M1_PREPARATION_SEMANTIC_CONFLICT"


@pytest.mark.parametrize(
    "authority",
    (
        _authority(company_selector_value="OTHER"),
        _authority(debit_semantic_key="UNADMITTED"),
        _authority(business_approval_policy_version=0),
        _authority(project_authorization_revision_hash="bad"),
        _authority(company_version=0),
        _authority(
            project_authorizations=(
                {
                    "project_code": "VO00D260101",
                    "decision_ref": "oa.authorization:m1-project-a",
                    "revision_hash": HASH_A,
                    "source_version": 7,
                },
            )
        ),
    ),
)
def test_01b4_authority_drift_fails_before_provider(authority) -> None:
    adapter, business, _vouchers = _adapter()
    context = _context()

    with pytest.raises(M1PreparationError):
        adapter.begin_proposal(
            business_request_context=context,
            business_context_hash=context["context_hash"],
            authority=authority,
            parent_execution_id=EXECUTION_ID,
        )

    assert business.proposals == []


@pytest.mark.parametrize(
    "authority",
    (
        _authority(authority_effective_at=NOW.replace(tzinfo=None)),
        _authority(
            project_refs=(
                {
                    "project_id": "not-a-uuid",
                    "project_code": "VO00D260101",
                    "project_version": 7,
                },
                {
                    "project_id": PROJECT_B_ID,
                    "project_code": "VO00D260102",
                    "project_version": 4,
                },
            )
        ),
        _authority(
            project_authorizations=(
                {
                    "project_code": "VO00D260101",
                    "decision_ref": "oa.authorization:m1-project-a",
                    "revision_hash": "invalid",
                    "source_version": 7,
                },
                {
                    "project_code": "VO00D260102",
                    "decision_ref": "oa.authorization:m1-project-b",
                    "revision_hash": HASH_B,
                    "source_version": 4,
                },
            )
        ),
    ),
)
def test_01b4_malformed_authority_fails_closed(authority) -> None:
    adapter, business, _vouchers = _adapter()
    context = _context()

    with pytest.raises(M1PreparationError):
        adapter.begin_proposal(
            business_request_context=context,
            business_context_hash=context["context_hash"],
            authority=authority,
            parent_execution_id=EXECUTION_ID,
        )

    assert business.proposals == []


def test_01b4_rejects_context_identity_and_authority_type_tamper() -> None:
    adapter, business, _vouchers = _adapter()
    context = _context()

    invalid_context = copy.deepcopy(context)
    invalid_context.pop("transaction")
    with pytest.raises(M1PreparationError) as invalid:
        adapter.begin_proposal(
            business_request_context=invalid_context,
            business_context_hash=context["context_hash"],
            authority=_authority(),
            parent_execution_id=EXECUTION_ID,
        )
    assert invalid.value.error_code == "M1_PREPARATION_INVALID"

    with pytest.raises(M1PreparationError) as changed:
        adapter.begin_proposal(
            business_request_context=context,
            business_context_hash=HASH_A,
            authority=_authority(),
            parent_execution_id=EXECUTION_ID,
        )
    assert changed.value.error_code == "M1_PREPARATION_SEMANTIC_CONFLICT"

    with pytest.raises(M1PreparationError):
        adapter.begin_proposal(
            business_request_context=context,
            business_context_hash=context["context_hash"],
            authority=object(),  # type: ignore[arg-type]
            parent_execution_id=EXECUTION_ID,
        )

    with pytest.raises(M1PreparationError):
        adapter.begin_proposal(
            business_request_context=context,
            business_context_hash=context["context_hash"],
            authority=_authority(),
            parent_execution_id="not-a-uuid",
        )
    assert business.proposals == []


def test_01b4_registry_fails_closed_for_unavailable_and_tampered_files(
    tmp_path: Path,
) -> None:
    with pytest.raises(M1PreparationError) as unavailable:
        load_m1_transaction_preparation_registration(tmp_path / "missing.json")
    assert unavailable.value.error_code == "M1_PREPARATION_REGISTRY_UNAVAILABLE"

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(M1PreparationError) as unreadable:
        load_m1_transaction_preparation_registration(malformed)
    assert unreadable.value.error_code == "M1_PREPARATION_REGISTRY_UNAVAILABLE"

    source = json.loads(
        (
            ROOT
            / "domains"
            / "mybee"
            / "config"
            / "m1_transaction_preparation_registry.v1.json"
        ).read_text(encoding="utf-8")
    )

    extra_field = copy.deepcopy(source)
    extra_field["unexpected"] = True
    extra_path = tmp_path / "extra.json"
    extra_path.write_text(json.dumps(extra_field), encoding="utf-8")
    with pytest.raises(M1PreparationError):
        load_m1_transaction_preparation_registration(extra_path)

    invalid_admission = copy.deepcopy(source)
    invalid_admission["adapter_id"] = "UNADMITTED"
    invalid_admission["registry_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in invalid_admission.items()
            if key != "registry_hash"
        }
    )
    admission_path = tmp_path / "admission.json"
    admission_path.write_text(json.dumps(invalid_admission), encoding="utf-8")
    with pytest.raises(M1PreparationError):
        load_m1_transaction_preparation_registration(admission_path)

    invalid_policy = copy.deepcopy(source)
    invalid_policy["account_policy"] = {"debit_semantic_key": "MB-COA-OTHER-EXPENSE"}
    invalid_policy["registry_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in invalid_policy.items() if key != "registry_hash"}
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(invalid_policy), encoding="utf-8")
    with pytest.raises(M1PreparationError):
        load_m1_transaction_preparation_registration(policy_path)

    invalid_text = copy.deepcopy(source)
    invalid_text["adapter_version"] = " padded "
    invalid_text["registry_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in invalid_text.items() if key != "registry_hash"}
    )
    text_path = tmp_path / "text.json"
    text_path.write_text(json.dumps(invalid_text), encoding="utf-8")
    with pytest.raises(M1PreparationError):
        load_m1_transaction_preparation_registration(text_path)


def test_01b4_requires_immutable_accounting_review_submission() -> None:
    class _MissingSubmission(_VoucherCandidates):
        def get_review(self, **_kwargs):
            return {
                "candidate_version": 2,
                "current_revision_no": 1,
                "events": [{"transition_kind": "RETURN"}],
            }

    adapter = M1TransactionPreparationAdapter(
        load_m1_transaction_preparation_registration(),
        _BusinessApprovals(),
        _MissingSubmission(),
    )
    context = _context()

    with pytest.raises(M1PreparationError) as raised:
        adapter.continue_after_accounting_approval(
            business_request_context=context,
            business_context_hash=context["context_hash"],
            authority=_authority(),
            parent_execution_id=EXECUTION_ID,
            candidate_id=CANDIDATE_ID,
            accounting_approval_evidence_id=EVIDENCE_ID,
        )

    assert raised.value.error_code == "M1_ACCOUNTING_REVIEW_NOT_SUBMITTED"


def test_01b4_progresses_through_both_human_approval_checkpoints() -> None:
    adapter, _business, vouchers = _adapter()
    context = _context()
    authority = _authority()

    accounting = adapter.continue_after_business_approval(
        business_request_context=context,
        business_context_hash=context["context_hash"],
        authority=authority,
        parent_execution_id=EXECUTION_ID,
        envelope_id=ENVELOPE_ID,
    )
    ready = adapter.continue_after_accounting_approval(
        business_request_context=context,
        business_context_hash=context["context_hash"],
        authority=authority,
        parent_execution_id=EXECUTION_ID,
        candidate_id=CANDIDATE_ID,
        accounting_approval_evidence_id=EVIDENCE_ID,
    )

    assert accounting["stage"] == "WAITING_ACCOUNTING_APPROVAL"
    assert accounting["references"]["candidate_id"] == CANDIDATE_ID
    assert ready["stage"] == "READY_FOR_D04"
    assert ready["references"]["accounting_approval_evidence_id"] == EVIDENCE_ID
    assert vouchers.drafts[0].project_code == "VO00D260101"
    assert vouchers.drafts[0].original_amount == 2450


def test_01b4_posting_admission_client_rejects_hash_and_binding_tamper() -> None:
    request = build_posting_admission_request(
        tenant_id=TENANT,
        subject_id=SUBJECT,
        company_id=COMPANY_ID,
        candidate_id=CANDIDATE_ID,
        expected_candidate_version=2,
        expected_candidate_revision=1,
        expected_candidate_hash=HASH_A,
        accounting_approval_evidence_id=EVIDENCE_ID,
        correlation_id=EXECUTION_ID,
    )
    semantics = {
        "schema_version": "eos_accounting_posting_admission.v1",
        "operation_id": "FINANCE.VOUCHER.APPROVE_AND_POST.ADMISSION",
        "admission_id": str(uuid.uuid4()),
        "tenant_id": TENANT,
        "company_id": COMPANY_ID,
        "candidate_id": CANDIDATE_ID,
        "candidate_version": 2,
        "candidate_revision": 1,
        "candidate_hash": HASH_A,
        "project_id": PROJECT_A_ID,
        "project_code": "VO00D260101",
        "accounting_approval_evidence_id": EVIDENCE_ID,
        "accounting_proof_hash": HASH_B,
        "approval_case_id": str(uuid.uuid4()),
        "approver_subject_id": "accountant-1",
        "validation_hash": HASH_B,
        "review_hash": HASH_C,
        "submitted_event_id": str(uuid.uuid4()),
        "fresh_oa_decision_ref": "oa.authorization:m1-posting",
        "fresh_oa_revision_hash": HASH_C,
        "fresh_project_authorization": {"allowed": True},
        "snapshot_hash": HASH_A,
        "correlation_id": EXECUTION_ID,
        "admitted_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
    }
    result = {
        **semantics,
        "admission_hash": semantic_sha256_hash_ref(semantics),
    }
    assert admit_posting_admission_result(result, request=request)["candidate_id"] == (
        CANDIDATE_ID
    )

    changed = dict(result)
    changed["candidate_version"] = 3
    changed["admission_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in changed.items() if key != "admission_hash"}
    )
    with pytest.raises(VoucherCandidateConsumerError) as raised:
        admit_posting_admission_result(changed, request=request)
    assert raised.value.code == "MYBEE_POSTING_ADMISSION_BINDING_MISMATCH"
