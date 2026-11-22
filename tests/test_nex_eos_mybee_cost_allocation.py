from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from nex_eos import (
    EOS_ACCOUNTING_PERIOD_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_COST_ALLOCATION_BATCH_TABLE,
    EOS_COST_ALLOCATION_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_TABLE,
    EOS_COST_SOURCE_POOL_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_OUTBOX_TABLE,
    AllocationSourceInput,
    CostAllocationRunCommand,
    EosAllocationOutboxEventError,
    EosAllocationReconciliationError,
    EosAllocationReconciliationService,
    EosCostAllocationError,
    EosCostAllocationService,
    InMemoryEosBusinessTransactionCoordinator,
    SqlAlchemyEosBusinessTransactionCoordinator,
    admit_allocation_committed_event,
    build_allocation_committed_event_payload,
    build_source_set_hash,
    cost_allocation_api,
    cost_allocation_payload_hash,
    deterministic_allocate,
    parse_cost_allocation_run,
)
from nex_eos.cost_allocation_api import register_cost_allocation_routes
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import load_migrations
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "VO00"
COMPANY_ID = "73000000-0000-4000-8000-000000000001"
PERIOD_ID = "73000000-0000-4000-8000-000000000002"
PLAN_ID = "73000000-0000-4000-8000-000000000003"
POOL_ID = "73000000-0000-4000-8000-000000000004"
BATCH_ID = "73000000-0000-4000-8000-000000000005"
OPERATION_ID = "73000000-0000-4000-8000-000000000006"
PROJECT_A = "73000000-0000-4000-8000-000000000010"
PROJECT_B = "73000000-0000-4000-8000-000000000011"
PROJECT_C = "73000000-0000-4000-8000-000000000012"
JOURNAL_ID = "73000000-0000-4000-8000-000000000020"
SOURCE_OPERATION_ID = "73000000-0000-4000-8000-000000000021"
ACCOUNT_ID = "73000000-0000-4000-8000-000000000022"
NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
ROOT = Path(__file__).resolve().parents[1]


def _runtime(*, eligible_amount: str = "100.0000"):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        EOS_BUSINESS_OPERATION_TABLE,
        EOS_IDEMPOTENCY_TABLE,
        EOS_OUTBOX_TABLE,
        EOS_ACCOUNTING_PERIOD_TABLE,
        EOS_COST_ALLOCATION_PLAN_TABLE,
        EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
        EOS_COST_SOURCE_POOL_TABLE,
        EOS_COST_ALLOCATION_BATCH_TABLE,
        EOS_COST_ALLOCATION_LINE_TABLE,
    ):
        table.create(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions.begin() as session:
        session.execute(
            EOS_ACCOUNTING_PERIOD_TABLE.insert().values(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                period_id=PERIOD_ID,
                fiscal_year=2026,
                period_no=11,
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 30),
                state="OPEN",
                version=1,
                close_proof_ref=None,
                closed_at=None,
                ledger_cutoff_watermark=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_COST_ALLOCATION_PLAN_TABLE.insert().values(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                plan_id=PLAN_ID,
                plan_revision=1,
                source_kind="SHARED_EXPENSE",
                scope_type="PROJECT_SET",
                basis_kind="ACTUAL_WORK",
                rule_release_hash=HASH_A,
                basis_source_ref="eos.evidence:worklog:2026-11",
                basis_source_hash=HASH_B,
                effective_start=date(2026, 11, 1),
                effective_end=date(2026, 11, 30),
                approved_by="employee-alloc-2001",
                approved_proof="eos.approval:allocation-plan:1",
                state="APPROVED",
                plan_hash=HASH_C,
                created_at=NOW,
            )
        )
        plan_lines = (
            (1, PROJECT_C, "VO00D260003", "0.333333333333"),
            (2, PROJECT_A, "VO00D260001", "0.333333333334"),
            (3, PROJECT_B, "VO00D260002", "0.333333333333"),
        )
        for line_no, project_id, project_code, ratio in plan_lines:
            session.execute(
                EOS_COST_ALLOCATION_PLAN_LINE_TABLE.insert().values(
                    tenant_id=TENANT,
                    company_id=COMPANY_ID,
                    plan_id=PLAN_ID,
                    plan_revision=1,
                    line_no=line_no,
                    project_id=project_id,
                    project_code=project_code,
                    work_code=None,
                    basis_units=Decimal("1.00000000"),
                    allocation_ratio=Decimal(ratio),
                    eligibility_hash=HASH_A,
                    confidentiality_class="INTERNAL",
                    line_hash=semantic_sha256_hash_ref(
                        {"line_no": line_no, "project_id": project_id}
                    ),
                )
            )
        session.execute(
            EOS_COST_SOURCE_POOL_TABLE.insert().values(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                pool_id=POOL_ID,
                journal_id=JOURNAL_ID,
                journal_line_no=1,
                eligible_component_id=f"ACCOUNT:{ACCOUNT_ID}",
                source_business_operation_id=SOURCE_OPERATION_ID,
                source_project_id=PROJECT_A,
                source_project_code="VO00D260001",
                source_kind="SHARED_EXPENSE",
                allocation_mode="MANAGEMENT_ALLOCATION",
                source_amount_functional=Decimal(eligible_amount),
                eligible_amount_functional=Decimal(eligible_amount),
                functional_currency="KRW",
                account_id=ACCOUNT_ID,
                account_category="EXPENSE",
                monetary_class="NON_MONETARY",
                recognition_date=date(2026, 11, 13),
                recognized_at=NOW,
                period_id=PERIOD_ID,
                source_record_ref="eos.journal:source:line:1",
                source_hash=HASH_A,
                eligibility_policy_hash=HASH_B,
                pool_state="OPEN",
                source_journal_hash=HASH_C,
                created_at=NOW,
            )
        )
    coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
        sessions,
        id_factory=_sequential_uuid_factory(100),
        clock=lambda: NOW,
    )
    return (
        engine,
        sessions,
        EosCostAllocationService(
            session_factory=sessions,
            coordinator=coordinator,
            clock=lambda: NOW,
        ),
        EosAllocationReconciliationService(sessions),
    )


def _sequential_uuid_factory(start: int):
    value = start

    def create() -> str:
        nonlocal value
        value += 1
        return str(uuid.UUID(int=value))

    return create


def _payload(
    *,
    unallocated: str = "0.0000",
    operation_id: str = OPERATION_ID,
    batch_id: str = BATCH_ID,
    idempotency_key: str = "cost-allocation-2026-11-001",
) -> dict:
    value = {
        "schema_version": "eos_cost_allocation_run.v1",
        "business_operation_id": operation_id,
        "idempotency_key": idempotency_key,
        "payload_hash": "sha256:" + "0" * 64,
        "batch_id": batch_id,
        "plan_id": PLAN_ID,
        "plan_revision": 1,
        "period_id": PERIOD_ID,
        "functional_currency": "KRW",
        "currency_scale": 4,
        "sources": [
            {
                "pool_id": POOL_ID,
                "unallocated_amount_functional": unallocated,
            }
        ],
    }
    parsed = parse_cost_allocation_run(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=value
    )
    value["payload_hash"] = cost_allocation_payload_hash(parsed)
    return value


def _run(service, **overrides):
    payload = _payload(**overrides)
    return service.run(tenant_id=TENANT, company_id=COMPANY_ID, payload=payload)


def test_deterministic_allocation_orders_stable_targets_and_preserves_signed_sum():
    lines = [
        {
            "project_id": PROJECT_C,
            "work_code": None,
            "allocation_ratio": "0.333333333333",
        },
        {
            "project_id": PROJECT_A,
            "work_code": None,
            "allocation_ratio": "0.333333333334",
        },
        {
            "project_id": PROJECT_B,
            "work_code": None,
            "allocation_ratio": "0.333333333333",
        },
    ]
    positive = deterministic_allocate(
        amount=Decimal("100.0000"), plan_lines=lines, basis_priority=1
    )
    negative = deterministic_allocate(
        amount=Decimal("-100.0000"), plan_lines=reversed(lines), basis_priority=1
    )

    assert [row["plan_line"]["project_id"] for row in positive] == [
        PROJECT_A,
        PROJECT_B,
        PROJECT_C,
    ]
    assert [row["allocated_amount_functional"] for row in positive] == [
        Decimal("33.3334"),
        Decimal("33.3333"),
        Decimal("33.3333"),
    ]
    assert [row["allocated_amount_functional"] for row in negative] == [
        Decimal("-33.3334"),
        Decimal("-33.3333"),
        Decimal("-33.3333"),
    ]
    assert sum(row["allocated_amount_functional"] for row in negative) == Decimal(
        "-100.0000"
    )


def test_allocation_commit_exact_replay_and_verified_reconciliation():
    engine, sessions, service, reconciliation = _runtime()
    created = _run(service)
    replay = _run(service)
    verified = reconciliation.verify_batch(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        batch_id=BATCH_ID,
    )

    assert created["idempotency_disposition"] == "CREATED"
    assert replay["idempotency_disposition"] == "EXACT_REPLAY"
    assert replay["outbox"] == created["outbox"]
    assert created["allocated_total"] == "100.0000"
    assert created["unallocated_total"] == "0.0000"
    assert created["line_count"] == 3
    assert verified["verification_status"] == "VERIFIED"
    assert verified["retry_disposition"] == "DO_NOT_RERUN"
    assert verified["batch"]["line_count"] == 3
    assert verified["conservation"] == [
        {
            "pool_id": POOL_ID,
            "source_hash": HASH_A,
            "eligible_amount_functional": "100.0000",
            "direct_amount_functional": "0.0000",
            "allocated_amount_functional": "100.0000",
            "unallocated_amount_functional": "0.0000",
        }
    ]
    with sessions() as session:
        assert (
            session.execute(
                select(func.count()).select_from(EOS_COST_ALLOCATION_BATCH_TABLE)
            ).scalar_one()
            == 1
        )
        assert (
            session.execute(
                select(func.count()).select_from(EOS_COST_ALLOCATION_LINE_TABLE)
            ).scalar_one()
            == 3
        )
        assert (
            session.execute(
                select(func.count()).select_from(EOS_OUTBOX_TABLE)
            ).scalar_one()
            == 1
        )
        assert (
            session.execute(
                select(EOS_COST_SOURCE_POOL_TABLE.c.pool_state)
            ).scalar_one()
            == "ALLOCATED"
        )
    engine.dispose()


def test_explicit_unallocated_and_negative_source_conserve_exactly():
    engine, _sessions, service, reconciliation = _runtime()
    partial = _run(service, unallocated="10.0000")
    assert partial["allocated_total"] == "90.0000"
    assert partial["unallocated_total"] == "10.0000"
    assert (
        reconciliation.verify(tenant_id=TENANT, business_operation_id=OPERATION_ID)[
            "verification_status"
        ]
        == "VERIFIED"
    )
    engine.dispose()

    engine, _sessions, service, reconciliation = _runtime(eligible_amount="-100.0000")
    negative = _run(service, unallocated="-10.0000")
    assert negative["allocated_total"] == "-90.0000"
    assert negative["unallocated_total"] == "-10.0000"
    assert (
        reconciliation.verify(tenant_id=TENANT, business_operation_id=OPERATION_ID)[
            "conservation"
        ][0]["eligible_amount_functional"]
        == "-100.0000"
    )
    engine.dispose()


def test_reconciliation_detects_drift_and_requires_adjustment_for_reversal():
    engine, sessions, service, reconciliation = _runtime()
    _run(service)
    with sessions.begin() as session:
        session.execute(
            update(EOS_COST_ALLOCATION_LINE_TABLE)
            .where(EOS_COST_ALLOCATION_LINE_TABLE.c.line_no == 1)
            .values(evidence_hash=HASH_B)
        )
    failed = reconciliation.verify(tenant_id=TENANT, business_operation_id=OPERATION_ID)
    assert failed["verification_status"] == "FAILED"
    assert failed["batch"] is None
    engine.dispose()

    engine, sessions, service, reconciliation = _runtime()
    _run(service)
    with sessions.begin() as session:
        session.execute(
            update(EOS_COST_SOURCE_POOL_TABLE).values(pool_state="REVERSED")
        )
    adjusted = reconciliation.verify(
        tenant_id=TENANT, business_operation_id=OPERATION_ID
    )
    assert adjusted["verification_status"] == "ADJUSTMENT_REQUIRED"
    assert adjusted["reversed_pool_ids"] == [POOL_ID]
    engine.dispose()


@pytest.mark.parametrize(
    ("commit_state", "expected_status", "retry"),
    (
        ("PENDING", "RECONCILIATION_REQUIRED", "RECONCILE_SAME_IDENTITY"),
        ("NOT_COMMITTED", "NOT_COMMITTED_CONFIRMED", "MAY_RETRY_SAME_IDENTITY"),
    ),
)
def test_reconciliation_projects_non_terminal_operation_states(
    commit_state: str, expected_status: str, retry: str
):
    engine, sessions, _service, reconciliation = _runtime()
    with sessions.begin() as session:
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=TENANT,
                business_operation_id=OPERATION_ID,
                idempotency_key="state-projection",
                operation="FINANCE.COST_ALLOCATION.RUN",
                payload_hash=HASH_A,
                commit_state=commit_state,
                result_json=None,
                created_at=NOW,
                committed_at=None,
            )
        )
    result = reconciliation.verify(tenant_id=TENANT, business_operation_id=OPERATION_ID)
    assert result["reconciliation_status"] == expected_status
    assert result["retry_disposition"] == retry
    assert result["batch"] is None
    engine.dispose()


def test_reconciliation_rejects_missing_wrong_type_and_invalid_state():
    engine, sessions, _service, reconciliation = _runtime()
    with pytest.raises(EosAllocationReconciliationError) as missing:
        reconciliation.verify(tenant_id=TENANT, business_operation_id=OPERATION_ID)
    assert missing.value.status_code == 404

    with sessions.begin() as session:
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=TENANT,
                business_operation_id=OPERATION_ID,
                idempotency_key="wrong-operation",
                operation="FINANCE.JOURNAL.POST",
                payload_hash=HASH_A,
                commit_state="COMMITTED",
                result_json={},
                created_at=NOW,
                committed_at=NOW,
            )
        )
    with pytest.raises(EosAllocationReconciliationError) as mismatch:
        reconciliation.verify(tenant_id=TENANT, business_operation_id=OPERATION_ID)
    assert mismatch.value.status_code == 409
    with sessions.begin() as session:
        session.execute(
            update(EOS_BUSINESS_OPERATION_TABLE).values(
                operation="FINANCE.COST_ALLOCATION.RUN", commit_state="BROKEN"
            )
        )
    with pytest.raises(EosAllocationReconciliationError) as invalid:
        reconciliation.verify(tenant_id=TENANT, business_operation_id=OPERATION_ID)
    assert invalid.value.status_code == 503
    assert invalid.value.retryable is True
    engine.dispose()


@pytest.mark.parametrize(
    ("mutation", "detail"),
    (
        (lambda value: value.update(schema_version="wrong"), "schema"),
        (lambda value: value.update(currency_scale=2), "scale"),
        (lambda value: value.update(sources=[]), "non-empty"),
        (
            lambda value: value["sources"].append(dict(value["sources"][0])),
            "unique and sorted",
        ),
        (
            lambda value: value.update(functional_currency="krw"),
            "uppercase ISO",
        ),
        (
            lambda value: value.update(plan_revision=True),
            "positive integer",
        ),
    ),
)
def test_command_contract_rejects_non_canonical_inputs(mutation, detail):
    value = _payload()
    mutation(value)
    with pytest.raises(EosCostAllocationError, match=detail):
        parse_cost_allocation_run(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=value
        )


def test_service_rejects_hash_conflicts_ineligible_sources_and_closed_period():
    engine, sessions, service, _reconciliation = _runtime()
    bad_hash = _payload()
    bad_hash["payload_hash"] = HASH_A
    with pytest.raises(EosCostAllocationError) as mismatch:
        service.run(tenant_id=TENANT, company_id=COMPANY_ID, payload=bad_hash)
    assert mismatch.value.status_code == 422

    with sessions.begin() as session:
        session.execute(
            update(EOS_COST_SOURCE_POOL_TABLE).values(allocation_mode="DIRECT")
        )
    with pytest.raises(EosCostAllocationError) as mode:
        _run(service)
    assert mode.value.error_code == "EOS_COST_ALLOCATION_MODE_CONFLICT"
    with sessions.begin() as session:
        session.execute(
            update(EOS_COST_SOURCE_POOL_TABLE).values(
                allocation_mode="MANAGEMENT_ALLOCATION"
            )
        )
        session.execute(update(EOS_ACCOUNTING_PERIOD_TABLE).values(state="CLOSED"))
    with pytest.raises(EosCostAllocationError) as period:
        _run(service)
    assert period.value.status_code == 409
    engine.dispose()


@pytest.mark.parametrize(
    ("table", "values", "expected_status"),
    (
        (EOS_ACCOUNTING_PERIOD_TABLE, {"period_id": str(uuid.uuid4())}, 404),
        (EOS_COST_ALLOCATION_PLAN_TABLE, {"state": "REVOKED"}, 409),
        (EOS_COST_SOURCE_POOL_TABLE, {"pool_state": "ON_HOLD"}, 409),
        (EOS_COST_SOURCE_POOL_TABLE, {"functional_currency": "USD"}, 409),
        (EOS_COST_SOURCE_POOL_TABLE, {"source_kind": "PAYROLL"}, 409),
        (
            EOS_COST_SOURCE_POOL_TABLE,
            {"recognition_date": date(2026, 12, 1)},
            409,
        ),
    ),
)
def test_reference_and_source_state_guards_fail_closed(table, values, expected_status):
    engine, sessions, service, _reconciliation = _runtime()
    with sessions.begin() as session:
        session.execute(update(table).values(**values))
    with pytest.raises(EosCostAllocationError) as rejected:
        _run(service)
    assert rejected.value.status_code == expected_status
    engine.dispose()


def test_missing_plan_pool_and_plan_lines_fail_closed():
    for table, expected_status in (
        (EOS_COST_ALLOCATION_PLAN_TABLE, 404),
        (EOS_COST_SOURCE_POOL_TABLE, 404),
        (EOS_COST_ALLOCATION_PLAN_LINE_TABLE, 409),
    ):
        engine, sessions, service, _reconciliation = _runtime()
        with sessions.begin() as session:
            session.execute(table.delete())
        with pytest.raises(EosCostAllocationError) as rejected:
            _run(service)
        assert rejected.value.status_code == expected_status
        engine.dispose()


def test_effective_date_and_unallocated_bounds_fail_closed():
    engine, sessions, service, _reconciliation = _runtime()
    with sessions.begin() as session:
        session.execute(
            update(EOS_COST_ALLOCATION_PLAN_TABLE).values(
                effective_start=date(2026, 11, 14),
                effective_end=None,
            )
        )
    with pytest.raises(EosCostAllocationError, match="not effective"):
        _run(service)
    engine.dispose()

    engine, _sessions, service, _reconciliation = _runtime()
    with pytest.raises(EosCostAllocationError) as positive:
        _run(service, unallocated="101.0000")
    assert positive.value.error_code == "EOS_COST_ALLOCATION_CONSERVATION_FAILED"
    engine.dispose()

    engine, _sessions, service, _reconciliation = _runtime(eligible_amount="-100.0000")
    with pytest.raises(EosCostAllocationError) as negative:
        _run(service, unallocated="-101.0000")
    assert negative.value.error_code == "EOS_COST_ALLOCATION_CONSERVATION_FAILED"
    engine.dispose()


def test_transaction_and_clock_guards_are_fail_closed():
    engine, sessions, _service, _reconciliation = _runtime()
    in_memory_service = EosCostAllocationService(
        session_factory=sessions,
        coordinator=InMemoryEosBusinessTransactionCoordinator(),
        clock=lambda: NOW,
    )
    with pytest.raises(EosCostAllocationError) as transaction:
        _run(in_memory_service)
    assert transaction.value.error_code == "EOS_COST_ALLOCATION_TRANSACTION_REQUIRED"

    naive_service = EosCostAllocationService(
        session_factory=sessions,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(sessions),
        clock=lambda: NOW.replace(tzinfo=None),
    )
    with pytest.raises(EosCostAllocationError) as clock:
        _run(naive_service)
    assert clock.value.error_code == "EOS_COST_ALLOCATION_CLOCK_INVALID"
    engine.dispose()


@pytest.mark.parametrize(
    "value",
    ("bad", "1.00000", None, float("inf")),
)
def test_amount_validation_rejects_ambiguous_numbers(value):
    with pytest.raises(EosCostAllocationError):
        deterministic_allocate(
            amount=value,
            plan_lines=[
                {
                    "project_id": PROJECT_A,
                    "work_code": None,
                    "allocation_ratio": "1",
                }
            ],
            basis_priority=1,
        )


@pytest.mark.parametrize("value", ("bad", None, float("inf"), "-0.1", "1.1"))
def test_ratio_validation_rejects_out_of_range_or_non_numeric_values(value):
    with pytest.raises(EosCostAllocationError):
        deterministic_allocate(
            amount=Decimal("1.0000"),
            plan_lines=[
                {
                    "project_id": PROJECT_A,
                    "work_code": None,
                    "allocation_ratio": value,
                }
            ],
            basis_priority=1,
        )


def test_deterministic_allocator_rejects_empty_or_non_conserving_plan():
    with pytest.raises(EosCostAllocationError, match="target lines"):
        deterministic_allocate(
            amount=Decimal("1.0000"), plan_lines=[], basis_priority=1
        )
    with pytest.raises(EosCostAllocationError) as failed:
        deterministic_allocate(
            amount=Decimal("1.0000"),
            plan_lines=[
                {
                    "project_id": PROJECT_A,
                    "work_code": None,
                    "allocation_ratio": "0",
                }
            ],
            basis_priority=1,
        )
    assert failed.value.error_code == "EOS_COST_ALLOCATION_CONSERVATION_FAILED"


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update(business_operation_id="not-a-uuid"),
        lambda value: value.update(payload_hash="not-a-hash"),
        lambda value: value.update(idempotency_key=" padded "),
        lambda value: value.update(sources=[{"pool_id": POOL_ID}]),
    ),
)
def test_command_field_validators_reject_malformed_identity(mutation):
    value = _payload()
    mutation(value)
    with pytest.raises(EosCostAllocationError):
        parse_cost_allocation_run(
            tenant_id=TENANT, company_id=COMPANY_ID, payload=value
        )


@pytest.mark.parametrize(
    "tamper",
    (
        "missing_outbox",
        "missing_plan",
        "missing_lines",
        "totals",
        "target",
        "result",
        "event",
        "transaction",
        "timestamp",
    ),
)
def test_reconciliation_tamper_matrix_returns_failed_projection(tamper):
    engine, sessions, service, reconciliation = _runtime()
    _run(service)
    with sessions.begin() as session:
        if tamper == "missing_outbox":
            session.execute(EOS_OUTBOX_TABLE.delete())
        elif tamper == "missing_plan":
            session.execute(EOS_COST_ALLOCATION_PLAN_TABLE.delete())
        elif tamper == "missing_lines":
            session.execute(EOS_COST_ALLOCATION_LINE_TABLE.delete())
        elif tamper == "totals":
            session.execute(
                update(EOS_COST_ALLOCATION_BATCH_TABLE).values(
                    allocated_total=Decimal("99.0000")
                )
            )
        elif tamper == "target":
            session.execute(
                update(EOS_COST_ALLOCATION_LINE_TABLE)
                .where(EOS_COST_ALLOCATION_LINE_TABLE.c.line_no == 1)
                .values(project_id=str(uuid.uuid4()))
            )
        elif tamper == "result":
            session.execute(
                update(EOS_BUSINESS_OPERATION_TABLE).values(result_json=None)
            )
        elif tamper == "event":
            outbox = session.execute(select(EOS_OUTBOX_TABLE)).mappings().one()
            event = dict(outbox["event_payload"])
            event["source_set_hash"] = HASH_B
            session.execute(update(EOS_OUTBOX_TABLE).values(event_payload=event))
        elif tamper == "timestamp":
            session.execute(
                update(EOS_COST_ALLOCATION_BATCH_TABLE).values(committed_at=None)
            )
        else:
            session.execute(
                update(EOS_IDEMPOTENCY_TABLE).values(idempotency_state="IN_PROGRESS")
            )
    result = reconciliation.verify(tenant_id=TENANT, business_operation_id=OPERATION_ID)
    assert result["verification_status"] == "FAILED"
    engine.dispose()


def test_reconciliation_identity_and_persistence_errors_are_typed():
    engine, _sessions, _service, reconciliation = _runtime()
    with pytest.raises(EosAllocationReconciliationError) as tenant:
        reconciliation.verify(tenant_id=" bad ", business_operation_id=OPERATION_ID)
    assert tenant.value.status_code == 422
    with pytest.raises(EosAllocationReconciliationError) as operation:
        reconciliation.verify(tenant_id=TENANT, business_operation_id="bad")
    assert operation.value.status_code == 422
    with pytest.raises(EosAllocationReconciliationError) as company:
        reconciliation.verify_batch(
            tenant_id=TENANT, company_id="bad", batch_id=BATCH_ID
        )
    assert company.value.status_code == 422
    with pytest.raises(EosAllocationReconciliationError) as batch:
        reconciliation.verify_batch(
            tenant_id=TENANT, company_id=COMPANY_ID, batch_id="bad"
        )
    assert batch.value.status_code == 422
    with pytest.raises(EosAllocationReconciliationError) as missing_batch:
        reconciliation.verify_batch(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            batch_id=str(uuid.uuid4()),
        )
    assert missing_batch.value.status_code == 404
    engine.dispose()
    with pytest.raises(EosAllocationReconciliationError) as unavailable:
        reconciliation.verify(tenant_id=TENANT, business_operation_id=OPERATION_ID)
    assert unavailable.value.status_code == 503
    with pytest.raises(EosAllocationReconciliationError) as batch_unavailable:
        reconciliation.verify_batch(
            tenant_id=TENANT, company_id=COMPANY_ID, batch_id=BATCH_ID
        )
    assert batch_unavailable.value.status_code == 503


def test_batch_identity_and_idempotency_semantic_conflicts_fail_closed():
    engine, sessions, service, _reconciliation = _runtime()
    _run(service)
    with sessions.begin() as session:
        session.execute(update(EOS_COST_SOURCE_POOL_TABLE).values(pool_state="OPEN"))
    with pytest.raises(EosCostAllocationError) as operation_conflict:
        _run(service, operation_id=str(uuid.uuid4()), idempotency_key="other")
    assert operation_conflict.value.status_code == 409
    changed = _payload(unallocated="10.0000")
    changed["business_operation_id"] = OPERATION_ID
    changed["idempotency_key"] = "cost-allocation-2026-11-001"
    parsed = parse_cost_allocation_run(
        tenant_id=TENANT, company_id=COMPANY_ID, payload=changed
    )
    changed["payload_hash"] = cost_allocation_payload_hash(parsed)
    with pytest.raises(EosCostAllocationError) as semantic_conflict:
        service.run(tenant_id=TENANT, company_id=COMPANY_ID, payload=changed)
    assert semantic_conflict.value.status_code == 409
    engine.dispose()


def test_event_contract_admits_canonical_payload_and_rejects_tampering():
    result = {
        "company_id": COMPANY_ID,
        "batch_id": BATCH_ID,
        "plan_id": PLAN_ID,
        "plan_revision": 1,
        "period_id": PERIOD_ID,
        "source_set_hash": HASH_A,
        "reconciliation_hash": HASH_B,
        "committed_at": "2026-11-13T09:00:00Z",
    }
    event = build_allocation_committed_event_payload(
        tenant_id=TENANT,
        business_operation_id=OPERATION_ID,
        operation="FINANCE.COST_ALLOCATION.RUN",
        result=result,
    )
    assert event["commit_state"] == "COMMITTED"
    assert event["committed_at"] == "2026-11-13T09:00:00Z"
    with pytest.raises(EosAllocationOutboxEventError):
        admit_allocation_committed_event({**event, "unexpected": True})
    with pytest.raises(EosAllocationOutboxEventError):
        admit_allocation_committed_event({**event, "source_set_hash": "bad"})
    with pytest.raises(EosAllocationOutboxEventError):
        build_allocation_committed_event_payload(
            tenant_id=TENANT,
            business_operation_id=OPERATION_ID,
            operation="FINANCE.COST_ALLOCATION.RUN",
            result=None,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("schema_version", "wrong"),
        ("commit_state", "PENDING"),
        ("plan_revision", 0),
        ("tenant_id", " bad "),
        ("company_id", "not-a-uuid"),
        ("committed_at", None),
        ("committed_at", "not-a-time"),
        ("committed_at", "2026-11-13T09:00:00"),
    ),
)
def test_event_contract_rejects_invalid_field_semantics(field_name, value):
    event = build_allocation_committed_event_payload(
        tenant_id=TENANT,
        business_operation_id=OPERATION_ID,
        operation="FINANCE.COST_ALLOCATION.RUN",
        result={
            "company_id": COMPANY_ID,
            "batch_id": BATCH_ID,
            "plan_id": PLAN_ID,
            "plan_revision": 1,
            "period_id": PERIOD_ID,
            "source_set_hash": HASH_A,
            "reconciliation_hash": HASH_B,
            "committed_at": "2026-11-13T09:00:00Z",
        },
    )
    event[field_name] = value
    with pytest.raises(EosAllocationOutboxEventError):
        admit_allocation_committed_event(event)


def test_source_set_hash_is_order_independent_and_command_hash_ignores_transport():
    pools = [
        {
            "pool_id": POOL_ID,
            "source_hash": HASH_A,
            "eligible_amount_functional": Decimal("100.0000"),
            "period_id": PERIOD_ID,
            "functional_currency": "KRW",
        },
        {
            "pool_id": "73000000-0000-4000-8000-000000000099",
            "source_hash": HASH_B,
            "eligible_amount_functional": Decimal("-10.0000"),
            "period_id": PERIOD_ID,
            "functional_currency": "KRW",
        },
    ]
    assert build_source_set_hash(pools) == build_source_set_hash(reversed(pools))
    command = CostAllocationRunCommand(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        business_operation_id=OPERATION_ID,
        idempotency_key="one",
        payload_hash=HASH_A,
        batch_id=BATCH_ID,
        plan_id=PLAN_ID,
        plan_revision=1,
        period_id=PERIOD_ID,
        functional_currency="KRW",
        sources=(AllocationSourceInput(POOL_ID, Decimal("0.0000")),),
    )
    changed_transport = CostAllocationRunCommand(
        **{
            **command.__dict__,
            "business_operation_id": str(uuid.uuid4()),
            "idempotency_key": "two",
            "payload_hash": HASH_B,
        }
    )
    assert cost_allocation_payload_hash(command) == cost_allocation_payload_hash(
        changed_transport
    )


def test_cost_allocation_api_created_replay_verify_and_failure_paths(monkeypatch):
    engine, _sessions, service, reconciliation = _runtime()
    monkeypatch.setattr(
        cost_allocation_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(subject="nex-ae-api"),
    )
    app = FastAPI()
    register_cost_allocation_routes(app)
    app.state.eos_cost_allocation_service = service
    app.state.eos_allocation_reconciliation_service = reconciliation
    headers = {
        "Authorization": "Bearer signed-service-token",
        "X-NeX-Tenant-Id": TENANT,
        "X-NeX-Company-Id": COMPANY_ID,
    }
    with TestClient(app) as client:
        created = client.post(
            "/internal/v2/finance/cost-allocation-batches",
            headers=headers,
            json=_payload(),
        )
        replay = client.post(
            "/internal/v2/finance/cost-allocation-batches",
            headers=headers,
            json=_payload(),
        )
        verified = client.get(
            f"/internal/v2/finance/cost-allocation-batches/{BATCH_ID}/verification",
            headers=headers,
        )
        invalid = client.post(
            "/internal/v2/finance/cost-allocation-batches",
            headers=headers,
            json={"bad": True},
        )
        invalid_verify = client.get(
            "/internal/v2/finance/cost-allocation-batches/bad/verification",
            headers=headers,
        )
    assert created.status_code == 201
    assert replay.status_code == 200
    assert verified.status_code == 200
    assert verified.json()["verification_status"] == "VERIFIED"
    assert invalid.status_code == 422
    assert invalid_verify.status_code == 422
    engine.dispose()


def test_api_propagates_token_denial_and_missing_dependencies(monkeypatch):
    app = FastAPI()
    register_cost_allocation_routes(app)
    monkeypatch.setattr(
        cost_allocation_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: cost_allocation_api.JSONResponse(
            {"error_code": "SERVICE_TOKEN_DENIED"}, status_code=403
        ),
    )
    headers = {"X-NeX-Tenant-Id": TENANT, "X-NeX-Company-Id": COMPANY_ID}
    with TestClient(app) as client:
        denied = client.post(
            "/internal/v2/finance/cost-allocation-batches",
            headers=headers,
            json=_payload(),
        )
        denied_verify = client.get(
            f"/internal/v2/finance/cost-allocation-batches/{BATCH_ID}/verification",
            headers=headers,
        )
    assert denied.status_code == 403
    assert denied_verify.status_code == 403

    monkeypatch.setattr(
        cost_allocation_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(subject="nex-ae-api"),
    )
    with TestClient(app) as client:
        unavailable = client.post(
            "/internal/v2/finance/cost-allocation-batches",
            headers=headers,
            json=_payload(),
        )
        verify_unavailable = client.get(
            f"/internal/v2/finance/cost-allocation-batches/{BATCH_ID}/verification",
            headers=headers,
        )
    assert unavailable.status_code == 503
    assert verify_unavailable.status_code == 503


def test_contract_migration_and_openapi_inventory_are_canonical():
    schemas = [
        "cost_allocation_run.v1.schema.json",
        "cost_allocation_batch.v1.schema.json",
        "cost_allocation_reconciliation.v1.schema.json",
        "cost_allocation_committed_event.v1.schema.json",
    ]
    for name in schemas:
        schema = json.loads(
            (ROOT / "contracts/schemas/service/nex_eos" / name).read_text()
        )
        Draft202012Validator.check_schema(schema)
    openapi = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-eos.openapi.yaml").read_text()
    )
    assert (
        openapi["paths"]["/internal/v2/finance/cost-allocation-batches"]["post"][
            "operationId"
        ]
        == "FINANCE.COST_ALLOCATION.RUN"
    )
    assert (
        openapi["paths"][
            "/internal/v2/finance/cost-allocation-batches/{batch_id}/verification"
        ]["get"]["operationId"]
        == "FINANCE.COST_ALLOCATION.VERIFY"
    )
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2541_eos_cost_source_allocation"
    )
    assert "CREATE TABLE IF NOT EXISTS eos_cost_allocation_batch" in migration.sql
    assert "CREATE TABLE IF NOT EXISTS eos_cost_allocation_line" in migration.sql
    assert "CREATE TABLE IF NOT EXISTS eos_cost_allocation_adjustment" in migration.sql
