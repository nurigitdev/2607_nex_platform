from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import test_nex_eos_mybee_cost_allocation as base
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from nex_eos import (
    EOS_COST_ALLOCATION_BATCH_TABLE,
    EOS_COST_ALLOCATION_LINE_TABLE,
    EOS_COST_SOURCE_POOL_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_TABLE,
    PROJECT_PNL_REFRESH_OPERATION,
    PROJECT_PNL_REFRESH_SCHEMA,
    EosAllocationPnlRefreshSourceResolver,
    EosAllocationReconciliationError,
    EosProjectPnlRefreshError,
    ProjectPnlRefreshSource,
)
from sqlalchemy import func, select, update

ROOT = Path(__file__).resolve().parents[1]
NVT_PROJECT_ID = "73000000-0000-4000-8000-000000000009"


class _StaticReconciliation:
    def __init__(self, value=None, error: Exception | None = None) -> None:
        self.value = value
        self.error = error

    def verify_batch(self, **_kwargs):
        if self.error is not None:
            raise self.error
        return self.value


def _runtime():
    engine, sessions, service, reconciliation = base._runtime()
    EOS_NVT_PROJECT_TABLE.create(engine, checkfirst=True)
    EOS_PROJECT_TABLE.create(engine, checkfirst=True)
    with sessions.begin() as session:
        session.execute(
            EOS_NVT_PROJECT_TABLE.insert().values(
                tenant_id=base.TENANT,
                nvt_project_id=NVT_PROJECT_ID,
                nvt_project_code="NVT-D04",
                name="D04 Finance",
                status="ACTIVE",
                version=1,
                created_at=base.NOW,
                updated_at=base.NOW,
            )
        )
        for project_id, project_code, name in (
            (base.PROJECT_A, "VO00D260001", "Project A"),
            (base.PROJECT_B, "VO00D260002", "Project B"),
            (base.PROJECT_C, "VO00D260003", "Project C"),
        ):
            session.execute(
                EOS_PROJECT_TABLE.insert().values(
                    tenant_id=base.TENANT,
                    project_id=project_id,
                    project_code=project_code,
                    project_request_code=None,
                    purpose_type="D",
                    origin="LEGACY_DIRECT",
                    approval_evidence_ref=None,
                    approval_evidence_hash=None,
                    project_owner_subject_id=None,
                    project_manager_subject_id=None,
                    agent_sync_state="IN_SYNC",
                    authorization_sync_state="IN_SYNC",
                    authorization_version=1,
                    name=name,
                    parent_project_id=None,
                    nvt_project_id=NVT_PROJECT_ID,
                    hierarchy_depth=1,
                    status="ACTIVE",
                    start_date=None,
                    end_date=None,
                    currency="KRW",
                    version=1,
                    created_at=base.NOW,
                    updated_at=base.NOW,
                )
            )
    resolver = EosAllocationPnlRefreshSourceResolver(
        session_factory=sessions,
        reconciliation=reconciliation,
    )
    return engine, sessions, service, reconciliation, resolver


def _counts(sessions) -> tuple[int, int, int, int]:
    with sessions() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(table))
            for table in (
                EOS_COST_ALLOCATION_BATCH_TABLE,
                EOS_COST_ALLOCATION_LINE_TABLE,
                EOS_COST_SOURCE_POOL_TABLE,
                EOS_PROJECT_TABLE,
            )
        )


def _resolve(resolver):
    return resolver.resolve(
        tenant_id=base.TENANT,
        company_id=base.COMPANY_ID,
        batch_id=base.BATCH_ID,
    )


def test_verified_batch_resolves_stable_affected_project_union_without_mutation():
    engine, sessions, service, _reconciliation, resolver = _runtime()
    created = base._run(service, unallocated="10.0000")
    before = _counts(sessions)

    first = _resolve(resolver)
    second = _resolve(resolver)

    assert first == second
    assert first.tenant_id == base.TENANT
    assert first.company_id == base.COMPANY_ID
    assert first.batch_id == base.BATCH_ID
    assert first.period_id == base.PERIOD_ID
    assert first.functional_currency == "KRW"
    assert first.allocation_reconciliation_hash == created["reconciliation_hash"]
    assert first.committed_at == base.NOW
    assert first.pool_ids == (base.POOL_ID,)
    assert [item.project_id for item in first.affected_projects] == [
        base.PROJECT_A,
        base.PROJECT_B,
        base.PROJECT_C,
    ]
    assert first.affected_projects[0].roles == (
        "ALLOCATION_TARGET",
        "SOURCE_PROJECT",
    )
    assert all(
        item.roles == ("ALLOCATION_TARGET",) for item in first.affected_projects[1:]
    )
    assert first.source_resolution_hash.startswith("sha256:")
    assert _counts(sessions) == before
    engine.dispose()


@pytest.mark.parametrize(
    ("tenant_id", "company_id", "batch_id", "expected_code"),
    (
        (
            "OTHER",
            base.COMPANY_ID,
            base.BATCH_ID,
            "EOS_PROJECT_PNL_REFRESH_BATCH_NOT_FOUND",
        ),
        (
            base.TENANT,
            "73000000-0000-4000-8000-000000000099",
            base.BATCH_ID,
            "EOS_PROJECT_PNL_REFRESH_BATCH_NOT_FOUND",
        ),
        (base.TENANT, base.COMPANY_ID, "bad", "EOS_PROJECT_PNL_REFRESH_INVALID"),
        (" bad ", base.COMPANY_ID, base.BATCH_ID, "EOS_PROJECT_PNL_REFRESH_INVALID"),
    ),
)
def test_scope_and_identity_probes_fail_closed(
    tenant_id: str, company_id: str, batch_id: str, expected_code: str
):
    engine, _sessions, service, _reconciliation, resolver = _runtime()
    base._run(service)

    with pytest.raises(EosProjectPnlRefreshError) as rejected:
        resolver.resolve(
            tenant_id=tenant_id,
            company_id=company_id,
            batch_id=batch_id,
        )

    assert rejected.value.error_code == expected_code
    assert rejected.value.status_code in {404, 422}
    engine.dispose()


@pytest.mark.parametrize("tamper", ("line", "reversed"))
def test_failed_or_adjustment_required_verification_cannot_resolve(tamper: str):
    engine, sessions, service, _reconciliation, resolver = _runtime()
    base._run(service)
    with sessions.begin() as session:
        if tamper == "line":
            session.execute(
                update(EOS_COST_ALLOCATION_LINE_TABLE)
                .where(EOS_COST_ALLOCATION_LINE_TABLE.c.line_no == 1)
                .values(evidence_hash=base.HASH_B)
            )
        else:
            session.execute(
                update(EOS_COST_SOURCE_POOL_TABLE).values(pool_state="REVERSED")
            )

    with pytest.raises(EosProjectPnlRefreshError) as rejected:
        _resolve(resolver)

    assert rejected.value.error_code == "EOS_PROJECT_PNL_REFRESH_BATCH_NOT_VERIFIED"
    assert rejected.value.status_code == 409
    engine.dispose()


@pytest.mark.parametrize("tamper", ("project_code", "missing_project", "source_code"))
def test_post_verification_lineage_drift_is_rejected(tamper: str):
    engine, sessions, service, reconciliation, _resolver = _runtime()
    base._run(service)
    verified = reconciliation.verify_batch(
        tenant_id=base.TENANT,
        company_id=base.COMPANY_ID,
        batch_id=base.BATCH_ID,
    )
    with sessions.begin() as session:
        if tamper == "project_code":
            session.execute(
                update(EOS_PROJECT_TABLE)
                .where(EOS_PROJECT_TABLE.c.project_id == base.PROJECT_A)
                .values(project_code="VO00D269999")
            )
        elif tamper == "missing_project":
            session.execute(
                EOS_PROJECT_TABLE.delete().where(
                    EOS_PROJECT_TABLE.c.project_id == base.PROJECT_C
                )
            )
        else:
            session.execute(
                update(EOS_COST_SOURCE_POOL_TABLE).values(
                    source_project_code="VO00D269999"
                )
            )
    resolver = EosAllocationPnlRefreshSourceResolver(
        session_factory=sessions,
        reconciliation=_StaticReconciliation(verified),
    )

    with pytest.raises(EosProjectPnlRefreshError) as rejected:
        _resolve(resolver)

    assert rejected.value.error_code == "EOS_PROJECT_PNL_REFRESH_SOURCE_DRIFT"
    assert rejected.value.status_code == 409
    engine.dispose()


@pytest.mark.parametrize(
    "tamper",
    (
        "missing_batch",
        "missing_line",
        "verified_scope",
        "verified_evidence",
        "business_operation",
        "line_state",
        "pool_state",
    ),
)
def test_post_verification_race_matrix_fails_closed(tamper: str):
    engine, sessions, service, reconciliation, _resolver = _runtime()
    base._run(service)
    verified = copy.deepcopy(
        reconciliation.verify_batch(
            tenant_id=base.TENANT,
            company_id=base.COMPANY_ID,
            batch_id=base.BATCH_ID,
        )
    )
    with sessions.begin() as session:
        if tamper == "missing_batch":
            session.execute(EOS_COST_ALLOCATION_BATCH_TABLE.delete())
        elif tamper == "missing_line":
            session.execute(
                EOS_COST_ALLOCATION_LINE_TABLE.delete().where(
                    EOS_COST_ALLOCATION_LINE_TABLE.c.line_no == 1
                )
            )
        elif tamper == "verified_scope":
            verified["batch"]["company_id"] = "73000000-0000-4000-8000-000000000099"
        elif tamper == "verified_evidence":
            verified["batch"]["plan_id"] = "73000000-0000-4000-8000-000000000099"
        elif tamper == "business_operation":
            verified["business_operation_id"] = "73000000-0000-4000-8000-000000000099"
        elif tamper == "line_state":
            session.execute(
                update(EOS_COST_ALLOCATION_LINE_TABLE).values(status="REVERSED")
            )
        else:
            session.execute(
                update(EOS_COST_SOURCE_POOL_TABLE).values(pool_state="ON_HOLD")
            )
    resolver = EosAllocationPnlRefreshSourceResolver(
        session_factory=sessions,
        reconciliation=_StaticReconciliation(verified),
    )

    with pytest.raises(EosProjectPnlRefreshError) as rejected:
        _resolve(resolver)

    expected = (
        "EOS_PROJECT_PNL_REFRESH_BATCH_NOT_FOUND"
        if tamper == "missing_batch"
        else "EOS_PROJECT_PNL_REFRESH_SOURCE_DRIFT"
    )
    assert rejected.value.error_code == expected
    engine.dispose()


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    (
        (404, "EOS_PROJECT_PNL_REFRESH_BATCH_NOT_FOUND", False),
        (422, "EOS_PROJECT_PNL_REFRESH_INVALID", False),
        (409, "EOS_PROJECT_PNL_REFRESH_BATCH_NOT_VERIFIED", False),
        (503, "EOS_PROJECT_PNL_REFRESH_SOURCE_UNAVAILABLE", True),
    ),
)
def test_reconciliation_errors_map_to_bounded_refresh_errors(
    status_code: int, expected_code: str, retryable: bool
):
    engine, sessions, _service, _reconciliation, _resolver = _runtime()
    resolver = EosAllocationPnlRefreshSourceResolver(
        session_factory=sessions,
        reconciliation=_StaticReconciliation(
            error=EosAllocationReconciliationError(
                "RECONCILIATION_ERROR",
                "bounded failure",
                status_code=status_code,
                retryable=retryable,
            )
        ),
    )

    with pytest.raises(EosProjectPnlRefreshError) as rejected:
        _resolve(resolver)

    assert rejected.value.error_code == expected_code
    assert rejected.value.retryable is retryable
    engine.dispose()


def test_malformed_verification_and_unavailable_persistence_are_typed():
    engine, sessions, service, reconciliation, _resolver = _runtime()
    base._run(service)
    malformed = EosAllocationPnlRefreshSourceResolver(
        session_factory=sessions,
        reconciliation=_StaticReconciliation([]),
    )
    with pytest.raises(EosProjectPnlRefreshError) as drift:
        _resolve(malformed)
    assert drift.value.error_code == "EOS_PROJECT_PNL_REFRESH_SOURCE_DRIFT"

    verified = reconciliation.verify_batch(
        tenant_id=base.TENANT,
        company_id=base.COMPANY_ID,
        batch_id=base.BATCH_ID,
    )
    unavailable = EosAllocationPnlRefreshSourceResolver(
        session_factory=sessions,
        reconciliation=_StaticReconciliation(verified),
    )
    engine.dispose()
    with pytest.raises(EosProjectPnlRefreshError) as failed:
        _resolve(unavailable)
    assert failed.value.error_code == "EOS_PROJECT_PNL_REFRESH_SOURCE_UNAVAILABLE"
    assert failed.value.retryable is True


def test_refresh_source_rejects_non_datetime_commit_boundary():
    source = ProjectPnlRefreshSource(
        tenant_id=base.TENANT,
        company_id=base.COMPANY_ID,
        business_operation_id=base.OPERATION_ID,
        batch_id=base.BATCH_ID,
        plan_id=base.PLAN_ID,
        plan_revision=1,
        period_id=base.PERIOD_ID,
        functional_currency="KRW",
        allocation_reconciliation_hash=base.HASH_A,
        source_set_hash=base.HASH_B,
        committed_at=None,  # type: ignore[arg-type]
        pool_ids=(base.POOL_ID,),
        affected_projects=(),
        source_resolution_hash="",
    )

    with pytest.raises(EosProjectPnlRefreshError) as rejected:
        source.semantic_payload()

    assert rejected.value.error_code == "EOS_PROJECT_PNL_REFRESH_SOURCE_DRIFT"


def test_refresh_contract_schema_example_and_openapi_are_canonical():
    schema = json.loads(
        (
            ROOT / "contracts/schemas/service/nex_eos/"
            "project_pnl_refresh_from_allocation.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    example = json.loads(
        (
            ROOT / "contracts/examples/service/"
            "eos_project_pnl_refresh_from_allocation.created.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
    assert example["schema_version"] == PROJECT_PNL_REFRESH_SCHEMA
    assert example["operation"] == PROJECT_PNL_REFRESH_OPERATION

    spec = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    operation = spec["paths"][
        "/internal/v2/finance/cost-allocation-batches/{batch_id}:refresh-project-pnl"
    ]["post"]
    assert operation["operationId"] == PROJECT_PNL_REFRESH_OPERATION
    assert operation["x-nex-side-effect-free"] is False
    assert operation["x-nex-request-selector"] == "BATCH_ID_ONLY"
    assert "requestBody" not in operation
    assert {(item["in"], item["name"]) for item in operation["parameters"]} == {
        ("path", "batch_id"),
        ("header", "X-NeX-Tenant-Id"),
        ("header", "X-NeX-Company-Id"),
        ("header", "X-NeX-Correlation-Id"),
    }
    assert set(operation["responses"]) == {
        "200",
        "201",
        "400",
        "401",
        "404",
        "409",
        "422",
        "503",
    }
    component = spec["components"]["schemas"]["ProjectPnlRefreshFromAllocation"]
    assert component["x-nex-canonical-json-schema"].endswith(
        "project_pnl_refresh_from_allocation.v1.schema.json"
    )


def test_dependency_composition_exposes_source_resolver_without_route_activation():
    from nex_eos.app import create_eos_app
    from nex_eos.config import EosSettings

    settings = EosSettings(
        service_id="nex-eos",
        profile="test",
        version="test",
        build_sha="test",
        database_env="NEX_EOS_DATABASE_URL",
    )
    app = create_eos_app(environ={}, settings=settings)

    assert app.state.eos_project_pnl_refresh_source_resolver is None
    assert not any(
        getattr(route, "operation_id", None) == PROJECT_PNL_REFRESH_OPERATION
        for route in app.routes
    )
