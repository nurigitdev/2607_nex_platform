from __future__ import annotations

import pytest
from nex_ae_api.accounting_allocation_authority import (
    ACCOUNTING_ALLOCATION_AUTHORITY_SCHEMA,
    AccountingAllocationAuthorityError,
    build_accounting_allocation_authority_checkpoint,
    build_accounting_allocation_work_intent,
    validate_accounting_allocation_authority_checkpoint,
    validate_accounting_allocation_work_intent,
)
from nex_ae_api.m1_accounting_allocation_runtime import (
    AccountingAllocationRuntimeError,
    InstalledAccountingAllocationRuntime,
)
from nex_ae_api.m1_allocation_plan_composition import (
    M1AllocationPlanCompositionError,
    resolve_accounting_allocation_plan_authority,
)

TENANT = "VO00"
COMPANY = "94000000-0000-4000-8000-000000000001"
JOURNAL = "94000000-0000-4000-8000-000000000002"
EXECUTION = "94000000-0000-4000-8000-000000000003"
WORK_INTENT = "94000000-0000-4000-8000-000000000004"
HASH_A = "sha256:" + "a" * 64


def _plain(value):
    if isinstance(value, dict) or hasattr(value, "items"):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _intent(**overrides):
    values = {
        "tenant_id": TENANT,
        "company_id": COMPANY,
        "subject_id": "accountant-1001",
        "execution_id": EXECUTION,
        "work_intent_id": WORK_INTENT,
        "journal_id": JOURNAL,
        "source_record_line_ref": "journal:line:17",
        "source_kind": "SHARED_EXPENSE",
        "projects": [
            {
                "project_code": "VO00D260002",
                "allocation_ratio": "0.625000000000",
            },
            {
                "project_code": "VO00M260001",
                "allocation_ratio": "0.375000000000",
            },
        ],
        "source_ref": "ia:interaction:allocation-17",
        "requested_at": "2026-11-24T01:00:00Z",
        "publication_target": "ACCOUNTING_WORKSPACE",
        "publication_target_ref": "accounting:workspace:team-7",
    }
    values.update(overrides)
    return build_accounting_allocation_work_intent(**values)


def _authorization(**overrides):
    value = {
        "active": True,
        "tenant_id": TENANT,
        "subject_id": "accountant-1001",
        "scopes": ["finance:allocation:execute", "finance:journal:read"],
        "revision_hash": HASH_A,
        "evaluated_at": "2026-11-24T01:00:01Z",
    }
    value.update(overrides)
    return value


def _runtime_job(**overrides):
    value = {
        "runtime_job_id": "94000000-0000-4000-8000-000000000005",
        "job_type": "START_EXECUTION",
        "execution_id": EXECUTION,
        "state": "RUNNING",
        "dedup_key": "allocation:94000000:17",
    }
    value.update(overrides)
    return value


def test_work_intent_is_typed_hash_bound_and_has_stable_replay_identity() -> None:
    first = _intent()
    second = _intent(
        work_intent_id="94000000-0000-4000-8000-000000000006",
        requested_at="2026-11-24T01:01:00Z",
        projects=list(reversed(first["projects"])),
    )

    assert [item["project_code"] for item in first["projects"]] == [
        "VO00D260002",
        "VO00M260001",
    ]
    assert first["replay_identity"] == second["replay_identity"]
    assert first["intent_hash"] != second["intent_hash"]
    assert (
        validate_accounting_allocation_work_intent(first)["intent_hash"]
        == (first["intent_hash"])
    )

    tampered = {
        **dict(first),
        "projects": [dict(item) for item in first["projects"]],
        "publication": dict(first["publication"]),
    }
    tampered["projects"][0]["allocation_ratio"] = "0.500000000000"
    with pytest.raises(AccountingAllocationAuthorityError, match="total exactly one"):
        validate_accounting_allocation_work_intent(tampered)


@pytest.mark.parametrize(
    "overrides",
    [
        {"projects": []},
        {
            "projects": [
                {
                    "project_code": "VO00D260001",
                    "allocation_ratio": "1.000000000000",
                },
                {
                    "project_code": "VO00D260001",
                    "allocation_ratio": "0.000000000000",
                },
            ]
        },
        {"publication_target": "PUBLIC_BROADCAST"},
        {"source_kind": "FIXTURE"},
    ],
)
def test_work_intent_rejects_noncanonical_business_input(overrides) -> None:
    with pytest.raises(AccountingAllocationAuthorityError):
        _intent(**overrides)


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    [
        ("schema_version", "unsupported", "identity"),
        ("company_id", "not-a-uuid", "company_id"),
        ("tenant_id", "bad tenant", "tenant_id"),
        ("requested_at", 17, "requested_at"),
        ("requested_at", "not-a-time", "requested_at"),
        ("requested_at", "2026-11-24T01:00:00", "requested_at"),
        ("replay_identity", HASH_A, "replay identity"),
        ("intent_hash", HASH_A, "WorkIntent hash"),
    ],
)
def test_work_intent_validator_rejects_identity_and_hash_tamper(
    field, value, detail
) -> None:
    document = _plain(_intent())
    document[field] = value
    with pytest.raises(AccountingAllocationAuthorityError, match=detail):
        validate_accounting_allocation_work_intent(document)


@pytest.mark.parametrize(
    "projects",
    [
        [
            {
                "project_code": "invalid",
                "allocation_ratio": "1.000000000000",
            }
        ],
        [
            {
                "project_code": "VO00D260001",
                "allocation_ratio": "not-a-ratio",
            }
        ],
        [
            {
                "project_code": "VO00D260001",
                "allocation_ratio": "0.500000000000",
            },
            {
                "project_code": "VO00D260001",
                "allocation_ratio": "0.500000000000",
            },
        ],
        [{"project_code": "VO00D260001", "allocation_ratio": "1", "extra": 1}],
    ],
)
def test_work_intent_rejects_malformed_project_records(projects) -> None:
    with pytest.raises(AccountingAllocationAuthorityError):
        _intent(projects=projects)


def test_authority_checkpoint_binds_fresh_oa_job_and_exact_replay() -> None:
    intent = _intent()
    checkpoint = build_accounting_allocation_authority_checkpoint(
        work_intent=intent,
        authorization=_authorization(),
        runtime_job=_runtime_job(),
    )

    admitted = validate_accounting_allocation_authority_checkpoint(checkpoint)
    replay = build_accounting_allocation_authority_checkpoint(
        work_intent=intent,
        authorization=_authorization(),
        runtime_job=_runtime_job(),
        existing_checkpoint=checkpoint,
    )

    assert admitted["schema_version"] == ACCOUNTING_ALLOCATION_AUTHORITY_SCHEMA
    assert admitted["work_intent_hash"] == intent["intent_hash"]
    assert admitted["runtime_job"]["runtime_job_id"].endswith("000000000005")
    assert admitted["publication"] == dict(intent["publication"])
    assert replay is checkpoint

    with pytest.raises(
        AccountingAllocationAuthorityError, match="differs from exact replay"
    ):
        build_accounting_allocation_authority_checkpoint(
            work_intent=intent,
            authorization=_authorization(revision_hash="sha256:" + "b" * 64),
            runtime_job=_runtime_job(),
            existing_checkpoint=checkpoint,
        )


@pytest.mark.parametrize(
    ("mutation", "detail"),
    [
        (lambda value: value.update(schema_version="unsupported"), "unsupported"),
        (lambda value: value.update(authority_hash=HASH_A), "authority hash"),
        (
            lambda value: value["oa_authority"].update(required_scope="wrong"),
            "scope drifted",
        ),
        (
            lambda value: value["runtime_job"].update(job_type="UNKNOWN"),
            "job_type",
        ),
        (
            lambda value: value["publication"].update(target="PUBLIC"),
            "publication.target",
        ),
        (lambda value: value.update(extra=True), "fields are not canonical"),
    ],
)
def test_checkpoint_validator_rejects_tamper(mutation, detail) -> None:
    checkpoint = _plain(
        build_accounting_allocation_authority_checkpoint(
            work_intent=_intent(),
            authorization=_authorization(),
            runtime_job=_runtime_job(),
        )
    )
    mutation(checkpoint)
    with pytest.raises(AccountingAllocationAuthorityError, match=detail):
        validate_accounting_allocation_authority_checkpoint(checkpoint)


@pytest.mark.parametrize(
    ("authorization", "runtime_job", "error_code"),
    [
        (None, _runtime_job(), "DENIED"),
        (_authorization(active=False), _runtime_job(), "DENIED"),
        (_authorization(scopes=[]), _runtime_job(), "DENIED"),
        (
            _authorization(subject_id="different-accountant"),
            _runtime_job(),
            "DENIED",
        ),
        (
            _authorization(),
            _runtime_job(execution_id="94000000-0000-4000-8000-000000000099"),
            "INVALID",
        ),
        (_authorization(), None, "INVALID"),
        (_authorization(revision_hash="bad-hash"), _runtime_job(), "INVALID"),
    ],
)
def test_authority_checkpoint_fails_closed_on_oa_or_job_drift(
    authorization, runtime_job, error_code
) -> None:
    with pytest.raises(AccountingAllocationAuthorityError) as caught:
        build_accounting_allocation_authority_checkpoint(
            work_intent=_intent(),
            authorization=authorization,
            runtime_job=runtime_job,
        )
    assert caught.value.error_code.endswith(error_code)


class _ResolutionRuntime:
    def __init__(self) -> None:
        self.calls = []

    def resolve_and_bind_by_project_codes(self, **values):
        self.calls.append(values)
        return {"status": "BOUND", "authority": values["lineage"]}


def test_plan_resolution_uses_independent_authority_and_code_only_projects() -> None:
    intent = _intent()
    checkpoint = build_accounting_allocation_authority_checkpoint(
        work_intent=intent,
        authorization=_authorization(),
        runtime_job=_runtime_job(),
    )
    runtime = _ResolutionRuntime()

    result = resolve_accounting_allocation_plan_authority(
        runtime,
        work_intent=intent,
        allocation_authority_checkpoint=checkpoint,
        source_pool={
            "source_kind": "SHARED_EXPENSE",
            "recognition_date": "2026-11-24",
        },
        correlation_id="allocation:resolve:17",
    )

    call = runtime.calls[0]
    assert result["status"] == "BOUND"
    assert call["projects"] == list(intent["projects"])
    assert all("project_id" not in item for item in call["projects"])
    assert call["lineage"].preparation_hash is None
    assert call["lineage"].allocation_authority_hash == checkpoint["authority_hash"]
    assert call["lineage"].business_context_hash == intent["intent_hash"]

    with pytest.raises(M1AllocationPlanCompositionError, match="source kind"):
        resolve_accounting_allocation_plan_authority(
            runtime,
            work_intent=intent,
            allocation_authority_checkpoint=checkpoint,
            source_pool={
                "source_kind": "PAYROLL",
                "recognition_date": "2026-11-24",
            },
            correlation_id="allocation:resolve:18",
        )


def test_plan_resolution_rejects_invalid_lineage_and_missing_runtime_capability() -> (
    None
):
    intent = _intent()
    checkpoint = build_accounting_allocation_authority_checkpoint(
        work_intent=intent,
        authorization=_authorization(),
        runtime_job=_runtime_job(),
    )

    tampered = _plain(checkpoint)
    tampered["authority_hash"] = HASH_A
    with pytest.raises(M1AllocationPlanCompositionError, match="authority is invalid"):
        resolve_accounting_allocation_plan_authority(
            _ResolutionRuntime(),
            work_intent=intent,
            allocation_authority_checkpoint=tampered,
            source_pool={
                "source_kind": "SHARED_EXPENSE",
                "recognition_date": "2026-11-24",
            },
            correlation_id="allocation:resolve:invalid",
        )

    different_intent = _intent(
        execution_id="94000000-0000-4000-8000-000000000080",
        work_intent_id="94000000-0000-4000-8000-000000000081",
    )
    with pytest.raises(M1AllocationPlanCompositionError, match="lineage differs"):
        resolve_accounting_allocation_plan_authority(
            _ResolutionRuntime(),
            work_intent=different_intent,
            allocation_authority_checkpoint=checkpoint,
            source_pool={
                "source_kind": "SHARED_EXPENSE",
                "recognition_date": "2026-11-24",
            },
            correlation_id="allocation:resolve:lineage",
        )

    with pytest.raises(
        M1AllocationPlanCompositionError, match="resolver is unavailable"
    ):
        resolve_accounting_allocation_plan_authority(
            object(),
            work_intent=intent,
            allocation_authority_checkpoint=checkpoint,
            source_pool={
                "source_kind": "SHARED_EXPENSE",
                "recognition_date": "2026-11-24",
            },
            correlation_id="allocation:resolve:unavailable",
        )

    with pytest.raises(
        M1AllocationPlanCompositionError, match="selector is unavailable"
    ):
        resolve_accounting_allocation_plan_authority(
            _ResolutionRuntime(),
            work_intent=intent,
            allocation_authority_checkpoint=checkpoint,
            source_pool={"source_kind": "SHARED_EXPENSE"},
            correlation_id="allocation:resolve:selector",
        )


class _FinancialResult:
    def __init__(self) -> None:
        self.calls = []

    def integrate(self, **values):
        self.calls.append(values)
        return {
            "journal_ref": f"eos.posted_journal:{JOURNAL}",
            "source_pool_ref": "eos.cost-source-pool:pool-17",
            "source_pool_hash": HASH_A,
            "allocation_batch_ref": "eos.cost-allocation-batch:batch-17",
            "allocation_reconciliation_hash": HASH_A,
            "pnl_refresh_hash": HASH_A,
            "project_results": [
                {
                    "project_code": "VO00D260002",
                    "projection_id": "94000000-0000-4000-8000-000000000009",
                    "projection_version": 1,
                    "projection_hash": HASH_A,
                    "reconciliation_status": "VERIFIED",
                    "freshness_status": "CURRENT",
                    "data_classification": "CONFIDENTIAL_FINANCIAL",
                }
            ],
        }


def test_historical_d04_replay_is_explicit_and_does_not_replace_active_path() -> None:
    financial = _FinancialResult()
    runtime = InstalledAccountingAllocationRuntime(
        integrator=financial,
        authority=type(
            "Authority",
            (),
            {"effective_authorization": lambda _self, **_values: _authorization()},
        )(),
    )

    result = runtime.execute_historical_d04_replay(
        tenant_id=TENANT,
        company_id=COMPANY,
        subject_id="accountant-1001",
        correlation_id="allocation:historical:17",
        journal_id=JOURNAL,
        work_intent={"historical": True},
        preparation_checkpoint={"stage": "READY_FOR_D04"},
    )

    assert result["compatibility_mode"] == "HISTORICAL_D04_REPLAY_ONLY"
    assert financial.calls[0]["preparation_checkpoint"] == {"stage": "READY_FOR_D04"}
    assert "allocation_authority_checkpoint" not in financial.calls[0]


def test_installed_runtime_rejects_invalid_scope_and_historical_authority() -> None:
    runtime = InstalledAccountingAllocationRuntime(
        integrator=_FinancialResult(),
        authority=type(
            "Authority",
            (),
            {
                "effective_authorization": lambda _self, **_values: _authorization(
                    scopes=[]
                )
            },
        )(),
    )
    with pytest.raises(AccountingAllocationRuntimeError, match="company_id"):
        runtime.execute(
            tenant_id=TENANT,
            company_id="not-a-uuid",
            subject_id="accountant-1001",
            correlation_id="allocation:invalid:17",
            journal_id=JOURNAL,
            work_intent=_intent(),
            runtime_job=_runtime_job(),
        )
    with pytest.raises(AccountingAllocationRuntimeError, match="denied"):
        runtime.execute_historical_d04_replay(
            tenant_id=TENANT,
            company_id=COMPANY,
            subject_id="accountant-1001",
            correlation_id="allocation:historical:18",
            journal_id=JOURNAL,
            work_intent={},
            preparation_checkpoint={},
        )


def test_installed_runtime_fails_closed_on_intent_and_authority_drift() -> None:
    financial = _FinancialResult()
    active_runtime = InstalledAccountingAllocationRuntime(
        integrator=financial,
        authority=type(
            "Authority",
            (),
            {"effective_authorization": lambda _self, **_values: _authorization()},
        )(),
    )

    with pytest.raises(AccountingAllocationRuntimeError, match="journal_id"):
        active_runtime.execute(
            tenant_id=TENANT,
            company_id=COMPANY,
            subject_id="accountant-1001",
            correlation_id="allocation:invalid-journal",
            journal_id="not-a-uuid",
            work_intent=_intent(),
            runtime_job=_runtime_job(),
        )

    with pytest.raises(AccountingAllocationRuntimeError, match="scope differs"):
        active_runtime.execute(
            tenant_id=TENANT,
            company_id=COMPANY,
            subject_id="different-accountant",
            correlation_id="allocation:scope-drift",
            journal_id=JOURNAL,
            work_intent=_intent(),
            runtime_job=_runtime_job(),
        )

    invalid_authority_runtime = InstalledAccountingAllocationRuntime(
        integrator=financial,
        authority=type(
            "Authority",
            (),
            {
                "effective_authorization": lambda _self, **_values: _authorization(
                    revision_hash="not-a-hash"
                )
            },
        )(),
    )
    with pytest.raises(AccountingAllocationRuntimeError, match="input is invalid"):
        invalid_authority_runtime.execute(
            tenant_id=TENANT,
            company_id=COMPANY,
            subject_id="accountant-1001",
            correlation_id="allocation:invalid-authority",
            journal_id=JOURNAL,
            work_intent=_intent(),
            runtime_job=_runtime_job(),
        )

    with pytest.raises(AccountingAllocationRuntimeError, match="Historical D04"):
        invalid_authority_runtime.execute_historical_d04_replay(
            tenant_id=TENANT,
            company_id=COMPANY,
            subject_id="accountant-1001",
            correlation_id="allocation:historical-invalid-authority",
            journal_id=JOURNAL,
            work_intent={"historical": True},
            preparation_checkpoint={"stage": "READY_FOR_D04"},
        )
