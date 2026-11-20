from __future__ import annotations

import json
import time
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_eos import (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_INSTANCE_TABLE,
    EOS_APPROVAL_PROOF_TABLE,
    EOS_APPROVAL_STAGE_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    AccountCatalogReleaseInput,
    AccountingPeriodInput,
    AccountInput,
    ApprovalPolicyInput,
    ApprovalPolicyStageInput,
    CoaAdoptionCommand,
    CoaBindingCommand,
    CoaDefinitionReleaseInput,
    CoaEntryInput,
    CompanyAccountPolicyInput,
    FxRatePolicyInput,
    FxRateSnapshotInput,
    LegalEntityInput,
    NvtProjectInput,
    OrgUnitInput,
    PositionAssignmentInput,
    PositionInput,
    PostingRuleReleaseInput,
    ProjectCompanyBindingInput,
    ProjectInput,
    ProjectMembershipInput,
    ProjectWorkCodeSetApproval,
    SqlAlchemyEosAccountCatalogRepository,
    SqlAlchemyEosAccountingPeriodRepository,
    SqlAlchemyEosAllocationPlanRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosCoaOperationsRepository,
    SqlAlchemyEosFxRateRepository,
    SqlAlchemyEosLegalEntityRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectMembershipRepository,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosProjectWorkCodeRepository,
    SqlAlchemyEosUnifiedCoaRepository,
    allocation_plans,
    fx_policy_hash,
)
from nex_eos.project_applications import PROJECT_REFERENCE_RESOLVE_SCOPE
from nex_eos.project_entitlement_events import append_project_entitlement_snapshot
from nex_eos.project_lifecycle_events import append_project_lifecycle_event
from nex_oa.credentials import SqlAlchemyOaCredentialRegistry
from nex_oa.memberships import SqlAlchemyOaTenantMembershipRegistry
from nex_oa.subjects import SqlAlchemyOaSubjectRegistry
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE_PATH = (
    ROOT / "scripts/deployment/data/mybee_m1_product_acceptance.v1.json"
)
PROFILE_POLICY_REF = "policy://nex-platform/project-agent-lifecycle/v1"
M1_APPROVAL_POSITION_TYPE = "TEAM_LEAD"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
HASH_E = "sha256:" + "e" * 64

_OA_SCOPES = {
    "requester": (
        "workspace:use",
        PROJECT_REFERENCE_RESOLVE_SCOPE,
        "finance:document:read",
        "finance:voucher-candidate:create",
        "finance:journal:request-approval",
        "finance:report:read",
        "project:pnl:read",
    ),
    "approver": (
        "workspace:use",
        "approval:read",
        "approval:decide",
        "finance:journal:approve",
        "finance:cost-allocation-plan:approve",
        "finance:report:read",
        "project:pnl:read",
    ),
}


class M1ProductAcceptanceSupportError(RuntimeError):
    pass


def load_acceptance_baseline(path: Path = DEFAULT_BASELINE_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M1ProductAcceptanceSupportError(
            "M1 product acceptance baseline is unreadable"
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != (
        "mybee_m1_product_acceptance.v1"
    ):
        raise M1ProductAcceptanceSupportError(
            "M1 product acceptance baseline schema drifted"
        )
    projects = value.get("projects")
    transactions = value.get("transactions")
    if (
        not isinstance(projects, list)
        or len(projects) != 2
        or not isinstance(transactions, list)
        or len(transactions) < 2
    ):
        raise M1ProductAcceptanceSupportError(
            "M1 product acceptance requires two Projects and two transactions"
        )
    ratios = sum(Decimal(str(item["allocation_ratio"])) for item in projects)
    if ratios != Decimal("1.000000000000"):
        raise M1ProductAcceptanceSupportError(
            "M1 product acceptance allocation ratios must sum to one"
        )
    if projects[0]["project_code"] == projects[1]["project_code"]:
        raise M1ProductAcceptanceSupportError(
            "M1 product acceptance Project codes must be distinct"
        )
    return value


def baseline_digest(value: Mapping[str, Any]) -> str:
    return semantic_sha256_hash_ref(
        {"domain": "MYBEE-M1-PRODUCT-ACCEPTANCE-BASELINE-V1", **dict(value)}
    )


def build_transaction_prompt(
    baseline: Mapping[str, Any], *, transaction_index: int
) -> str:
    transaction = baseline["transactions"][transaction_index]
    projects = baseline["projects"]
    return (
        f"회사 코드 {baseline['company']['company_code']} 기준으로 "
        f"{baseline['recognition_date']} 공급사 {transaction['counterparty']}의 "
        f"{transaction['currency']} {transaction['amount']} 용역비를 전표 처리하고 "
        f"승인해줘. 주 Project는 {projects[0]['project_code']}이고 배부는 "
        f"{projects[0]['project_code']} 40%, {projects[1]['project_code']} 60%로 "
        f"해줘. 문서 제목은 {transaction['document_subject']}야."
    )


def seed_acceptance_authority(
    urls: Mapping[str, str],
    *,
    requester_password: str,
    approver_password: str,
    baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    data = dict(baseline or load_acceptance_baseline())
    tenant_id = str(data["tenant"]["tenant_id"])
    oa_engine = create_engine(urls["nex-oa"], poolclass=NullPool)
    eos_engine = create_engine(urls["nex-eos"], poolclass=NullPool)
    try:
        _seed_oa(
            oa_engine,
            data,
            requester_password=requester_password,
            approver_password=approver_password,
        )
        eos = _seed_eos(eos_engine, data)
        return {
            "schema_version": "mybee_m1_product_acceptance_seed.v1",
            "tenant_id": tenant_id,
            "baseline_digest": baseline_digest(data),
            "requester_subject_id": data["principals"]["requester"]["subject_id"],
            "approver_subject_id": data["principals"]["approver"]["subject_id"],
            "project_codes": [item["project_code"] for item in data["projects"]],
            "authority_records": eos,
            "post_request_business_mutations": 0,
        }
    finally:
        oa_engine.dispose()
        eos_engine.dispose()


def wait_for_installed_authority(
    urls: Mapping[str, str],
    *,
    tenant_id: str,
    expected_project_count: int,
    timeout_seconds: float = 90.0,
) -> dict[str, int]:
    engines = {
        service: create_engine(urls[service], poolclass=NullPool)
        for service in ("nex-oa", "nex-ae-api", "nex-eos")
    }
    try:
        deadline = time.monotonic() + timeout_seconds
        latest: dict[str, int] = {}
        while time.monotonic() < deadline:
            with engines["nex-eos"].connect() as connection:
                latest["pending_outbox"] = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM eos_outbox WHERE tenant_id=:tenant "
                            "AND delivery_state <> 'PUBLISHED'"
                        ),
                        {"tenant": tenant_id},
                    ).scalar_one()
                )
            with engines["nex-ae-api"].connect() as connection:
                latest["project_agents"] = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM ae_project_agent_sync "
                            "WHERE tenant_id=:tenant AND project_state='ACTIVE'"
                        ),
                        {"tenant": tenant_id},
                    ).scalar_one()
                )
            with engines["nex-oa"].connect() as connection:
                latest["entitlement_events"] = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM oa_project_entitlement_inbox "
                            "WHERE tenant_id=:tenant"
                        ),
                        {"tenant": tenant_id},
                    ).scalar_one()
                )
            if (
                latest["pending_outbox"] == 0
                and latest["project_agents"] == expected_project_count
                and latest["entitlement_events"] == expected_project_count
            ):
                return latest
            time.sleep(0.5)
        raise M1ProductAcceptanceSupportError(
            f"installed authority synchronization timed out: {latest}"
        )
    finally:
        for engine in engines.values():
            engine.dispose()


def _seed_oa(
    engine: Engine,
    baseline: Mapping[str, Any],
    *,
    requester_password: str,
    approver_password: str,
) -> None:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    subjects = SqlAlchemyOaSubjectRegistry(factory)
    memberships = SqlAlchemyOaTenantMembershipRegistry(
        factory, subject_registry=subjects
    )
    credentials = SqlAlchemyOaCredentialRegistry(
        factory, subject_registry=subjects
    )
    tenant_id = baseline["tenant"]["tenant_id"]
    passwords = {
        "requester": requester_password,
        "approver": approver_password,
    }
    for role in ("requester", "approver"):
        principal = baseline["principals"][role]
        credentials.ensure_credential(
            {
                "tenant_id": tenant_id,
                "employee_id": principal["employee_id"],
                "subject_id": principal["subject_id"],
                "password": passwords[role],
                "subject_display_name": principal["display_name"],
                "credential_metadata": {
                    "source": "mybee-m1-product-acceptance"
                },
            }
        )
        memberships.ensure_membership(
            {
                "tenant_id": tenant_id,
                "subject_id": principal["subject_id"],
                "tenant_display_name": baseline["tenant"]["display_name"],
                "subject_display_name": principal["display_name"],
                "roles": [
                    "employee",
                    f"m1-{role}",
                    *(
                        [M1_APPROVAL_POSITION_TYPE]
                        if role == "approver"
                        else []
                    ),
                ],
                "scopes": list(_OA_SCOPES[role]),
                "membership_metadata": {
                    "source": "mybee-m1-product-acceptance"
                },
            }
        )


def _seed_eos(engine: Engine, baseline: Mapping[str, Any]) -> dict[str, int]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    tenant_id = str(baseline["tenant"]["tenant_id"])
    company = baseline["company"]
    requester = baseline["principals"]["requester"]
    approver = baseline["principals"]["approver"]
    projects = baseline["projects"]
    effective_on = date(2026, 1, 1)
    now = datetime(2026, 11, 18, 1, 0, tzinfo=UTC)
    legal = SqlAlchemyEosLegalEntityRepository(factory)
    project_repository = SqlAlchemyEosProjectRepository(factory)
    memberships = SqlAlchemyEosProjectMembershipRepository(factory)
    organization = SqlAlchemyEosOrganizationRepository(factory)

    legal.create_legal_entity(
        LegalEntityInput(
            tenant_id,
            company["company_id"],
            company["company_code"],
            company["name"],
            company["functional_currency"],
            company["functional_currency"],
            "Asia/Seoul",
            effective_on,
        )
    )
    nvt_id = _id("nvt")
    project_repository.create_nvt_project(
        NvtProjectInput(tenant_id, nvt_id, "NVT-M1A7", "M1 Acceptance")
    )
    for index, project in enumerate(projects):
        project_repository.create_project(
            ProjectInput(
                tenant_id,
                project["project_id"],
                project["project_code"],
                project["name"],
                nvt_project_id=nvt_id,
                status="ACTIVE",
                start_date=effective_on,
                currency="KRW",
                project_request_code=project["project_request_code"],
                purpose_type="D",
                origin="APPROVED_APPLICATION",
                approval_evidence_ref=f"acceptance:m1:project:{index + 1}",
                approval_evidence_hash=HASH_A,
                project_owner_subject_id=requester["subject_id"],
                project_manager_subject_id=requester["subject_id"],
                agent_sync_state="PENDING",
                authorization_sync_state="PENDING",
                authorization_version=1,
            )
        )
        legal.create_project_company_binding(
            ProjectCompanyBindingInput(
                tenant_id,
                _id(f"binding-{'a' if index == 0 else 'b'}"),
                project["project_id"],
                company["company_id"],
                effective_on,
                HASH_A,
            )
        )
        for role, member_role in (("requester", "OWNER"), ("approver", "MEMBER")):
            principal = baseline["principals"][role]
            memberships.add_membership(
                ProjectMembershipInput(
                    tenant_id,
                    _id(
                        f"membership-{'a' if index == 0 else 'b'}-{role}"
                    ),
                    project["project_id"],
                    principal["subject_id"],
                    member_role,
                    requester["subject_id"],
                    valid_from=now,
                )
            )

    organization.create_org_unit(
        OrgUnitInput(
            tenant_id,
            _id("org"),
            "M1-FINANCE",
            "M1 Finance",
            "TEAM",
            now,
        )
    )
    organization.create_position(
        PositionInput(
            tenant_id,
            _id("position"),
            M1_APPROVAL_POSITION_TYPE,
            _id("org"),
        )
    )
    organization.assign_position(
        PositionAssignmentInput(
            tenant_id,
            _id("position-assignment"),
            _id("position"),
            {"type": "oa.user", "id": approver["subject_id"]},
            now,
        )
    )
    SqlAlchemyEosAccountingPeriodRepository(factory).create_open_period(
        AccountingPeriodInput(
            tenant_id,
            company["company_id"],
            _id("period"),
            2026,
            11,
            date(2026, 11, 1),
            date(2026, 11, 30),
        )
    )
    _seed_accounts_and_coa(factory, baseline)
    _seed_fx(factory, baseline)
    _seed_approval_policies(factory, baseline, now=now)
    _seed_work_codes(factory, baseline, effective_on=effective_on)
    _seed_allocation_plan(factory, baseline, now=now)

    project_agent_ids = []
    with factory.begin() as session:
        for project in projects:
            append_project_entitlement_snapshot(
                session,
                tenant_id=tenant_id,
                project_id=project["project_id"],
                project_code=project["project_code"],
                project_status="ACTIVE",
                source_version=1,
                members=(
                    {
                        "subject_id": requester["subject_id"],
                        "project_role": "OWNER",
                    },
                    {
                        "subject_id": approver["subject_id"],
                        "project_role": "MEMBER",
                    },
                ),
                correlation_id=f"m1-acceptance-entitlement-{project['project_code']}",
                causation_id=f"m1-acceptance-project-{project['project_code']}",
                occurred_at=now,
            )
            append_project_lifecycle_event(
                session,
                tenant_id=tenant_id,
                project_id=project["project_id"],
                project_code=project["project_code"],
                previous_state="SUBMITTED",
                current_state="ACTIVE",
                project_version=1,
                profile_policy_ref=PROFILE_POLICY_REF,
                correlation_id=f"m1-acceptance-lifecycle-{project['project_code']}",
                causation_id=f"m1-acceptance-project-{project['project_code']}",
                occurred_at=now,
            )
            project_agent_ids.append(_project_agent_id(tenant_id, project["project_id"]))
    return {
        "legal_entity": 1,
        "projects": len(projects),
        "project_memberships": len(projects) * 2,
        "project_agents_expected": len(project_agent_ids),
        "approval_policies": 2,
        "allocation_plans": 1,
        "post_request_business_mutations": 0,
    }


def _seed_accounts_and_coa(factory: Any, baseline: Mapping[str, Any]) -> None:
    tenant_id = baseline["tenant"]["tenant_id"]
    company_id = baseline["company"]["company_id"]
    catalog = SqlAlchemyEosAccountCatalogRepository(factory)
    catalog.create_catalog_release(
        AccountCatalogReleaseInput(
            tenant_id,
            _id("catalog"),
            "acceptance://mybee/m1/coa/v1",
            "2026.11",
            HASH_A,
            date(2026, 1, 1),
            "m1-product-acceptance",
            HASH_B,
        )
    )
    catalog.create_posting_rule_release(
        PostingRuleReleaseInput(
            tenant_id,
            _id("posting-rule"),
            company_id,
            _id("catalog"),
            "MYBEE-M1-ACCEPTANCE",
            1,
            HASH_B,
            date(2026, 1, 1),
            HASH_C,
            HASH_A,
        )
    )
    account_specs = (
        (
            "debit",
            "80201002",
            "M1 Other Expense",
            "EXPENSE",
            "OTHER_EXPENSE",
            "PL.OTHER_EXPENSE",
            False,
        ),
        (
            "credit",
            "20101002",
            "M1 Accounts Payable FX",
            "LIABILITY",
            "ACCOUNTS_PAYABLE",
            "BS.ACCOUNTS_PAYABLE",
            True,
        ),
    )
    for key, code, name, category, account_type, statement, monetary in account_specs:
        catalog.create_approved_account(
            account=AccountInput(
                tenant_id,
                _id(f"account-{key}"),
                code,
                name,
                category,
                account_type,
                date(2026, 1, 1),
            ),
            policy=CompanyAccountPolicyInput(
                tenant_id,
                _id(f"account-policy-{key}"),
                company_id,
                _id(f"account-{key}"),
                _id("catalog"),
                _id("posting-rule"),
                True,
                monetary,
                statement,
                ("USD", "KRW"),
                date(2026, 1, 1),
                HASH_B,
            ),
        )

    entries = _coa_entries()
    unified = SqlAlchemyEosUnifiedCoaRepository(factory)
    unified.create_draft_release(
        release=CoaDefinitionReleaseInput(
            _id("coa-release"),
            "GLOBAL",
            "MYBEE-KIFRS-M1",
            "2026.11",
            date(2026, 1, 1),
            "acceptance://mybee/m1/coa/v1",
            HASH_A,
            HASH_B,
            HASH_C,
            "m1-product-acceptance",
        ),
        entries=entries,
    )
    operations = SqlAlchemyEosCoaOperationsRepository(factory)
    with factory.begin() as session:
        operations.publish_release(
            session,
            command=_coa_publication_command(),
        )
        operations.adopt_release(
            session,
            CoaAdoptionCommand(
                tenant_id,
                _id("coa-adoption"),
                company_id,
                _id("coa-release"),
                date(2026, 1, 1),
                HASH_B,
                "m1-product-acceptance",
                (
                    CoaBindingCommand(
                        _id("coa-binding-debit"),
                        _id("coa-debit"),
                        _id("account-debit"),
                        HASH_B,
                    ),
                    CoaBindingCommand(
                        _id("coa-binding-credit"),
                        _id("coa-credit"),
                        _id("account-credit"),
                        HASH_B,
                    ),
                ),
            ),
        )


def _coa_publication_command():
    from nex_eos.coa_operations import CoaPublicationCommand

    return CoaPublicationCommand(
        _id("coa-release"),
        "acceptance://mybee/m1/coa/v1",
        HASH_A,
        HASH_B,
        HASH_C,
        "m1-product-acceptance",
    )


def _coa_entries() -> tuple[CoaEntryInput, ...]:
    specs = (
        ("coa-root-expense", "80000000", "MB-COA-EXPENSE", "Expense", 1, "EXPENSE", "ACCOUNT_GROUP", "DR", False, None),
        ("coa-group-expense", "80200000", "MB-COA-NONOPERATING-EXPENSE", "Non-operating expense", 2, "EXPENSE", "ACCOUNT_GROUP", "DR", False, "coa-root-expense"),
        ("coa-family-expense", "80201000", "MB-COA-OTHER-EXPENSE-FAMILY", "Other expense family", 3, "EXPENSE", "ACCOUNT_GROUP", "DR", False, "coa-group-expense"),
        ("coa-debit", "80201002", "MB-COA-OTHER-EXPENSE", "Other expense", 4, "EXPENSE", "OTHER_EXPENSE", "DR", True, "coa-family-expense"),
        ("coa-root-liability", "20000000", "MB-COA-LIABILITY", "Liability", 1, "LIABILITY", "ACCOUNT_GROUP", "CR", False, None),
        ("coa-group-liability", "20100000", "MB-COA-CURRENT-LIABILITY", "Current liability", 2, "LIABILITY", "ACCOUNT_GROUP", "CR", False, "coa-root-liability"),
        ("coa-family-liability", "20101000", "MB-COA-ACCOUNTS-PAYABLE-FAMILY", "Accounts payable family", 3, "LIABILITY", "ACCOUNT_GROUP", "CR", False, "coa-group-liability"),
        ("coa-credit", "20101002", "MB-COA-ACCOUNTS-PAYABLE-FX", "Accounts payable FX", 4, "LIABILITY", "ACCOUNTS_PAYABLE", "CR", True, "coa-family-liability"),
    )
    return tuple(
        CoaEntryInput(
            _id(identity),
            code,
            semantic,
            name,
            level,
            category,
            account_type,
            balance,
            False,
            postable,
            account_type == "ACCOUNTS_PAYABLE",
            "mybee-m1-product-acceptance.v1",
            semantic_sha256_hash_ref({"identity": identity, "code": code}),
            parent_entry_id=_id(parent) if parent else None,
        )
        for identity, code, semantic, name, level, category, account_type, balance, postable, parent in specs
    )


def _seed_fx(factory: Any, baseline: Mapping[str, Any]) -> None:
    fx = baseline["fx"]
    tenant_id = baseline["tenant"]["tenant_id"]
    company_id = baseline["company"]["company_id"]
    policy_semantics = {
        "tenant_id": tenant_id,
        "company_id": company_id,
        "policy_id": _id("fx-policy"),
        "version": 1,
        "purpose": "TRANSACTION_SPOT",
        "base_currency": fx["base_currency"],
        "quote_currency": fx["quote_currency"],
        "rate_kind": "MARKET_BASE",
        "source_provider_id": fx["source_provider_id"],
        "publication_selector": "FINAL",
        "effective_from": "2026-01-01",
        "effective_to": None,
        "allow_previous_business_day": True,
        "max_staleness_business_days": 3,
        "rounding_mode": "HALF_EVEN",
        "rate_decimal_scale": 6,
        "approved_by": baseline["principals"]["approver"]["subject_id"],
        "approval_proof_hash": HASH_A,
    }
    repository = SqlAlchemyEosFxRateRepository(factory)
    repository.create_approved_policy(
        FxRatePolicyInput(
            tenant_id,
            company_id,
            _id("fx-policy"),
            1,
            "TRANSACTION_SPOT",
            fx["base_currency"],
            fx["quote_currency"],
            "MARKET_BASE",
            fx["source_provider_id"],
            "FINAL",
            date(2026, 1, 1),
            True,
            3,
            "HALF_EVEN",
            6,
            baseline["principals"]["approver"]["subject_id"],
            HASH_A,
            fx_policy_hash(policy_semantics),
        )
    )
    observed = date.fromisoformat(str(baseline["recognition_date"]))
    repository.import_approved_snapshot(
        FxRateSnapshotInput(
            tenant_id,
            company_id,
            _id("fx-snapshot"),
            _id("fx-policy"),
            1,
            fx["source_provider_id"],
            fx["base_currency"],
            fx["quote_currency"],
            Decimal(str(fx["quote_unit"])),
            Decimal(str(fx["published_rate"])),
            observed,
            observed,
            datetime(2026, 11, 18, 0, 30, tzinfo=UTC),
            datetime(2026, 11, 18, 0, 0, tzinfo=UTC),
            "FINAL",
            True,
            "smbs:2026-11-18:usd:final",
            fx["source_uri"],
            semantic_sha256_hash_ref({"source": "smbs", "date": str(observed)}),
            "KR_BUSINESS_DAY_V1",
            "Asia/Seoul",
            {"acquisition_mode": "APPROVED_ACCEPTANCE_IMPORT"},
        )
    )


def _seed_approval_policies(
    factory: Any, baseline: Mapping[str, Any], *, now: datetime
) -> None:
    tenant_id = baseline["tenant"]["tenant_id"]
    primary_project_id = baseline["projects"][0]["project_id"]
    repository = SqlAlchemyEosApprovalPolicyRepository(factory)
    for key, transaction_type in (
        ("business", "DOCUMENT_SIGNOFF"),
        ("accounting", "ACCOUNTING_POSTING"),
    ):
        project_id = (
            None if transaction_type == "DOCUMENT_SIGNOFF" else primary_project_id
        )
        repository.create_policy(
            ApprovalPolicyInput(
                tenant_id,
                _id(f"{key}-policy"),
                f"mybee.m1.acceptance.{key}",
                f"M1 acceptance {key} approval",
                "BUSINESS_FORMAL",
                now,
                (ApprovalPolicyStageInput(M1_APPROVAL_POSITION_TYPE),),
                transaction_type=transaction_type,
                project_id=project_id,
            )
        )


def _seed_work_codes(
    factory: Any, baseline: Mapping[str, Any], *, effective_on: date
) -> None:
    from nex_eos.project_work_codes import (
        D12_CATALOG_DIGEST,
        D12_CATALOG_ID,
        D12_CATALOG_VERSION,
        MANDATORY_D12_WORK_CODE_IDS,
    )

    tenant_id = baseline["tenant"]["tenant_id"]
    requester = baseline["principals"]["requester"]["subject_id"]
    repository = SqlAlchemyEosProjectWorkCodeRepository(factory)
    for index, project in enumerate(baseline["projects"]):
        agent_id = _project_agent_id(tenant_id, project["project_id"])
        repository.approve(
            ProjectWorkCodeSetApproval(
                tenant_id,
                project["project_id"],
                _id(f"work-set-{'a' if index == 0 else 'b'}"),
                1,
                D12_CATALOG_ID,
                D12_CATALOG_VERSION,
                D12_CATALOG_DIGEST,
                "mybee.d12.required-five",
                "1.0.0",
                MANDATORY_D12_WORK_CODE_IDS,
                HASH_A,
                requester,
                requester,
                agent_id,
                semantic_sha256_hash_ref(
                    {"tenant_id": tenant_id, "agent_id": agent_id}
                ),
                effective_on,
            )
        )


def _seed_allocation_plan(
    factory: Any, baseline: Mapping[str, Any], *, now: datetime
) -> None:
    tenant_id = baseline["tenant"]["tenant_id"]
    company_id = baseline["company"]["company_id"]
    projects = baseline["projects"]
    proof_id = _id("allocation-proof")
    payload = {
        "schema_version": "eos_cost_allocation_plan_release.v1",
        "approval_proof_id": proof_id,
        "plan": {
            "plan_id": _id("allocation-plan"),
            "plan_revision": 1,
            "source_kind": "SHARED_EXPENSE",
            "scope_type": "PROJECT_SET",
            "basis_kind": "JUSTIFIED_PERCENTAGE",
            "rule_release_hash": HASH_A,
            "basis_source_ref": "acceptance:m1:allocation-basis:2026-11",
            "basis_source_hash": HASH_B,
            "effective_start": "2026-11-01",
            "effective_end": "2026-11-30",
            "lines": [
                {
                    "line_no": index + 1,
                    "project_id": project["project_id"],
                    "project_code": project["project_code"],
                    "work_code": None,
                    "basis_units": "1.00000000",
                    "allocation_ratio": project["allocation_ratio"],
                    "eligibility_hash": semantic_sha256_hash_ref(
                        {"project_code": project["project_code"]}
                    ),
                    "confidentiality_class": "INTERNAL",
                }
                for index, project in enumerate(projects)
            ],
        },
    }
    _, candidate = allocation_plans._admit_release(
        tenant_id=tenant_id, company_id=company_id, payload=payload
    )
    instance_id = _id("allocation-instance")
    operation_id = _id("allocation-operation")
    decision_id = _id("allocation-decision")
    stage_id = _id("allocation-stage")
    protected_ref = (
        f"eos.cost-allocation-plan:{candidate['plan_id']}:"
        f"revision:{candidate['plan_revision']}"
    )
    with factory.begin() as session:
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=tenant_id,
                business_operation_id=operation_id,
                idempotency_key="m1-acceptance-allocation-operation",
                operation="FINANCE.COST_ALLOCATION_PLAN.RELEASE",
                payload_hash=candidate["plan_hash"],
                commit_state="COMMITTED",
                result_json={
                    "plan_id": candidate["plan_id"],
                    "plan_revision": candidate["plan_revision"],
                },
                created_at=now,
                committed_at=now,
            )
        )
        session.execute(
            EOS_APPROVAL_INSTANCE_TABLE.insert().values(
                tenant_id=tenant_id,
                approval_instance_id=instance_id,
                idempotency_key="m1-acceptance-allocation-plan",
                approval_policy_id=_id("business-policy"),
                policy_version=1,
                policy_hash=HASH_E,
                approval_domain="BUSINESS_FORMAL",
                business_operation_id=operation_id,
                operation="FINANCE.COST_ALLOCATION_PLAN.RELEASE",
                protected_operation_ref=protected_ref,
                payload_hash=candidate["plan_hash"],
                write_intent_hash=HASH_A,
                requester_ref_type="oa.user",
                requester_id=baseline["principals"]["requester"]["subject_id"],
                org_unit_id=_id("org"),
                project_id=projects[0]["project_id"],
                state="APPROVED",
                active_stage_order=None,
                stage_count=1,
                version=2,
                expires_at=None,
                correlation_id="m1-acceptance-allocation",
                causation_id="m1-acceptance-authority",
                binding_hash=semantic_sha256_hash_ref({"instance": instance_id}),
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            EOS_APPROVAL_STAGE_TABLE.insert().values(
                tenant_id=tenant_id,
                approval_stage_id=stage_id,
                approval_instance_id=instance_id,
                stage_order=1,
                policy_stage_order=1,
                position_type="TEAM_LEAD",
                quorum_count=1,
                separation_policy="REQUESTER_EXCLUDED",
                state="APPROVED",
                version=2,
                activated_at=now,
                decided_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            EOS_APPROVAL_DECISION_TABLE.insert().values(
                tenant_id=tenant_id,
                approval_decision_id=_id("allocation-decision-row"),
                approval_instance_id=instance_id,
                approval_stage_id=stage_id,
                wc_approval_work_item_id=_id("allocation-work-item"),
                wc_decision_id=decision_id,
                decision="APPROVE",
                decision_version=1,
                decided_by_ref_type="oa.user",
                decided_by_id=baseline["principals"]["approver"]["subject_id"],
                decision_comment="M1 acceptance allocation authority",
                authorized_by_oa=True,
                oa_decision_ref=f"oa.decision:{decision_id}",
                authorization_revision_hash=HASH_D,
                authorization_checked_at=now,
                decided_at=now,
                decision_hash=semantic_sha256_hash_ref({"decision": decision_id}),
                recorded_at=now,
            )
        )
        session.execute(
            EOS_APPROVAL_PROOF_TABLE.insert().values(
                tenant_id=tenant_id,
                approval_proof_id=proof_id,
                approval_instance_id=instance_id,
                business_operation_id=operation_id,
                final_approval_stage_id=stage_id,
                final_wc_decision_id=decision_id,
                approval_domain="BUSINESS_FORMAL",
                protected_operation_ref=protected_ref,
                payload_hash=candidate["plan_hash"],
                write_intent_hash=HASH_A,
                policy_hash=HASH_E,
                instance_binding_hash=semantic_sha256_hash_ref(
                    {"binding": instance_id}
                ),
                decision_chain_hash=semantic_sha256_hash_ref(
                    {"chain": decision_id}
                ),
                final_decision_hash=semantic_sha256_hash_ref(
                    {"final": decision_id}
                ),
                proof_version=1,
                proof_hash=semantic_sha256_hash_ref({"proof": proof_id}),
                issued_at=now,
            )
        )
    SqlAlchemyEosAllocationPlanRepository(factory, clock=lambda: now).release(
        candidate, approval_proof_id=proof_id
    )


def _id(name: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"https://nex-platform.local/acceptance/m1/{name}",
        )
    )


def _project_agent_id(tenant_id: str, project_id: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/ae/project-agent/"
            f"{tenant_id}/{project_id}",
        )
    )


__all__ = [
    "DEFAULT_BASELINE_PATH",
    "M1ProductAcceptanceSupportError",
    "baseline_digest",
    "build_transaction_prompt",
    "load_acceptance_baseline",
    "seed_acceptance_authority",
    "wait_for_installed_authority",
]
