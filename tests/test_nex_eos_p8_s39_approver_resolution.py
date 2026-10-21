from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from nex_eos import (
    EOS_METADATA,
    EosApproverResolutionError,
    EosApproverResolutionService,
    EosOrganizationError,
    OrgUnitInput,
    PositionAssignmentInput,
    PositionInput,
    SqlAlchemyEosOrganizationRepository,
)
from nex_eos.app import create_eos_app
from nex_runtime import issue_mock_service_token
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 22, 1, 0, tzinfo=UTC)
ORG_ID = "10000000-0000-4000-8000-000000000001"
PROJECT_ID = "40000000-0000-4000-8000-000000000001"
POSITION_ID = "20000000-0000-4000-8000-000000000001"
ASSIGNMENT_ID = "30000000-0000-4000-8000-000000000001"


def _repository() -> SqlAlchemyEosOrganizationRepository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    return SqlAlchemyEosOrganizationRepository(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )


def _request(**overrides):
    value = {
        "schema_version": "eos_approver_resolution_request.v1",
        "requester_ref": {"type": "oa.user", "id": "employee-1001"},
        "approval_domain": "NSL_WRITE",
        "risk_level": "HIGH",
        "org_unit_ref": {"type": "eos.org_unit", "id": ORG_ID},
        "project_ref": {"type": "eos.project", "id": PROJECT_ID},
        "policy_ref": "eos.approver.default.v1",
    }
    value.update(overrides)
    return value


def _assignment(position_type: str, principal_id: str = "employee-2001"):
    return {
        "position_id": POSITION_ID,
        "position_type": position_type,
        "org_unit_id": ORG_ID,
        "position_assignment_id": ASSIGNMENT_ID,
        "principal_ref_type": "oa.user",
        "principal_id": principal_id,
        "position_assignment_version": 2,
        "org_unit_version": 3,
    }


class StubRepository:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = []

    def resolve_active_approver_assignment(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.parametrize(
    ("risk_level", "position_type"),
    (
        ("LOW", "PART_LEAD"),
        ("MEDIUM", "TEAM_LEAD"),
        ("HIGH", "GROUP_LEAD"),
        ("CRITICAL", "CEO"),
    ),
)
def test_default_policy_resolves_risk_to_effective_position(
    risk_level: str,
    position_type: str,
) -> None:
    repository = StubRepository(_assignment(position_type))
    service = EosApproverResolutionService(repository, clock=lambda: NOW)

    result = service.resolve(
        _request(risk_level=risk_level), tenant_id="tenant-a"
    )

    assert repository.calls == [
        {
            "tenant_id": "tenant-a",
            "org_unit_id": ORG_ID,
            "position_type": position_type,
            "effective_at": NOW,
        }
    ]
    assert result["principal_ref"] == {
        "type": "oa.user",
        "id": "employee-2001",
    }
    assert result["position_type"] == position_type
    assert result["security_authorization"] is False
    assert result["resolution_ref"].endswith(
        result["resolution_hash"].removeprefix("sha256:")
    )


def test_resolution_hash_is_stable_across_resolution_times() -> None:
    repository = StubRepository(_assignment("GROUP_LEAD"))
    first = EosApproverResolutionService(
        repository, clock=lambda: NOW
    ).resolve(_request(), tenant_id="tenant-a")
    second = EosApproverResolutionService(
        repository, clock=lambda: NOW + timedelta(minutes=5)
    ).resolve(_request(), tenant_id="tenant-a")

    assert first["resolution_hash"] == second["resolution_hash"]
    assert first["resolution_ref"] == second["resolution_ref"]
    assert first["resolved_at"] != second["resolved_at"]

    without_project = EosApproverResolutionService(
        repository, clock=lambda: NOW
    ).resolve(_request(project_ref=None), tenant_id="tenant-a")
    assert without_project["project_ref"] is None


def test_sql_repository_resolves_only_effective_tenant_scoped_assignment() -> None:
    repository = _repository()
    repository.create_org_unit(
        OrgUnitInput(
            tenant_id="tenant-a",
            org_unit_id=ORG_ID,
            org_unit_code="GROUP-A",
            name="Group A",
            org_unit_type="GROUP",
            effective_from=NOW - timedelta(days=1),
        )
    )
    repository.create_position(
        PositionInput(
            tenant_id="tenant-a",
            position_id=POSITION_ID,
            position_type="GROUP_LEAD",
            org_unit_id=ORG_ID,
        )
    )
    repository.assign_position(
        PositionAssignmentInput(
            tenant_id="tenant-a",
            position_assignment_id=ASSIGNMENT_ID,
            position_id=POSITION_ID,
            principal_ref={"type": "oa.user", "id": "employee-2001"},
            effective_from=NOW - timedelta(hours=1),
            effective_until=NOW + timedelta(hours=1),
            version=2,
        )
    )

    found = repository.resolve_active_approver_assignment(
        tenant_id="tenant-a",
        org_unit_id=ORG_ID,
        position_type="GROUP_LEAD",
        effective_at=NOW,
    )

    assert found is not None
    assert found["principal_id"] == "employee-2001"
    assert found["position_assignment_version"] == 2
    assert (
        repository.resolve_active_approver_assignment(
            tenant_id="tenant-b",
            org_unit_id=ORG_ID,
            position_type="GROUP_LEAD",
            effective_at=NOW,
        )
        is None
    )
    assert (
        repository.resolve_active_approver_assignment(
            tenant_id="tenant-a",
            org_unit_id=ORG_ID,
            position_type="GROUP_LEAD",
            effective_at=NOW + timedelta(hours=1),
        )
        is None
    )


def test_resolution_denies_missing_assignment_and_self_approval() -> None:
    with pytest.raises(EosApproverResolutionError) as missing:
        EosApproverResolutionService(
            StubRepository(), clock=lambda: NOW
        ).resolve(_request(), tenant_id="tenant-a")
    assert (missing.value.error_code, missing.value.status_code) == (
        "EOS_APPROVER_NOT_FOUND",
        404,
    )

    with pytest.raises(EosApproverResolutionError) as self_approval:
        EosApproverResolutionService(
            StubRepository(_assignment("GROUP_LEAD", "employee-1001")),
            clock=lambda: NOW,
        ).resolve(_request(), tenant_id="tenant-a")
    assert (self_approval.value.error_code, self_approval.value.status_code) == (
        "EOS_APPROVER_SELF_ASSIGNMENT",
        409,
    )


@pytest.mark.parametrize(
    "payload",
    (
        [],
        {"schema_version": "eos_approver_resolution_request.v1"},
        _request(schema_version="v2"),
        _request(policy_ref="eos.approver.unknown.v1"),
        _request(requester_ref={"type": "oa.service", "id": "nex-ae-api"}),
        _request(requester_ref={"type": "oa.user"}),
        _request(requester_ref={"type": "oa.user", "id": "bad id"}),
        _request(approval_domain="UNKNOWN"),
        _request(risk_level="EXTREME"),
        _request(org_unit_ref={"type": "eos.project", "id": ORG_ID}),
        _request(org_unit_ref={"type": "eos.org_unit", "id": "not-uuid"}),
        _request(project_ref={"type": "eos.org_unit", "id": PROJECT_ID}),
        _request(project_ref={"type": "eos.project", "id": "not-uuid"}),
    ),
)
def test_request_validation_fails_closed(payload) -> None:
    with pytest.raises(EosApproverResolutionError) as error:
        EosApproverResolutionService(
            StubRepository(_assignment("GROUP_LEAD")), clock=lambda: NOW
        ).resolve(payload, tenant_id="tenant-a")
    assert error.value.error_code == "EOS_APPROVER_RESOLUTION_INVALID"
    assert error.value.status_code == 422


def test_tenant_clock_and_repository_failures_fail_closed() -> None:
    service = EosApproverResolutionService(
        StubRepository(_assignment("GROUP_LEAD")), clock=lambda: NOW
    )
    with pytest.raises(EosApproverResolutionError):
        service.resolve(_request(), tenant_id="bad tenant")
    with pytest.raises(EosApproverResolutionError):
        EosApproverResolutionService(
            StubRepository(_assignment("GROUP_LEAD")),
            clock=lambda: NOW.replace(tzinfo=None),
        ).resolve(_request(), tenant_id="tenant-a")

    unavailable = EosOrganizationError(
        "EOS_ORGANIZATION_QUERY_FAILED",
        "private detail",
        status_code=503,
    )
    with pytest.raises(EosApproverResolutionError) as error:
        EosApproverResolutionService(
            StubRepository(error=unavailable), clock=lambda: NOW
        ).resolve(_request(), tenant_id="tenant-a")
    assert error.value.error_code == "EOS_APPROVER_RESOLUTION_UNAVAILABLE"
    assert error.value.retryable is True
    assert "private detail" not in error.value.detail

    expected = EosApproverResolutionError("EXPECTED", "expected", status_code=409)
    with pytest.raises(EosApproverResolutionError) as propagated:
        EosApproverResolutionService(
            StubRepository(error=expected), clock=lambda: NOW
        ).resolve(_request(), tenant_id="tenant-a")
    assert propagated.value is expected

    with pytest.raises(ValueError, match="unexpected"):
        EosApproverResolutionService(
            StubRepository(error=ValueError("unexpected")), clock=lambda: NOW
        ).resolve(_request(), tenant_id="tenant-a")


def test_repository_query_failure_is_redacted() -> None:
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private database detail")

    repository = SqlAlchemyEosOrganizationRepository(lambda: BrokenSession())
    with pytest.raises(EosOrganizationError) as error:
        repository.resolve_active_approver_assignment(
            tenant_id="tenant-a",
            org_unit_id=ORG_ID,
            position_type="GROUP_LEAD",
            effective_at=NOW,
        )
    assert error.value.error_code == "EOS_ORGANIZATION_QUERY_FAILED"
    assert "private database detail" not in error.value.detail


def _app():
    return create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "2.1.0-p8-s39",
            "NEX_BUILD_SHA": "p8s39test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )


def _headers():
    token = issue_mock_service_token(
        service_id="nex-ae-api", audience="nex-eos"
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": "tenant-a",
    }


def test_protected_approver_resolution_api() -> None:
    app = _app()
    app.state.eos_approver_resolution_service = EosApproverResolutionService(
        StubRepository(_assignment("GROUP_LEAD")), clock=lambda: NOW
    )
    client = TestClient(app)

    assert client.post(
        "/internal/v1/organization/approver-resolutions",
        json=_request(),
        headers={"X-NeX-Tenant-Id": "tenant-a"},
    ).status_code == 401
    response = client.post(
        "/internal/v1/organization/approver-resolutions",
        json=_request(),
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.json()["principal_ref"]["id"] == "employee-2001"


def test_approver_resolution_api_unavailable_and_domain_error() -> None:
    app = _app()
    client = TestClient(app)
    unavailable = client.post(
        "/internal/v1/organization/approver-resolutions",
        json=_request(),
        headers=_headers(),
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "EOS_APPROVER_RESOLUTION_UNAVAILABLE"

    app.state.eos_approver_resolution_service = EosApproverResolutionService(
        StubRepository(), clock=lambda: NOW
    )
    missing = client.post(
        "/internal/v1/organization/approver-resolutions",
        json=_request(),
        headers=_headers(),
    )
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "EOS_APPROVER_NOT_FOUND"


def test_contract_examples_validate_and_negative_is_rejected() -> None:
    pairs = (
        (
            "approver_resolution_request.v1.schema.json",
            "eos_approver_resolution_request.default.json",
        ),
        (
            "approver_resolution.v1.schema.json",
            "eos_approver_resolution.resolved.json",
        ),
    )
    import json

    for schema_name, example_name in pairs:
        schema = json.loads(
            (
                ROOT
                / "contracts/schemas/service/nex_eos"
                / schema_name
            ).read_text(encoding="utf-8")
        )
        example = json.loads(
            (ROOT / "contracts/examples/service" / example_name).read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).validate(example)

    request_schema = json.loads(
        (
            ROOT
            / "contracts/schemas/service/nex_eos/approver_resolution_request.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    negative = json.loads(
        (
            ROOT
            / "contracts/tests/negative/service/eos_approver_resolution_request.unknown_policy.json"
        ).read_text(encoding="utf-8")
    )
    assert list(
        Draft202012Validator(
            request_schema, format_checker=FormatChecker()
        ).iter_errors(negative)
    )
