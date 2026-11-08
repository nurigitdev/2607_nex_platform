from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import test_nex_ae_p8_s52_nsl_approval_resume_integration as s52
import test_nex_ae_p8_s75e_attachment_manifest as s75e
import test_nex_eos_p8_s58_fresh_authorization as s58
import test_nex_eos_p8_s75f_attachment_admission as s75f
import test_nex_wc_p8_s26_parent_authority as s26
from nex_ae_api.platform_approval_evidence import (
    PlatformApprovalEvidenceError,
    validate_platform_approval_evidence,
)
from nex_ae_api.voucher_attachment_manifest import (
    VoucherAttachmentManifestError,
    require_manifest_approval_binding,
)
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_METADATA,
    EOS_OUTBOX_TABLE,
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    AccountInput,
    EosAuthorizationEvidence,
    EosCreateVoucherDraftService,
    EosServiceCaller,
    EosVoucherCommandError,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosAttachmentRepository,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosVoucherRepository,
    voucher_payload_hash,
)
from nex_wc.work_items import WorkItemError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ATTACK_MATRIX = {
    "approval_evidence_tamper": "AE approval evidence integrity",
    "payload_hash_mismatch": "EOS canonical payload admission",
    "write_intent_hash_mismatch": "AE manifest approval binding",
    "cross_tenant_project": "EOS tenant-scoped Project lookup",
    "cross_tenant_account": "EOS tenant-scoped Account lookup",
    "cross_tenant_attachment": "EOS authenticated attachment resolution",
    "stale_claim_delegation": "WC current parent authority",
    "manifest_drift": "EOS immutable manifest lineage",
    "attachment_substitution": "EOS attachment identity lineage",
    "object_ref_tenant_isolation": "AE-owned opaque object reference",
}

MUTATION_TABLES = (
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
)

NOW = datetime(2026, 10, 24, 15, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]
FOREIGN_TENANT = "tenant-p8-s85-foreign"
FOREIGN_NVT_ID = "85000000-0000-4000-8000-000000000001"
FOREIGN_PROJECT_ID = "85000000-0000-4000-8000-000000000002"
FOREIGN_ACCOUNT_ID = "85000000-0000-4000-8000-000000000003"


class _Authorizer:
    def authorize_create(self, target):
        return EosAuthorizationEvidence(
            tenant_id=target.tenant_id,
            subject_id=target.subject_id,
            service_subject=target.service_subject,
            required_scope="finance:voucher-draft:create",
            project_id=target.project_id,
            resource_type=target.resource_type,
            resource_id=target.resource_id,
            org_unit_id=None,
            authorization_revision_hash="8" * 64,
            authorization_checked_at=NOW,
        )


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _mutation_counts(factory) -> dict[str, int]:
    with factory() as session:
        return {
            table.name: session.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
            for table in MUTATION_TABLES
        }


def _service(factory, *, attachments=None) -> EosCreateVoucherDraftService:
    return EosCreateVoucherDraftService(
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            factory,
            id_factory=lambda: str(uuid4()),
            clock=lambda: NOW,
        ),
        vouchers=SqlAlchemyEosVoucherRepository(factory),
        attachments=attachments,
        authorizer=_Authorizer(),
        id_factory=lambda: str(uuid4()),
        clock=lambda: NOW,
    )


def _caller() -> EosServiceCaller:
    return EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))


def test_s85_canonical_attack_matrix_is_complete() -> None:
    assert len(ATTACK_MATRIX) == 10
    plan = (ROOT / "docs/transition/P8/P8_Implementation_Slice_Plan_v1.0.md").read_text(
        encoding="utf-8"
    )
    preparation = (
        ROOT / "docs/transition/P8/"
        "P8_8_Pre_Entry_Repository_Consistency_and_Reliability_"
        "Preparation_Actions_v1.0.md"
    ).read_text(encoding="utf-8")
    for term in (
        "ApprovalEvidence tamper",
        "PayloadHash mismatch",
        "WriteIntentHash mismatch",
        "cross-tenant Project",
        "cross-tenant Account",
        "cross-tenant attachment",
        "stale Claim delegation",
    ):
        assert term in plan
    for term in ("manifest drift", "attachment substitution", "object_ref tenant"):
        assert term in preparation


@pytest.mark.parametrize("field", ("payload_hash", "approver_id"))
def test_approval_evidence_tamper_fails_integrity_validation(field: str) -> None:
    evidence = s52._evidence()
    evidence[field] = (
        "sha256:" + "0" * 64 if field == "payload_hash" else "other-approver"
    )

    with pytest.raises(PlatformApprovalEvidenceError) as denied:
        validate_platform_approval_evidence(evidence)

    assert denied.value.error_code == "ae.approval_evidence_integrity_failed"


def test_write_intent_hash_mismatch_fails_before_any_write_boundary() -> None:
    manifest = s75e.build_attachment_manifest(
        s75e._batch([s75e._item(s75e.FIRST_ID, suffix="85")])
    )
    governed_payload = {
        "schema_version": "eos_create_voucher_draft_command.v1",
        "tenant_id": s75e.TENANT,
        "attachments": [],
    }
    payload_hash = s75e.nsl_write_payload_hash_ref(
        s75e.bind_manifest_to_governed_payload(governed_payload, manifest)
    )
    request = {
        "approval_request_id": "approval-p8-s85",
        "payload_hash": payload_hash,
        "write_intent_hash": "sha256:" + "8" * 64,
        "display_safe_summary": s75e.approval_display_summary({}, manifest),
    }
    evidence = {
        **request,
        "write_intent_hash": "sha256:" + "0" * 64,
    }

    with pytest.raises(VoucherAttachmentManifestError, match="stale attachment"):
        require_manifest_approval_binding(
            manifest=manifest,
            governed_payload=governed_payload,
            approval_request=request,
            approval_evidence=evidence,
        )


@pytest.mark.parametrize(
    ("attack", "expected_code"),
    (
        ("payload_hash_mismatch", "EOS_VOUCHER_PAYLOAD_HASH_MISMATCH"),
        ("cross_tenant_project", "EOS_VOUCHER_PROJECT_NOT_FOUND"),
        ("cross_tenant_account", "EOS_VOUCHER_ACCOUNT_NOT_FOUND"),
    ),
)
def test_eos_payload_project_account_attacks_leave_zero_mutation(
    attack: str,
    expected_code: str,
) -> None:
    engine, factory = _factory()
    try:
        s58._seed(factory)
        projects = SqlAlchemyEosProjectRepository(factory)
        accounts = SqlAlchemyEosAccountRepository(factory)
        projects.create_nvt_project(
            NvtProjectInput(
                FOREIGN_TENANT,
                FOREIGN_NVT_ID,
                "NVT-S85-FOREIGN",
                "P8 S85 foreign NVT",
            )
        )
        projects.create_project(
            ProjectInput(
                FOREIGN_TENANT,
                FOREIGN_PROJECT_ID,
                "PROJECT-S85-FOREIGN",
                "P8 S85 foreign Project",
                nvt_project_id=FOREIGN_NVT_ID,
            )
        )
        accounts.create_account(
            AccountInput(
                FOREIGN_TENANT,
                FOREIGN_ACCOUNT_ID,
                "ACCOUNT-S85-FOREIGN",
                "P8 S85 foreign Account",
                "EXPENSE",
                "GENERAL",
                date(2026, 1, 1),
            )
        )
        payload = s58._payload()
        if attack == "payload_hash_mismatch":
            payload["description"] = "Tampered without rehashing"
        elif attack == "cross_tenant_project":
            payload["project_ref"] = {
                "type": "eos.project",
                "id": FOREIGN_PROJECT_ID,
            }
            payload["payload_hash"] = voucher_payload_hash(payload)
        else:
            payload["lines"][0]["account_ref"] = {
                "type": "eos.account",
                "id": FOREIGN_ACCOUNT_ID,
            }
            payload["payload_hash"] = voucher_payload_hash(payload)

        with pytest.raises(EosVoucherCommandError) as denied:
            _service(factory).execute(payload, caller=_caller())

        assert denied.value.error_code == expected_code
        assert all(count == 0 for count in _mutation_counts(factory).values())
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("attack", "resolver_changes"),
    (
        ("manifest_drift", {"attachment_manifest_hash": "sha256:" + "f" * 64}),
        (
            "attachment_substitution",
            {"attachment_id": "85000000-0000-4000-8000-000000000010"},
        ),
        ("cross_tenant_attachment", {"tenant_id": FOREIGN_TENANT}),
        (
            "object_ref_tenant_isolation",
            {"object_ref": "objref:ae:voucher:foreign-s85"},
        ),
    ),
)
def test_attachment_tamper_matrix_rolls_back_atomically(
    attack: str,
    resolver_changes: dict[str, object],
) -> None:
    assert attack in ATTACK_MATRIX
    engine, factory = _factory()
    try:
        s75f.SqlAlchemyEosProjectRepository(factory).create_nvt_project(
            NvtProjectInput(s75f.TENANT, s75f.NVT_ID, "NVT-S85", "NVT S85")
        )
        s75f.SqlAlchemyEosProjectRepository(factory).create_project(
            ProjectInput(
                s75f.TENANT,
                s75f.PROJECT_ID,
                "PROJECT-S85",
                "Project S85",
                nvt_project_id=s75f.NVT_ID,
            )
        )
        account_repository = SqlAlchemyEosAccountRepository(factory)
        account_repository.create_account(
            AccountInput(
                s75f.TENANT,
                s75f.DEBIT_ID,
                "TRAVEL-S85",
                "Travel",
                "EXPENSE",
                "GENERAL",
                date(2026, 1, 1),
            )
        )
        account_repository.create_account(
            AccountInput(
                s75f.TENANT,
                s75f.CREDIT_ID,
                "CASH-S85",
                "Cash",
                "ASSET",
                "GENERAL",
                date(2026, 1, 1),
            )
        )
        attachments = SqlAlchemyEosAttachmentRepository(
            factory,
            s75f._Resolver(**resolver_changes),
        )

        with pytest.raises(EosVoucherCommandError) as denied:
            _service(factory, attachments=attachments).execute(
                s75f._payload(),
                caller=_caller(),
            )

        assert denied.value.error_code == "EOS_ATTACHMENT_OBJECT_REJECTED"
        assert all(count == 0 for count in _mutation_counts(factory).values())
    finally:
        engine.dispose()


def test_stale_claim_delegation_creates_no_child_or_lineage() -> None:
    work_items, _coordination, claim = s26._claimed_parent()
    payload = s26._nested_payload(
        parent_claim_ref=claim["claim"]["claim_id"],
        parent_claim_generation=2,
    )

    with pytest.raises(WorkItemError) as denied:
        s26._child_service(work_items).create(payload)

    assert denied.value.error_code == "wc.delegation_parent_authority_stale"
    assert work_items.get(tenant_id=s26.TENANT, work_item_id=s26.CHILD_ID) is None
    assert (
        work_items.get_lineage(tenant_id=s26.TENANT, work_item_id=s26.CHILD_ID) is None
    )
