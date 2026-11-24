from __future__ import annotations

import io
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from urllib.error import HTTPError, URLError

import mybee_ax.integrations.nex_allocation_plan_client as client_module
import nex_ae_api.allocation_plan_resolution_runtime as runtime_module
import pytest
from mybee_ax.integrations import (
    ALLOCATION_PLAN_RESOLUTION_BY_CODE_SCHEMA,
    ALLOCATION_PLAN_RESOLUTION_SCHEMA,
    ALLOCATION_PLAN_RESOLVE_BY_CODE_SCHEMA,
    ALLOCATION_PLAN_RESOLVE_OPERATION,
    AllocationPlanConsumerError,
    HttpAllocationPlanProviderTransport,
    NexAllocationPlanResolverClient,
    admit_allocation_plan_resolution,
    build_allocation_plan_resolve_by_code_request,
    build_allocation_plan_resolve_request,
)
from mybee_ax.orchestration import (
    APPROVED_ALLOCATION_PLAN_AUTHORITY_SCHEMA,
    INDEPENDENT_ALLOCATION_PLAN_AUTHORITY_SCHEMA,
    AllocationAuthorityLineage,
    ApprovedAllocationPlanAuthorityBinder,
    ApprovedAllocationPlanAuthorityError,
)
from nex_ae_api.allocation_plan_resolution_runtime import (
    InstalledAllocationPlanResolutionError,
    InstalledApprovedAllocationPlanResolution,
    build_installed_allocation_plan_resolution,
)
from nex_ae_api.m1_allocation_plan_composition import (
    M1AllocationPlanCompositionError,
    resolve_m1_allocation_plan_authority,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


@dataclass(frozen=True)
class _Scenario:
    tenant_id: str
    company_id: str
    source_kind: str
    effective_on: str
    projects: tuple[dict[str, str], ...]
    plan_id: str
    source_project_id: str
    source_project_code: str


SCENARIOS = (
    _Scenario(
        tenant_id="T101",
        company_id="11000000-0000-4000-8000-000000000001",
        source_kind="SERVICE",
        effective_on="2026-10-21",
        projects=(
            {
                "project_id": "11000000-0000-4000-8000-000000000011",
                "project_code": "T101M260102",
                "allocation_ratio": "0.750000000000",
            },
            {
                "project_id": "11000000-0000-4000-8000-000000000010",
                "project_code": "T101D260101",
                "allocation_ratio": "0.250000000000",
            },
        ),
        plan_id="11000000-0000-4000-8000-000000000020",
        source_project_id="11000000-0000-4000-8000-000000000090",
        source_project_code="T101O269901",
    ),
    _Scenario(
        tenant_id="Z9K2",
        company_id="22000000-0000-4000-8000-000000000001",
        source_kind="PAYROLL",
        effective_on="2027-02-28",
        projects=(
            {
                "project_id": "22000000-0000-4000-8000-000000000013",
                "project_code": "Z9K2I270203",
                "allocation_ratio": "0.500000000000",
            },
            {
                "project_id": "22000000-0000-4000-8000-000000000011",
                "project_code": "Z9K2S270201",
                "allocation_ratio": "0.200000000000",
            },
            {
                "project_id": "22000000-0000-4000-8000-000000000012",
                "project_code": "Z9K2G270202",
                "allocation_ratio": "0.300000000000",
            },
        ),
        plan_id="22000000-0000-4000-8000-000000000020",
        source_project_id="22000000-0000-4000-8000-000000000090",
        source_project_code="Z9K2O279901",
    ),
)


def _request(scenario: _Scenario):
    return build_allocation_plan_resolve_request(
        tenant_id=scenario.tenant_id,
        company_id=scenario.company_id,
        source_kind=scenario.source_kind,
        effective_on=scenario.effective_on,
        projects=scenario.projects,
        correlation_id=f"allocation:{scenario.tenant_id}:17",
    )


def _resolution(scenario: _Scenario, request=None) -> dict[str, object]:
    request = request or _request(scenario)
    project_ids = {
        project["project_code"]: project["project_id"] for project in scenario.projects
    }
    lines: list[dict[str, object]] = []
    for line_no, project in enumerate(request.body["projects"], 1):
        project_id = project.get("project_id") or project_ids[project["project_code"]]
        semantics = {
            "line_no": line_no,
            "project_id": project_id,
            "project_code": project["project_code"],
            "work_code": None,
            "basis_units": f"{line_no}.00000000",
            "allocation_ratio": project["allocation_ratio"],
            "eligibility_hash": semantic_sha256_hash_ref(
                {"project_id": project_id, "eligible": True}
            ),
            "confidentiality_class": "INTERNAL",
        }
        lines.append(
            {
                **semantics,
                "line_hash": semantic_sha256_hash_ref(
                    {"domain": "EOS-COST-ALLOCATION-PLAN-LINE-V1", **semantics}
                ),
            }
        )
    response: dict[str, object] = {
        "schema_version": (
            ALLOCATION_PLAN_RESOLUTION_BY_CODE_SCHEMA
            if request.body["schema_version"] == ALLOCATION_PLAN_RESOLVE_BY_CODE_SCHEMA
            else ALLOCATION_PLAN_RESOLUTION_SCHEMA
        ),
        "operation": ALLOCATION_PLAN_RESOLVE_OPERATION,
        "resolution_disposition": "EXACT_MATCH",
        "selector_hash": semantic_sha256_hash_ref(
            {
                "domain": (
                    "EOS-COST-ALLOCATION-PLAN-RESOLVE-V2"
                    if request.body["schema_version"]
                    == ALLOCATION_PLAN_RESOLVE_BY_CODE_SCHEMA
                    else "EOS-COST-ALLOCATION-PLAN-RESOLVE-V1"
                ),
                "schema_version": request.body["schema_version"],
                "tenant_id": request.tenant_id,
                "company_id": request.company_id,
                "source_kind": request.body["source_kind"],
                "scope_type": request.body["scope_type"],
                "effective_on": request.body["effective_on"],
                "projects": list(request.body["projects"]),
            }
        ),
        "resolution_hash": HASH_A,
        "tenant_id": request.tenant_id,
        "company_id": request.company_id,
        "plan_id": scenario.plan_id,
        "plan_revision": len(scenario.projects) + 2,
        "source_kind": request.body["source_kind"],
        "scope_type": "PROJECT_SET",
        "basis_kind": "APPROVED_PLAN",
        "basis_priority": 2,
        "rule_release_hash": semantic_sha256_hash_ref(
            {"tenant_id": scenario.tenant_id, "rule": "approved-plan"}
        ),
        "basis_source_ref": f"EOS:ALLOCATION_BASIS:{scenario.plan_id}",
        "basis_source_hash": semantic_sha256_hash_ref(
            {"plan_id": scenario.plan_id, "revision": len(scenario.projects) + 2}
        ),
        "effective_start": scenario.effective_on,
        "effective_end": None,
        "approved_by": f"finance-approver-{scenario.tenant_id.lower()}",
        "approved_proof": f"eos.approval-proof:{uuid.uuid5(uuid.NAMESPACE_DNS, scenario.tenant_id)}",
        "state": "APPROVED",
        "plan_hash": HASH_B,
        "created_at": f"{scenario.effective_on}T00:00:00Z",
        "lines": lines,
    }
    response["plan_hash"] = semantic_sha256_hash_ref(
        {
            "domain": "EOS-COST-ALLOCATION-PLAN-V1",
            **{
                name: response[name]
                for name in (
                    "tenant_id",
                    "company_id",
                    "plan_id",
                    "plan_revision",
                    "source_kind",
                    "scope_type",
                    "basis_kind",
                    "rule_release_hash",
                    "basis_source_ref",
                    "basis_source_hash",
                    "effective_start",
                    "effective_end",
                )
            },
            "lines": lines,
        }
    )
    response["resolution_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in response.items() if key != "resolution_hash"}
    )
    return response


def _rehash_resolution(response: dict[str, object]) -> None:
    for line in response["lines"]:
        line["line_hash"] = semantic_sha256_hash_ref(
            {
                "domain": "EOS-COST-ALLOCATION-PLAN-LINE-V1",
                **{key: value for key, value in line.items() if key != "line_hash"},
            }
        )
    response["plan_hash"] = semantic_sha256_hash_ref(
        {
            "domain": "EOS-COST-ALLOCATION-PLAN-V1",
            **{
                name: response[name]
                for name in (
                    "tenant_id",
                    "company_id",
                    "plan_id",
                    "plan_revision",
                    "source_kind",
                    "scope_type",
                    "basis_kind",
                    "rule_release_hash",
                    "basis_source_ref",
                    "basis_source_hash",
                    "effective_start",
                    "effective_end",
                )
            },
            "lines": response["lines"],
        }
    )
    response["resolution_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in response.items() if key != "resolution_hash"}
    )


def _source_pool(scenario: _Scenario) -> dict[str, object]:
    namespace = uuid.UUID(scenario.company_id)
    return {
        "schema_version": "eos_cost_source_pool.v1",
        "operation": "FINANCE.COST_SOURCE_POOL.GET",
        "idempotency_disposition": "EXACT_REPLAY",
        "tenant_id": scenario.tenant_id,
        "company_id": scenario.company_id,
        "pool_id": str(uuid.uuid5(namespace, "pool")),
        "journal_id": str(uuid.uuid5(namespace, "journal")),
        "journal_line_no": len(scenario.projects),
        "eligible_component_id": f"component:{scenario.source_kind.lower()}",
        "source_business_operation_id": str(uuid.uuid5(namespace, "operation")),
        "source_project_id": scenario.source_project_id,
        "source_project_code": scenario.source_project_code,
        "source_kind": scenario.source_kind,
        "allocation_mode": "MANAGEMENT_ALLOCATION",
        "source_amount_functional": "785000.0000",
        "eligible_amount_functional": "780000.0000",
        "functional_currency": "KRW",
        "account_id": str(uuid.uuid5(namespace, "account")),
        "account_category": "EXPENSE",
        "monetary_class": "MONETARY",
        "recognition_date": scenario.effective_on,
        "recognized_at": f"{scenario.effective_on}T01:00:00Z",
        "period_id": str(uuid.uuid5(namespace, "period")),
        "source_record_ref": f"EOS:POSTED_JOURNAL:{scenario.tenant_id}:17",
        "source_hash": semantic_sha256_hash_ref(
            {"tenant": scenario.tenant_id, "source": scenario.source_kind}
        ),
        "eligibility_policy_hash": semantic_sha256_hash_ref(
            {"tenant": scenario.tenant_id, "policy": "allocation"}
        ),
        "pool_state": "OPEN",
        "source_journal_hash": semantic_sha256_hash_ref(
            {"tenant": scenario.tenant_id, "journal": 17}
        ),
        "created_at": f"{scenario.effective_on}T01:01:00Z",
    }


class _Transport:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return self.response


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_generic_client_admits_varied_exact_authority(scenario: _Scenario) -> None:
    request = _request(scenario)
    transport = _Transport(_resolution(scenario, request))

    admitted = NexAllocationPlanResolverClient(transport).resolve_request(request)

    assert transport.requests == [request]
    assert tuple(item["project_code"] for item in request.body["projects"]) == tuple(
        sorted(item["project_code"] for item in scenario.projects)
    )
    assert admitted["tenant_id"] == scenario.tenant_id
    assert admitted["source_kind"] == scenario.source_kind
    assert len(admitted["lines"]) == len(scenario.projects)
    assert isinstance(admitted, MappingProxyType)


def test_generic_client_resolve_entrypoint_and_effective_end() -> None:
    scenario = SCENARIOS[0]
    request = _request(scenario)
    response = _resolution(scenario, request)
    response["effective_end"] = scenario.effective_on
    _rehash_resolution(response)
    transport = _Transport(response)

    result = NexAllocationPlanResolverClient(transport).resolve(
        tenant_id=scenario.tenant_id,
        company_id=scenario.company_id,
        source_kind=scenario.source_kind,
        effective_on=scenario.effective_on,
        projects=scenario.projects,
        correlation_id="allocation:entrypoint:17",
    )

    assert result["effective_end"] == scenario.effective_on
    assert transport.requests[0].correlation_id == "allocation:entrypoint:17"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_code_based_client_admits_eos_authoritative_project_ids(
    scenario: _Scenario,
) -> None:
    request = build_allocation_plan_resolve_by_code_request(
        tenant_id=scenario.tenant_id,
        company_id=scenario.company_id,
        source_kind=scenario.source_kind,
        effective_on=scenario.effective_on,
        projects=tuple(
            {
                "project_code": item["project_code"],
                "allocation_ratio": item["allocation_ratio"],
            }
            for item in scenario.projects
        ),
        correlation_id=f"allocation:code:{scenario.tenant_id}",
    )
    transport = _Transport(_resolution(scenario, request))

    admitted = NexAllocationPlanResolverClient(transport).resolve_request(request)

    assert request.body["schema_version"] == ALLOCATION_PLAN_RESOLVE_BY_CODE_SCHEMA
    assert all("project_id" not in item for item in request.body["projects"])
    assert admitted["schema_version"] == ALLOCATION_PLAN_RESOLUTION_BY_CODE_SCHEMA
    assert {
        (line["project_id"], line["project_code"]) for line in admitted["lines"]
    } == {(item["project_id"], item["project_code"]) for item in scenario.projects}


def test_independent_binder_uses_allocation_authority_not_d04_preparation() -> None:
    scenario = SCENARIOS[0]
    request = build_allocation_plan_resolve_by_code_request(
        tenant_id=scenario.tenant_id,
        company_id=scenario.company_id,
        source_kind=scenario.source_kind,
        effective_on=scenario.effective_on,
        projects=tuple(
            {
                "project_code": item["project_code"],
                "allocation_ratio": item["allocation_ratio"],
            }
            for item in scenario.projects
        ),
        correlation_id="allocation:independent:17",
    )
    admitted = admit_allocation_plan_resolution(
        _resolution(scenario, request), request=request
    )

    checkpoint = ApprovedAllocationPlanAuthorityBinder().bind(
        request=request,
        resolution=admitted,
        source_pool=_source_pool(scenario),
        lineage=AllocationAuthorityLineage(
            business_context_hash=HASH_A,
            allocation_authority_hash=HASH_C,
        ),
    )

    assert checkpoint["schema_version"] == (
        INDEPENDENT_ALLOCATION_PLAN_AUTHORITY_SCHEMA
    )
    assert checkpoint["allocation_authority_hash"] == HASH_C
    assert "preparation_hash" not in checkpoint
    assert {
        (item["project_id"], item["project_code"])
        for item in checkpoint["allocation_plan"]["project_refs"]
    } == {(item["project_id"], item["project_code"]) for item in scenario.projects}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_id", "not-a-uuid"),
        ("source_kind", "UNREGISTERED"),
        ("effective_on", "not-a-date"),
        ("correlation_id", "bad value"),
    ],
)
def test_generic_request_rejects_invalid_selector_fields(field, value) -> None:
    scenario = SCENARIOS[0]
    values = {
        "tenant_id": scenario.tenant_id,
        "company_id": scenario.company_id,
        "source_kind": scenario.source_kind,
        "effective_on": scenario.effective_on,
        "projects": scenario.projects,
        "correlation_id": "request:17",
    }
    values[field] = value

    with pytest.raises(AllocationPlanConsumerError) as caught:
        build_allocation_plan_resolve_request(**values)

    assert caught.value.status_code == 400
    assert caught.value.error_code == "MYBEE_ALLOCATION_PLAN_REQUEST_INVALID"


@pytest.mark.parametrize(
    "projects",
    [
        (),
        "not-a-project-set",
        (
            {
                "project_id": SCENARIOS[0].projects[0]["project_id"],
                "project_code": SCENARIOS[0].projects[0]["project_code"],
                "allocation_ratio": "1.000000000000",
                "extra": True,
            },
        ),
        (
            {
                "project_id": SCENARIOS[0].projects[0]["project_id"],
                "project_code": SCENARIOS[0].projects[0]["project_code"],
                "allocation_ratio": "0.900000000000",
            },
        ),
        (SCENARIOS[0].projects[0], SCENARIOS[0].projects[0]),
    ],
)
def test_generic_request_rejects_noncanonical_project_sets(projects) -> None:
    scenario = SCENARIOS[0]
    with pytest.raises(AllocationPlanConsumerError) as caught:
        build_allocation_plan_resolve_request(
            tenant_id=scenario.tenant_id,
            company_id=scenario.company_id,
            source_kind=scenario.source_kind,
            effective_on=scenario.effective_on,
            projects=projects,
            correlation_id="request:18",
        )
    assert caught.value.status_code == 400


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_id", "bad-uuid"),
        ("project_code", "invalid"),
        ("allocation_ratio", "0.250000"),
    ],
)
def test_generic_request_rejects_malformed_project_values(field, value) -> None:
    scenario = SCENARIOS[0]
    projects = [dict(item) for item in scenario.projects]
    projects[0][field] = value
    with pytest.raises(AllocationPlanConsumerError):
        build_allocation_plan_resolve_request(
            tenant_id=scenario.tenant_id,
            company_id=scenario.company_id,
            source_kind=scenario.source_kind,
            effective_on=scenario.effective_on,
            projects=projects,
            correlation_id="request:19",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(tenant_id="OTHER"),
        lambda value: value.update(plan_id="bad-uuid"),
        lambda value: value.update(plan_revision=0),
        lambda value: value.update(basis_kind="UNSUPPORTED"),
        lambda value: value.update(basis_priority=4),
        lambda value: value.update(rule_release_hash="bad-hash"),
        lambda value: value.update(basis_source_ref=""),
        lambda value: value.update(approved_proof="not-proof"),
        lambda value: value.update(effective_start=None),
        lambda value: value.update(effective_start="2099-01-01"),
        lambda value: value.update(created_at=None),
        lambda value: value.update(created_at="not-a-time"),
        lambda value: value.update(created_at="2026-10-21T00:00:00"),
        lambda value: value.update(lines=[]),
        lambda value: value["lines"][0].update(line_no=2),
        lambda value: value["lines"][0].update(project_code="invalid"),
        lambda value: value["lines"][0].update(basis_units="1"),
        lambda value: value["lines"][0].update(allocation_ratio="0.010000000000"),
        lambda value: value["lines"][0].update(line_hash=HASH_A),
        lambda value: value.update(selector_hash=HASH_A),
        lambda value: value.update(plan_hash=HASH_A),
        lambda value: value.update(resolution_hash=HASH_A),
        lambda value: value.update(extra="drift"),
    ],
)
def test_generic_client_fails_closed_on_provider_drift(mutation) -> None:
    scenario = SCENARIOS[0]
    request = _request(scenario)
    response = _resolution(scenario, request)
    mutation(response)

    with pytest.raises(AllocationPlanConsumerError) as caught:
        admit_allocation_plan_resolution(response, request=request)

    assert caught.value.error_code == "MYBEE_ALLOCATION_PLAN_RESPONSE_INVALID"
    assert caught.value.status_code == 502


def test_generic_client_rejects_exactly_hashed_project_set_drift() -> None:
    scenario = SCENARIOS[0]
    request = _request(scenario)
    response = _resolution(scenario, request)
    response["lines"][0]["allocation_ratio"] = "0.100000000000"
    response["lines"][1]["allocation_ratio"] = "0.900000000000"
    _rehash_resolution(response)
    with pytest.raises(AllocationPlanConsumerError, match="Project set"):
        admit_allocation_plan_resolution(response, request=request)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_generic_authority_binder_is_scenario_neutral_and_replay_safe(
    scenario: _Scenario,
) -> None:
    request = _request(scenario)
    resolution = admit_allocation_plan_resolution(
        _resolution(scenario, request), request=request
    )
    source_pool = _source_pool(scenario)
    binder = ApprovedAllocationPlanAuthorityBinder()
    lineage = AllocationAuthorityLineage(HASH_A, HASH_B)

    first = binder.bind(
        request=request,
        resolution=resolution,
        source_pool=source_pool,
        lineage=lineage,
    )
    replay = binder.bind(
        request=request,
        resolution=resolution,
        source_pool=source_pool,
        lineage=lineage,
        existing_checkpoint=first,
    )

    assert replay is first
    assert first["schema_version"] == APPROVED_ALLOCATION_PLAN_AUTHORITY_SCHEMA
    assert first["stage"] == "READY_FOR_ALLOCATION"
    assert first["source_pool"]["source_kind"] == scenario.source_kind
    assert first["allocation_plan"]["plan_id"] == scenario.plan_id
    assert scenario.source_project_id not in {
        item["project_id"] for item in request.body["projects"]
    }
    assert "source_project_id" not in first["allocation_plan"]

    changed_pool = {**source_pool, "source_hash": HASH_C}
    with pytest.raises(ApprovedAllocationPlanAuthorityError) as caught:
        binder.bind(
            request=request,
            resolution=resolution,
            source_pool=changed_pool,
            lineage=lineage,
            existing_checkpoint=first,
        )
    assert caught.value.error_code == "ALLOCATION_PLAN_AUTHORITY_REPLAY_CONFLICT"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(tenant_id="OTHER"),
        lambda value: value.update(allocation_mode="DIRECT"),
        lambda value: value.update(pool_state="ALLOCATED"),
        lambda value: value.update(source_kind="OTHER"),
        lambda value: value.update(recognition_date="2030-01-01"),
        lambda value: value.update(source_amount_functional="not-money"),
        lambda value: value.update(company_id="bad-uuid"),
        lambda value: value.update(journal_line_no=0),
        lambda value: value.update(eligible_component_id=""),
        lambda value: value.update(source_project_code="invalid"),
        lambda value: value.update(functional_currency="won"),
        lambda value: value.update(account_category="ASSET"),
        lambda value: value.update(monetary_class="UNKNOWN"),
        lambda value: value.update(recognition_date="not-a-date"),
        lambda value: value.update(recognized_at="not-a-time"),
        lambda value: value.update(created_at="2026-10-21T01:00:00"),
        lambda value: value.update(source_hash="bad-hash"),
        lambda value: value.update(extra="drift"),
    ],
)
def test_generic_authority_binder_rejects_source_pool_drift(mutation) -> None:
    scenario = SCENARIOS[0]
    request = _request(scenario)
    source_pool = _source_pool(scenario)
    mutation(source_pool)
    with pytest.raises(ApprovedAllocationPlanAuthorityError):
        ApprovedAllocationPlanAuthorityBinder().bind(
            request=request,
            resolution=admit_allocation_plan_resolution(
                _resolution(scenario, request), request=request
            ),
            source_pool=source_pool,
            lineage=AllocationAuthorityLineage(HASH_A, HASH_B),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: [],
        lambda value: {**value, "tenant_id": "OTHER"},
        lambda value: {**value, "plan_id": "bad-uuid"},
        lambda value: {**value, "plan_revision": 0},
        lambda value: {**value, "plan_hash": "bad-hash"},
        lambda value: {**value, "approved_proof": "not-proof"},
    ],
)
def test_generic_authority_binder_rejects_unadmitted_plan_authority(
    mutation,
) -> None:
    scenario = SCENARIOS[0]
    request = _request(scenario)
    plan = mutation(_resolution(scenario, request))
    with pytest.raises(ApprovedAllocationPlanAuthorityError):
        ApprovedAllocationPlanAuthorityBinder().bind(
            request=request,
            resolution=plan,
            source_pool=_source_pool(scenario),
            lineage=AllocationAuthorityLineage(HASH_A, HASH_B),
        )


def test_generic_authority_binder_rejects_invalid_existing_checkpoint() -> None:
    scenario = SCENARIOS[0]
    request = _request(scenario)
    resolution = admit_allocation_plan_resolution(
        _resolution(scenario, request), request=request
    )
    binder = ApprovedAllocationPlanAuthorityBinder()
    values = {
        "request": request,
        "resolution": resolution,
        "source_pool": _source_pool(scenario),
        "lineage": AllocationAuthorityLineage(HASH_A, HASH_B),
    }
    checkpoint = binder.bind(**values)
    for invalid in (
        {**checkpoint, "source_pool": None},
        {**checkpoint, "checkpoint_hash": HASH_C},
    ):
        with pytest.raises(ApprovedAllocationPlanAuthorityError):
            binder.bind(**values, existing_checkpoint=invalid)


class _Response:
    def __init__(self, body: object) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def test_http_transport_sends_signed_canonical_request(monkeypatch) -> None:
    scenario = SCENARIOS[0]
    request = _request(scenario)
    observed = {}

    def send(outgoing, *, timeout):
        observed["url"] = outgoing.full_url
        observed["timeout"] = timeout
        observed["authorization"] = outgoing.get_header("Authorization")
        observed["tenant"] = outgoing.get_header("X-nex-tenant-id")
        observed["body"] = json.loads(outgoing.data)
        return _Response(_resolution(scenario, request))

    monkeypatch.setattr(client_module, "urlopen", send)
    transport = HttpAllocationPlanProviderTransport(
        eos_base_url="https://eos.example/base",
        service_token="signed-token",
        timeout_seconds=27,
    )

    result = transport.send(request)

    assert result["plan_id"] == scenario.plan_id
    assert observed == {
        "url": "https://eos.example/base/internal/v2/finance/cost-allocation-plans:resolve",
        "timeout": 27.0,
        "authorization": "Bearer signed-token",
        "tenant": scenario.tenant_id,
        "body": request.body,
    }


@pytest.mark.parametrize(
    ("failure", "error_code", "retryable"),
    [
        (
            HTTPError(
                "https://eos.example",
                409,
                "conflict",
                {},
                io.BytesIO(b'{"error_code":"PLAN_AMBIGUOUS","retryable":false}'),
            ),
            "PLAN_AMBIGUOUS",
            False,
        ),
        (URLError("offline"), "EOS_COST_ALLOCATION_PLAN_UNAVAILABLE", True),
    ],
)
def test_http_transport_maps_provider_failures(
    monkeypatch, failure, error_code, retryable
) -> None:
    monkeypatch.setattr(
        client_module,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    transport = HttpAllocationPlanProviderTransport(
        eos_base_url="http://eos.example",
        service_token="signed-token",
    )
    with pytest.raises(AllocationPlanConsumerError) as caught:
        transport.send(_request(SCENARIOS[0]))
    assert caught.value.error_code == error_code
    assert caught.value.retryable is retryable


@pytest.mark.parametrize(
    ("base_url", "token", "timeout"),
    [
        ("not-a-url", "token", 15),
        ("https://eos.example", "", 15),
        ("https://eos.example", "token", 0),
    ],
)
def test_http_transport_constructor_is_fail_closed(base_url, token, timeout) -> None:
    with pytest.raises(AllocationPlanConsumerError):
        HttpAllocationPlanProviderTransport(
            eos_base_url=base_url,
            service_token=token,
            timeout_seconds=timeout,
        )


class _BytesResponse(_Response):
    def __init__(self, body: bytes) -> None:
        self.body = body


@pytest.mark.parametrize("body", [b"not-json", b"[]"])
def test_http_transport_rejects_non_object_json(monkeypatch, body) -> None:
    monkeypatch.setattr(
        client_module, "urlopen", lambda *_args, **_kwargs: _BytesResponse(body)
    )
    transport = HttpAllocationPlanProviderTransport(
        eos_base_url="https://eos.example", service_token="token"
    )
    with pytest.raises(AllocationPlanConsumerError) as caught:
        transport.send(_request(SCENARIOS[0]))
    assert caught.value.status_code == 502


def test_http_transport_uses_default_error_for_non_json_http_failure(
    monkeypatch,
) -> None:
    failure = HTTPError(
        "https://eos.example", 503, "offline", {}, io.BytesIO(b"not-json")
    )
    monkeypatch.setattr(
        client_module,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    transport = HttpAllocationPlanProviderTransport(
        eos_base_url="https://eos.example", service_token="token"
    )
    with pytest.raises(AllocationPlanConsumerError) as caught:
        transport.send(_request(SCENARIOS[0]))
    assert caught.value.error_code == "EOS_COST_ALLOCATION_PLAN_REJECTED"
    assert caught.value.retryable is True


def _work_intent(scenario: _Scenario) -> dict[str, object]:
    intent = json.loads(
        (
            ROOT
            / "contracts/examples/service/ae_work_intent.business_transaction.v1_2.json"
        ).read_text(encoding="utf-8")
    )
    context = intent["business_request_context"]
    context["transaction"]["recognition_date"] = scenario.effective_on
    context["requested_allocation"] = [
        {
            "project_code": item["project_code"],
            "ratio": f"{float(item['allocation_ratio']):.6f}",
        }
        for item in scenario.projects
    ]
    context["context_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in context.items() if key != "context_hash"}
    )
    intent["business_context_hash"] = context["context_hash"]
    intent["intent_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in intent.items() if key != "intent_hash"}
    )
    return intent


def _preparation(scenario: _Scenario, intent: dict[str, object]) -> dict[str, object]:
    authority = {
        "schema_version": "nex.mybee.m1-preparation-authority.v1",
        "tenant_id": scenario.tenant_id,
        "company_id": scenario.company_id,
        "project_refs": [
            {
                "project_id": item["project_id"],
                "project_code": item["project_code"],
                "project_version": index,
            }
            for index, item in enumerate(scenario.projects, 1)
        ],
    }
    authority["authority_hash"] = semantic_sha256_hash_ref(authority)
    semantics = {
        "schema_version": "nex.mybee.m1-transaction-preparation.v1",
        "stage": "READY_FOR_D04",
        "business_context_hash": intent["business_context_hash"],
        "authority_hash": authority["authority_hash"],
        "authority": authority,
        "adapter_identity": "mybee:transaction-preparation:installed:v1",
        "identities": {},
        "references": {},
    }
    return {**semantics, "preparation_hash": semantic_sha256_hash_ref(semantics)}


class _RuntimeSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def resolve_and_bind(self, **values):
        self.calls.append(values)
        return MappingProxyType({"stage": "READY_FOR_ALLOCATION", **values})


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_m1_composition_only_maps_authoritative_runtime_inputs(
    scenario: _Scenario,
) -> None:
    runtime = _RuntimeSpy()
    intent = _work_intent(scenario)
    preparation = _preparation(scenario, intent)
    source_pool = _source_pool(scenario)

    result = resolve_m1_allocation_plan_authority(
        runtime,
        work_intent=intent,
        preparation_checkpoint=preparation,
        source_pool=source_pool,
        correlation_id=f"m1:{scenario.tenant_id}:19",
    )

    assert result["stage"] == "READY_FOR_ALLOCATION"
    call = runtime.calls[0]
    assert call["tenant_id"] == scenario.tenant_id
    assert call["company_id"] == scenario.company_id
    assert call["source_kind"] == scenario.source_kind
    assert call["effective_on"] == scenario.effective_on
    assert call["projects"] == tuple(
        {
            "project_id": item["project_id"],
            "project_code": item["project_code"],
            "allocation_ratio": item["allocation_ratio"],
        }
        for item in scenario.projects
    )


@pytest.mark.parametrize("mutation", ["intent", "preparation", "project_set"])
def test_m1_composition_rejects_stale_or_inexact_authority(mutation) -> None:
    scenario = SCENARIOS[0]
    intent = _work_intent(scenario)
    preparation = _preparation(scenario, intent)
    if mutation == "intent":
        intent["business_context_hash"] = HASH_A
    elif mutation == "preparation":
        preparation["preparation_hash"] = "not-a-hash"
    else:
        preparation["authority"]["project_refs"] = preparation["authority"][
            "project_refs"
        ][:-1]
        authority = preparation["authority"]
        authority["authority_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in authority.items() if key != "authority_hash"}
        )
        preparation["authority_hash"] = authority["authority_hash"]
        preparation["preparation_hash"] = semantic_sha256_hash_ref(
            {
                key: value
                for key, value in preparation.items()
                if key != "preparation_hash"
            }
        )

    with pytest.raises(M1AllocationPlanCompositionError):
        resolve_m1_allocation_plan_authority(
            _RuntimeSpy(),
            work_intent=intent,
            preparation_checkpoint=preparation,
            source_pool=_source_pool(scenario),
            correlation_id="m1:invalid",
        )


def _rehash_preparation(preparation: dict[str, object]) -> None:
    authority = preparation["authority"]
    authority["authority_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in authority.items() if key != "authority_hash"}
    )
    preparation["authority_hash"] = authority["authority_hash"]
    preparation["preparation_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in preparation.items() if key != "preparation_hash"}
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "work_intent_type",
        "context_contract",
        "preparation_stage",
        "authority_hash",
        "source_kind",
        "project_ref_fields",
        "duplicate_project_ref",
        "allocation_type",
        "unrequested_authority",
    ],
)
def test_m1_composition_rejects_mapping_and_authority_drift(mutation) -> None:
    scenario = SCENARIOS[0]
    intent = _work_intent(scenario)
    preparation = _preparation(scenario, intent)
    source_pool = _source_pool(scenario)
    work_intent = intent
    if mutation == "work_intent_type":
        work_intent = []
    elif mutation == "context_contract":
        intent["business_request_context"]["schema_version"] = "unsupported"
    elif mutation == "preparation_stage":
        preparation["stage"] = "OTHER"
        preparation["preparation_hash"] = semantic_sha256_hash_ref(
            {
                key: value
                for key, value in preparation.items()
                if key != "preparation_hash"
            }
        )
    elif mutation == "authority_hash":
        preparation["authority_hash"] = HASH_C
        preparation["preparation_hash"] = semantic_sha256_hash_ref(
            {
                key: value
                for key, value in preparation.items()
                if key != "preparation_hash"
            }
        )
    elif mutation == "source_kind":
        source_pool.pop("source_kind")
    elif mutation == "project_ref_fields":
        preparation["authority"]["project_refs"][0]["extra"] = True
        _rehash_preparation(preparation)
    elif mutation == "duplicate_project_ref":
        preparation["authority"]["project_refs"][1]["project_code"] = preparation[
            "authority"
        ]["project_refs"][0]["project_code"]
        _rehash_preparation(preparation)
    elif mutation == "allocation_type":
        intent["business_request_context"]["requested_allocation"] = "not-a-list"
        context = intent["business_request_context"]
        context["context_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in context.items() if key != "context_hash"}
        )
        intent["business_context_hash"] = context["context_hash"]
        intent["intent_hash"] = semantic_sha256_hash_ref(
            {key: value for key, value in intent.items() if key != "intent_hash"}
        )
    else:
        preparation["authority"]["project_refs"].append(
            {
                "project_id": "11000000-0000-4000-8000-000000000099",
                "project_code": "T101G260199",
                "project_version": 9,
            }
        )
        _rehash_preparation(preparation)

    with pytest.raises(M1AllocationPlanCompositionError):
        resolve_m1_allocation_plan_authority(
            _RuntimeSpy(),
            work_intent=work_intent,
            preparation_checkpoint=preparation,
            source_pool=source_pool,
            correlation_id="m1:invalid:matrix",
        )


def test_installed_runtime_readiness_and_builder_have_no_business_defaults() -> None:
    runtime = build_installed_allocation_plan_resolution(
        {
            "NEX_EOS_BASE_URL": "https://eos.example",
            "NEX_AE_TO_EOS_SERVICE_TOKEN": "signed-token",
            "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "29",
        }
    )
    readiness = runtime.readiness()
    assert readiness["status"] == "READY"
    assert readiness["operation"] == ALLOCATION_PLAN_RESOLVE_OPERATION
    assert readiness["timeout_seconds"] == 29.0
    assert readiness["business_defaults_included"] is False
    assert "url" not in readiness and "token" not in readiness

    for environment in (
        {
            "NEX_EOS_BASE_URL": "not-a-url",
            "NEX_AE_TO_EOS_SERVICE_TOKEN": "signed-token",
        },
        {
            "NEX_EOS_BASE_URL": "https://eos.example",
            "NEX_AE_TO_EOS_SERVICE_TOKEN": "signed-token",
            "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "121",
        },
    ):
        with pytest.raises(InstalledAllocationPlanResolutionError):
            build_installed_allocation_plan_resolution(environment)


def test_installed_runtime_executes_generic_client_and_binder() -> None:
    scenario = SCENARIOS[1]
    request = _request(scenario)
    transport = _Transport(_resolution(scenario, request))
    runtime = InstalledApprovedAllocationPlanResolution(
        client=NexAllocationPlanResolverClient(transport),
        binder=ApprovedAllocationPlanAuthorityBinder(),
        timeout_seconds=31.0,
    )

    checkpoint = runtime.resolve_and_bind(
        tenant_id=scenario.tenant_id,
        company_id=scenario.company_id,
        source_kind=scenario.source_kind,
        effective_on=scenario.effective_on,
        projects=scenario.projects,
        correlation_id="runtime:generic:31",
        source_pool=_source_pool(scenario),
        lineage=AllocationAuthorityLineage(HASH_A, HASH_B),
    )

    assert checkpoint["stage"] == "READY_FOR_ALLOCATION"
    assert checkpoint["tenant_id"] == scenario.tenant_id
    assert transport.requests[0].body["projects"] == sorted(
        scenario.projects, key=lambda item: (item["project_code"], item["project_id"])
    )


def test_installed_runtime_wraps_token_resolution_and_nonnumeric_timeout(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runtime_module,
        "resolve_ae_outbound_service_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    with pytest.raises(InstalledAllocationPlanResolutionError):
        build_installed_allocation_plan_resolution(
            {
                "NEX_EOS_BASE_URL": "https://eos.example",
                "NEX_AE_TO_EOS_SERVICE_TOKEN": "token",
            }
        )

    monkeypatch.undo()
    with pytest.raises(InstalledAllocationPlanResolutionError, match="numeric"):
        build_installed_allocation_plan_resolution(
            {
                "NEX_EOS_BASE_URL": "https://eos.example",
                "NEX_AE_TO_EOS_SERVICE_TOKEN": "token",
                "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "slow",
            }
        )


def test_generic_product_boundaries_contain_no_scenario_business_values() -> None:
    generic_paths = (
        ROOT / "domains/mybee/mybee_ax/integrations/nex_allocation_plan_client.py",
        ROOT / "domains/mybee/mybee_ax/orchestration/allocation_plan_authority.py",
        ROOT / "services/nex-ae-api/nex_ae_api/allocation_plan_resolution_runtime.py",
    )
    prohibited = (
        "VO00",
        "0.400000000000",
        "0.600000000000",
        "fixture",
        "demo",
        "golden",
        "M1",
    )
    for path in generic_paths:
        source = path.read_text(encoding="utf-8")
        for value in prohibited:
            assert value.casefold() not in source.casefold(), (
                f"{value} remained in {path}"
            )
