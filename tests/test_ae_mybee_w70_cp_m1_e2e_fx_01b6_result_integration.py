from __future__ import annotations

import uuid
from types import MappingProxyType, SimpleNamespace

import pytest
from mybee_ax.integrations import NexCostAllocationClient
from mybee_ax.orchestration import (
    M1FinancialResultError,
    M1FinancialResultIntegrator,
    load_m1_transaction_preparation_registration,
)
from nex_ae_api.accounting_allocation_authority import (
    AccountingAllocationAuthorityError,
    build_accounting_allocation_work_intent,
)
from nex_ae_api.business_result_summary import (
    BusinessResultSummaryError,
    admit_business_result_summary,
    build_project_allocation_summary,
)
from nex_ae_api.controlled_skill_runtime import ControlledSkillRuntimeError
from nex_ae_api.m1_accounting_allocation_runtime import (
    AccountingAllocationRuntimeError,
    InstalledAccountingAllocationRuntime,
)
from nex_ae_api.m1_installed_skill_runtime import (
    _committed_journal_id,
    _M1JournalControlledRuntime,
)
from nex_ae_api.work_result_publication import (
    SqlAlchemyInstalledBackgroundResultCloser,
    WorkResultPublicationError,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TENANT = "VO00"
COMPANY = "92000000-0000-4000-8000-000000000001"
JOURNAL = "92000000-0000-4000-8000-000000000002"
POOL = "92000000-0000-4000-8000-000000000003"
PERIOD = "92000000-0000-4000-8000-000000000004"
PLAN = "92000000-0000-4000-8000-000000000005"
SOURCE_PROJECT = "92000000-0000-4000-8000-000000000006"
ACCOUNT = "92000000-0000-4000-8000-000000000007"
PROJECT_A = "92000000-0000-4000-8000-000000000010"
PROJECT_B = "92000000-0000-4000-8000-000000000011"
CODE_A = "VO00D260001"
CODE_B = "VO00D260002"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
ALLOCATION_EXECUTION = "92000000-0000-4000-8000-000000000020"
ALLOCATION_INTENT = "92000000-0000-4000-8000-000000000021"


def _pool() -> dict[str, object]:
    return {
        "schema_version": "eos_cost_source_pool.v1",
        "operation": "FINANCE.COST_SOURCE_POOL.ADMIT",
        "idempotency_disposition": "CREATED",
        "tenant_id": TENANT,
        "company_id": COMPANY,
        "pool_id": POOL,
        "journal_id": JOURNAL,
        "journal_line_no": 1,
        "eligible_component_id": "component:shared-expense",
        "source_business_operation_id": str(uuid.uuid4()),
        "source_project_id": SOURCE_PROJECT,
        "source_project_code": "VO00O269999",
        "source_kind": "SHARED_EXPENSE",
        "allocation_mode": "MANAGEMENT_ALLOCATION",
        "source_amount_functional": "10000.0000",
        "eligible_amount_functional": "10000.0000",
        "functional_currency": "KRW",
        "account_id": ACCOUNT,
        "account_category": "EXPENSE",
        "monetary_class": "MONETARY",
        "recognition_date": "2026-11-17",
        "recognized_at": "2026-11-17T00:00:00Z",
        "period_id": PERIOD,
        "source_record_ref": f"EOS:POSTED_JOURNAL:{JOURNAL}:1",
        "source_hash": HASH_A,
        "eligibility_policy_hash": HASH_B,
        "pool_state": "OPEN",
        "source_journal_hash": HASH_C,
        "created_at": "2026-11-17T00:00:01Z",
    }


def _authority() -> dict[str, object]:
    semantics = {
        "schema_version": "mybee.approved_allocation_plan_authority.v1",
        "stage": "READY_FOR_ALLOCATION",
        "tenant_id": TENANT,
        "company_id": COMPANY,
        "source_pool": {
            "pool_id": POOL,
            "source_hash": HASH_A,
        },
        "allocation_plan": {"plan_id": PLAN, "plan_revision": 3},
    }
    return {**semantics, "checkpoint_hash": semantic_sha256_hash_ref(semantics)}


class _AllocationTransport:
    def __init__(self) -> None:
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        if request.operation_id == "FINANCE.JOURNAL.GET":
            return {
                "schema_version": "eos_posted_journal.v1",
                "operation_id": request.operation_id,
                "header": {
                    "tenant_id": TENANT,
                    "company_id": COMPANY,
                    "journal_id": JOURNAL,
                    "state": "POSTED",
                    "line_count": 1,
                },
                "lines": [
                    {
                        "tenant_id": TENANT,
                        "company_id": COMPANY,
                        "journal_id": JOURNAL,
                        "line_no": 1,
                        "source_record_line_ref": "m1-expense-line",
                    }
                ],
            }
        if request.operation_id == "FINANCE.COST_SOURCE_POOL.ADMIT":
            return _pool()
        if request.operation_id == "FINANCE.COST_ALLOCATION.RUN":
            command = request.body
            return {
                "schema_version": "eos_cost_allocation_batch.v1",
                "operation": request.operation_id,
                "idempotency_disposition": "CREATED",
                "tenant_id": TENANT,
                "business_operation_id": command["business_operation_id"],
                "idempotency_key": command["idempotency_key"],
                "payload_hash": command["payload_hash"],
                "commit_state": "COMMITTED",
                "business_result_ref": f"eos.cost-allocation-batch:{command['batch_id']}",
                "company_id": COMPANY,
                "batch_id": command["batch_id"],
                "plan_id": PLAN,
                "plan_revision": 3,
                "period_id": PERIOD,
                "source_set_hash": HASH_A,
                "functional_currency": "KRW",
                "allocated_total": "10000.0000",
                "unallocated_total": "0.0000",
                "reconciliation_hash": HASH_B,
                "line_count": 2,
                "pool_count": 1,
                "committed_at": "2026-11-17T00:00:02Z",
                "outbox": {},
            }
        batch_id = request.path.split("/")[-2]
        return {
            "schema_version": "eos_cost_allocation_reconciliation.v1",
            "operation": request.operation_id,
            "tenant_id": TENANT,
            "business_operation_id": self.requests[-2].body["business_operation_id"],
            "commit_state": "COMMITTED",
            "reconciliation_status": "COMMITTED_CONFIRMED",
            "verification_status": "VERIFIED",
            "retry_disposition": "DO_NOT_RERUN",
            "batch": {"batch_id": batch_id, "reconciliation_hash": HASH_B},
            "conservation": [
                {
                    "pool_id": POOL,
                    "source_hash": HASH_A,
                    "eligible_amount_functional": "10000.0000",
                    "direct_amount_functional": "0.0000",
                    "allocated_amount_functional": "10000.0000",
                    "unallocated_amount_functional": "0.0000",
                }
            ],
            "reversed_pool_ids": [],
            "outbox": {},
        }


def test_cost_allocation_client_uses_journal_authority_and_exact_replay_identity():
    transport = _AllocationTransport()
    client = NexCostAllocationClient(transport)

    pool = client.admit_source_pool(
        tenant_id=TENANT,
        company_id=COMPANY,
        journal_id=JOURNAL,
        subject_id="employee-1001",
        correlation_id="corr-m1-1",
        source_record_line_ref="m1-expense-line",
        source_kind="SHARED_EXPENSE",
        allocation_mode="MANAGEMENT_ALLOCATION",
    )
    batch, verification = client.run_verified(
        tenant_id=TENANT,
        company_id=COMPANY,
        correlation_id="corr-m1-1",
        source_pool=pool,
        allocation_authority=_authority(),
    )

    assert [item.operation_id for item in transport.requests] == [
        "FINANCE.JOURNAL.GET",
        "FINANCE.COST_SOURCE_POOL.ADMIT",
        "FINANCE.COST_ALLOCATION.RUN",
        "FINANCE.COST_ALLOCATION.VERIFY",
    ]
    assert batch["unallocated_total"] == "0.0000"
    assert verification["verification_status"] == "VERIFIED"


class _Allocation:
    def __init__(self) -> None:
        self.admit_calls = []
        self.run_calls = []

    def admit_source_pool(self, **values):
        self.admit_calls.append(values)
        return MappingProxyType(_pool())

    def run_verified(self, **values):
        self.run_calls.append(values)
        return (
            {
                "batch_id": str(uuid.uuid4()),
                "business_result_ref": "eos.cost-allocation-batch:batch-1",
                "business_operation_id": str(uuid.uuid4()),
                "reconciliation_hash": HASH_B,
                "verification_status": "VERIFIED",
                "allocated_total": "10000.0000",
                "unallocated_total": "0.0000",
                "functional_currency": "KRW",
                "period_id": PERIOD,
            },
            {"verification_status": "VERIFIED"},
        )


class _Refresh:
    def __init__(self) -> None:
        self.batch_id = None

    def refresh(self, **values):
        self.batch_id = values["batch_id"]
        return {
            "period_id": PERIOD,
            "allocation_reconciliation_hash": HASH_B,
            "refresh_hash": HASH_C,
            "projections": [
                {
                    "project_id": PROJECT_A,
                    "project_code": CODE_A,
                    "projection_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, CODE_A)),
                    "projection_version": 2,
                    "projection_hash": HASH_A,
                },
                {
                    "project_id": PROJECT_B,
                    "project_code": CODE_B,
                    "projection_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, CODE_B)),
                    "projection_version": 3,
                    "projection_hash": HASH_B,
                },
            ],
        }


class _Pnl:
    def __init__(self) -> None:
        self.calls = []

    def get(self, **values):
        self.calls.append(values)
        code = values["project_code"]
        version = values["projection_version"]
        return {
            "projection_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, code)),
            "projection_version": version,
            "projection_hash": HASH_A if code == CODE_A else HASH_B,
            "posted_allocated_cost": "4000.0000" if code == CODE_A else "6000.0000",
            "posted_operating_result": "-4000.0000" if code == CODE_A else "-6000.0000",
            "reconciliation_status": "VERIFIED",
            "freshness_status": "CURRENT",
            "data_classification": "CONFIDENTIAL_FINANCIAL",
        }


def _preparation() -> dict[str, object]:
    return {
        "authority": {
            "project_refs": [
                {"project_id": PROJECT_A, "project_code": CODE_A},
                {"project_id": PROJECT_B, "project_code": CODE_B},
            ]
        }
    }


def test_financial_integrator_preserves_authority_and_redacts_public_summary():
    refresh = _Refresh()
    pnl = _Pnl()
    integrator = M1FinancialResultIntegrator(
        allocation_client=_Allocation(),
        refresh_client=refresh,
        pnl_client=pnl,
        authority_resolver=lambda **_values: _authority(),
        registration=load_m1_transaction_preparation_registration(),
    )

    result = integrator.integrate(
        tenant_id=TENANT,
        company_id=COMPANY,
        subject_id="employee-1001",
        correlation_id="corr-m1-2",
        journal_id=JOURNAL,
        work_intent={"intent": "authority-bound"},
        preparation_checkpoint=_preparation(),
    )
    summary = build_project_allocation_summary(result)

    assert refresh.batch_id == result["allocation_batch_id"]
    assert [item["project_code"] for item in result["project_results"]] == [
        CODE_A,
        CODE_B,
    ]
    assert {item["subject_id"] for item in pnl.calls} == {"employee-1001"}
    assert summary["summary"]["project_projections"][0]["project_code"] == CODE_A
    assert "posted_allocated_cost" not in str(summary)
    assert "components" not in str(summary)
    assert admit_business_result_summary(summary, strict=True) == summary


def test_financial_integrator_uses_scenario_neutral_independent_lineage() -> None:
    allocation = _Allocation()
    refresh = _Refresh()
    authority = {
        "schema_version": "mybee.approved_allocation_plan_authority.v2",
        "checkpoint_hash": HASH_C,
        "allocation_plan": {
            "project_refs": [
                {
                    "project_id": PROJECT_B,
                    "project_code": CODE_B,
                    "allocation_ratio": "0.600000000000",
                },
                {
                    "project_id": PROJECT_A,
                    "project_code": CODE_A,
                    "allocation_ratio": "0.400000000000",
                },
            ]
        },
    }
    resolver_calls = []

    def resolve(**values):
        resolver_calls.append(values)
        return authority

    result = M1FinancialResultIntegrator(
        allocation_client=allocation,
        refresh_client=refresh,
        pnl_client=_Pnl(),
        authority_resolver=resolve,
    ).integrate(
        tenant_id=TENANT,
        company_id=COMPANY,
        subject_id="accountant-1",
        correlation_id="allocation-independent-1",
        journal_id=JOURNAL,
        work_intent={"schema_version": "ae.accounting_allocation_work_intent.v1"},
        allocation_authority_checkpoint={"authority_hash": HASH_C},
        source_record_line_ref="m1-expense-line",
        source_kind="SHARED_EXPENSE",
    )

    assert result["schema_version"] == (
        "mybee.accounting-allocation-financial-result.v1"
    )
    assert allocation.admit_calls[0]["allocation_mode"] == "MANAGEMENT_ALLOCATION"
    assert resolver_calls[0]["allocation_authority_checkpoint"] == {
        "authority_hash": HASH_C
    }
    assert "preparation_checkpoint" not in resolver_calls[0]
    assert [item["project_code"] for item in result["project_results"]] == [
        CODE_A,
        CODE_B,
    ]


def test_financial_result_and_summary_fail_closed_on_lineage_or_privacy_drift():
    refresh = _Refresh()
    pnl = _Pnl()
    integrator = M1FinancialResultIntegrator(
        allocation_client=_Allocation(),
        refresh_client=refresh,
        pnl_client=pnl,
        authority_resolver=lambda **_values: _authority(),
        registration=load_m1_transaction_preparation_registration(),
    )
    bad = _preparation()
    bad["authority"]["project_refs"].append(
        {"project_id": PROJECT_A, "project_code": CODE_A}
    )
    with pytest.raises(M1FinancialResultError):
        integrator.integrate(
            tenant_id=TENANT,
            company_id=COMPANY,
            subject_id="employee-1001",
            correlation_id="corr-m1-3",
            journal_id=JOURNAL,
            work_intent={},
            preparation_checkpoint=bad,
        )

    summary = build_project_allocation_summary(
        {
            "journal_ref": f"eos.posted_journal:{JOURNAL}",
            "source_pool_ref": f"eos.cost-source-pool:{POOL}",
            "source_pool_hash": HASH_A,
            "allocation_batch_ref": "eos.cost-allocation-batch:batch-1",
            "allocation_reconciliation_hash": HASH_B,
            "pnl_refresh_hash": HASH_C,
            "project_results": [
                {
                    "project_code": CODE_A,
                    "projection_id": str(uuid.uuid4()),
                    "projection_version": 1,
                    "projection_hash": HASH_A,
                    "reconciliation_status": "VERIFIED",
                    "freshness_status": "CURRENT",
                    "data_classification": "CONFIDENTIAL_FINANCIAL",
                }
            ],
        }
    )
    summary["summary"]["project_projections"][0]["payroll_components"] = []
    with pytest.raises(BusinessResultSummaryError):
        admit_business_result_summary(summary, strict=True)


class _Finalizer:
    def __init__(self) -> None:
        self.calls = []

    def finalize(self, **values):
        self.calls.append(values)
        return SimpleNamespace(delivery={"delivery_id": "delivery-1"})


class _Publisher:
    def __init__(self, *, failure: bool = False) -> None:
        self.calls = []
        self.failure = failure

    def publish(self, **values):
        self.calls.append(values)
        if self.failure:
            raise WorkResultPublicationError("wc.unavailable", "retry", True)
        return {"created": len(self.calls) == 1}


def _closer_sessions():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.execute(
            text(
                "CREATE TABLE ae_agent_execution ("
                "tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL, "
                "agent_type TEXT NOT NULL, source_type TEXT NOT NULL, "
                "state TEXT NOT NULL, phase TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
        )
        session.execute(
            text(
                "CREATE TABLE ae_result_delivery ("
                "tenant_id TEXT NOT NULL, delivery_id TEXT NOT NULL, "
                "agent_execution_id TEXT NOT NULL, target_type TEXT NOT NULL)"
            )
        )
    return sessions


def test_background_closer_finalizes_publishes_and_resumes_after_restart():
    sessions = _closer_sessions()
    finalizer = _Finalizer()
    publisher = _Publisher()
    closer = SqlAlchemyInstalledBackgroundResultCloser(
        sessions, finalizer=finalizer, publisher=publisher
    )
    with sessions.begin() as session:
        session.execute(
            text(
                "INSERT INTO ae_agent_execution VALUES "
                "(:tenant, 'pa-1', 'PA', 'CLAIMED_WORKITEM', 'RUNNING', "
                "'RESULT_VERIFY', '2026-11-17T00:00:00Z'), "
                "(:tenant, 'ia-1', 'IA', 'PROMPT', 'RUNNING', "
                "'RESULT_VERIFY', '2026-11-17T00:00:00Z')"
            ),
            {"tenant": TENANT},
        )

    first = closer.close_ready(now="2026-11-17T00:00:01Z")

    assert first == {
        "candidate_count": 1,
        "finalized_count": 1,
        "published_count": 1,
        "replayed_count": 0,
        "failed_count": 0,
        "failures": [],
    }
    assert finalizer.calls[0]["execution_id"] == "pa-1"

    with sessions.begin() as session:
        session.execute(text("UPDATE ae_agent_execution SET phase = 'RESULT_PUBLISH'"))
        session.execute(
            text(
                "INSERT INTO ae_result_delivery VALUES "
                "(:tenant, 'delivery-1', 'pa-1', 'WC_WORK_RESULT')"
            ),
            {"tenant": TENANT},
        )
    replay = closer.close_ready(now="2026-11-17T00:00:02Z")
    assert replay["replayed_count"] == 1
    assert replay["finalized_count"] == 0


def test_background_closer_records_retryable_publication_failure():
    sessions = _closer_sessions()
    with sessions.begin() as session:
        session.execute(
            text(
                "INSERT INTO ae_agent_execution VALUES "
                "(:tenant, 'pa-2', 'PA', 'CLAIMED_WORKITEM', 'RUNNING', "
                "'RESULT_VERIFY', '2026-11-17T00:00:00Z')"
            ),
            {"tenant": TENANT},
        )
    result = SqlAlchemyInstalledBackgroundResultCloser(
        sessions,
        finalizer=_Finalizer(),
        publisher=_Publisher(failure=True),
    ).close_ready()
    assert result["failed_count"] == 1
    assert result["failures"][0] == {
        "tenant_id": TENANT,
        "agent_execution_id": "pa-2",
        "error_code": "wc.unavailable",
        "retryable": True,
    }


class _Financial:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = []

    def integrate(self, **values):
        self.calls.append(values)
        return self.result


class _AccountingAuthority:
    def __init__(self, *, scopes=("finance:allocation:execute",), active=True):
        self.scopes = scopes
        self.active = active
        self.calls = []

    def effective_authorization(self, **values):
        self.calls.append(values)
        return {
            "active": self.active,
            "tenant_id": values["tenant_id"],
            "subject_id": values["subject_id"],
            "scopes": list(self.scopes),
            "revision_hash": HASH_C,
            "evaluated_at": "2026-11-17T00:00:00Z",
        }


def _allocation_work_intent(projects=None):
    return build_accounting_allocation_work_intent(
        tenant_id=TENANT,
        company_id=COMPANY,
        subject_id="accountant-1",
        execution_id=ALLOCATION_EXECUTION,
        work_intent_id=ALLOCATION_INTENT,
        journal_id=JOURNAL,
        source_record_line_ref="m1-expense-line",
        source_kind="SHARED_EXPENSE",
        projects=(
            [
                {"project_code": CODE_A, "allocation_ratio": "0.400000000000"},
                {"project_code": CODE_B, "allocation_ratio": "0.600000000000"},
            ]
            if projects is None
            else projects
        ),
        source_ref="AE:INTERACTION:allocation-1",
        requested_at="2026-11-17T00:00:00Z",
        publication_target="ACCOUNTING_WORKSPACE",
        publication_target_ref="accounting:workspace:allocation",
    )


def _allocation_runtime_job():
    return {
        "runtime_job_id": "92000000-0000-4000-8000-000000000022",
        "job_type": "START_EXECUTION",
        "execution_id": ALLOCATION_EXECUTION,
        "state": "RUNNING",
        "dedup_key": "allocation:run:92000000",
    }


def test_accounting_allocation_requires_fresh_oa_scope_and_explicit_ratios():
    financial = _Financial(
        {
            "journal_ref": f"eos.posted_journal:{JOURNAL}",
            "source_pool_ref": f"eos.cost-source-pool:{POOL}",
            "source_pool_hash": HASH_A,
            "allocation_batch_ref": "eos.cost-allocation-batch:batch-1",
            "allocation_reconciliation_hash": HASH_B,
            "pnl_refresh_hash": HASH_C,
            "project_results": [
                {
                    "project_code": CODE_A,
                    "projection_id": PROJECT_A,
                    "projection_version": 1,
                    "projection_hash": HASH_A,
                    "reconciliation_status": "VERIFIED",
                    "freshness_status": "CURRENT",
                    "data_classification": "CONFIDENTIAL_FINANCIAL",
                }
            ],
        }
    )
    authority = _AccountingAuthority()
    runtime = InstalledAccountingAllocationRuntime(
        integrator=financial,
        authority=authority,
    )

    result = runtime.execute(
        tenant_id=TENANT,
        company_id=COMPANY,
        subject_id="accountant-1",
        correlation_id="allocation-1",
        journal_id=JOURNAL,
        work_intent=_allocation_work_intent(),
        runtime_job=_allocation_runtime_job(),
    )

    assert result["operation"] == "FINANCE.COST_ALLOCATION.RUN"
    assert result["business_summary"]["result_type"] == "FINANCE.PROJECT_ALLOCATION"
    assert financial.calls[0]["journal_id"] == JOURNAL
    assert financial.calls[0]["allocation_authority_checkpoint"]["stage"] == (
        "AUTHORIZED_FOR_ALLOCATION_RESOLUTION"
    )
    assert result["runtime_job_ref"].endswith("000000000022")
    assert authority.calls == [{"tenant_id": TENANT, "subject_id": "accountant-1"}]


def test_accounting_allocation_denies_missing_scope_and_empty_ratios():
    denied = InstalledAccountingAllocationRuntime(
        integrator=_Financial({}),
        authority=_AccountingAuthority(scopes=()),
    )
    with pytest.raises(AccountingAllocationRuntimeError, match="denied"):
        denied.execute(
            tenant_id=TENANT,
            company_id=COMPANY,
            subject_id="accountant-1",
            correlation_id="allocation-2",
            journal_id=JOURNAL,
            work_intent=_allocation_work_intent(),
            runtime_job=_allocation_runtime_job(),
        )

    with pytest.raises(AccountingAllocationAuthorityError, match="1..64"):
        _allocation_work_intent([])


def test_m1_controlled_outcome_stops_at_posted_journal_and_defers_allocation():
    financial_result = {
        "journal_ref": f"eos.posted_journal:{JOURNAL}",
        "source_pool_ref": f"eos.cost-source-pool:{POOL}",
        "source_pool_hash": HASH_A,
        "allocation_batch_ref": "eos.cost-allocation-batch:batch-1",
        "allocation_reconciliation_hash": HASH_B,
        "pnl_refresh_hash": HASH_C,
        "project_results": [
            {
                "project_code": CODE_A,
                "projection_id": str(uuid.uuid4()),
                "projection_version": 1,
                "projection_hash": HASH_A,
                "reconciliation_status": "VERIFIED",
                "freshness_status": "CURRENT",
                "data_classification": "CONFIDENTIAL_FINANCIAL",
            }
        ],
    }
    financial = _Financial(financial_result)
    writer = object.__new__(_M1JournalControlledRuntime)
    writer._financial_result = financial
    result = SimpleNamespace(
        outcome=SimpleNamespace(
            commit_state=SimpleNamespace(value="COMMITTED"),
            result=SimpleNamespace(
                business_reference=f"eos.posted_journal:{JOURNAL}",
                value=SimpleNamespace(
                    value={
                        "journal_no": "VO00-2026-000001",
                        "project_codes": [CODE_A],
                    }
                ),
            ),
        ),
        verification=SimpleNamespace(status=SimpleNamespace(value="VERIFIED")),
        write_request=SimpleNamespace(idempotency_key="journal-key"),
    )
    authority = SimpleNamespace(
        canonical_write_payload={"company_id": COMPANY},
        business_result_seed={
            "amount": "100000.00",
            "currency": "KRW",
            "account_codes": [
                "MB-COA-OTHER-EXPENSE",
                "MB-COA-ACCOUNTS-PAYABLE-FX",
            ],
            "project_code": CODE_A,
        },
        runtime_metadata={
            "work_intent": {"intent": "bound"},
            "preparation_checkpoint": _preparation(),
            "principal_id": "employee-1001",
            "correlation_id": "corr-m1-4",
        },
    )

    outcome = writer._controlled_write_outcome(
        context=SimpleNamespace(job={"tenant_id": TENANT}),
        result=result,
        authority=authority,
        business_operation_id="operation-1",
    )

    assert outcome.state == "SUCCEEDED"
    assert outcome.result_payload["journal_id"] == JOURNAL
    assert outcome.result_payload["deferred_operations"] == []
    assert financial.calls == []
    assert f"eos.posted_journal:{JOURNAL}" in outcome.external_refs
    assert "financial_result" not in outcome.result_payload
    assert outcome.result_payload["business_summary"]["summary"] == {
        "outcome": "COMMITTED",
        "verification_status": "VERIFIED",
        "approval_state": "APPROVED",
        "business_operation_id": "operation-1",
        "voucher_number": "VO00-2026-000001",
        "amount": "100000.00",
        "currency": "KRW",
        "account_codes": [
            "MB-COA-OTHER-EXPENSE",
            "MB-COA-ACCOUNTS-PAYABLE-FX",
        ],
        "project_code": CODE_A,
        "business_object_link": None,
    }


def test_committed_journal_reference_is_required_for_journal_completion():
    with pytest.raises(ControlledSkillRuntimeError):
        _committed_journal_id(SimpleNamespace(outcome=SimpleNamespace(result=None)))

    writer = object.__new__(_M1JournalControlledRuntime)
    result = SimpleNamespace(
        outcome=SimpleNamespace(
            commit_state=SimpleNamespace(value="COMMITTED"), result=object()
        ),
        verification=SimpleNamespace(status=SimpleNamespace(value="VERIFIED")),
        write_request=SimpleNamespace(idempotency_key="journal-key"),
    )
    with pytest.raises(ControlledSkillRuntimeError, match="reference is unavailable"):
        writer._controlled_write_outcome(
            context=SimpleNamespace(job={"tenant_id": TENANT}),
            result=result,
            authority=SimpleNamespace(
                business_result_seed={
                    "amount": "100000.00",
                    "currency": "KRW",
                    "account_codes": [
                        "MB-COA-OTHER-EXPENSE",
                        "MB-COA-ACCOUNTS-PAYABLE-FX",
                    ],
                    "project_code": CODE_A,
                },
                runtime_metadata=None,
            ),
            business_operation_id="operation-1",
        )
