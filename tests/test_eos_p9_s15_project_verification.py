from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_METADATA,
    NvtProjectInput,
    ProjectInput,
    ProjectMembershipInput,
    SqlAlchemyEosProjectMembershipRepository,
    SqlAlchemyEosProjectRepository,
)
from nex_eos.project_memberships import EosProjectMembershipError
from nex_eos.projects import EosProjectError
from nex_eos.wa_project_verification import (
    EOS_PROJECT_VERIFY_SCOPE,
    EosWaProjectVerifier,
    EosWaVerificationError,
    register_wa_project_verification_routes,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "tenant-p9-s15"
OTHER_TENANT = "tenant-other"
ACTIVE_PROJECT = "91000000-0000-4000-8000-000000000001"
INACTIVE_PROJECT = "91000000-0000-4000-8000-000000000002"
OTHER_PROJECT = "91000000-0000-4000-8000-000000000003"
MISSING_PROJECT = "91000000-0000-4000-8000-000000000004"
MEMBERSHIP_ID = "92000000-0000-4000-8000-000000000001"
EVENT_TIME = datetime(2026, 10, 28, 9, tzinfo=UTC)


class _Projects:
    def __init__(self) -> None:
        self.records = {
            (TENANT, ACTIVE_PROJECT): {"status": "ACTIVE", "version": 3},
            (TENANT, INACTIVE_PROJECT): {"status": "INACTIVE", "version": 2},
            (OTHER_TENANT, OTHER_PROJECT): {"status": "ACTIVE", "version": 1},
        }

    def get_project(self, *, tenant_id: str, project_id: str, **_kwargs: Any):
        return self.records.get((tenant_id, project_id))

    def find_project_tenants(self, *, project_id: str, limit: int = 2):
        return tuple(
            tenant
            for tenant, candidate in self.records
            if candidate == project_id
        )[:limit]


class _Memberships:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str], dict[str, Any]] = {}

    def get_subject_membership(
        self,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
    ):
        return self.records.get((tenant_id, project_id, subject_id))


def _verifier() -> tuple[EosWaProjectVerifier, _Projects, _Memberships]:
    projects = _Projects()
    memberships = _Memberships()
    return EosWaProjectVerifier(projects, memberships), projects, memberships


def _membership(*, valid_from: datetime, valid_to: datetime | None) -> dict[str, Any]:
    return {
        "project_membership_id": MEMBERSHIP_ID,
        "member_role": "MEMBER",
        "version": 4,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }


def _headers(*, caller: str = "nex-wa", include_scope: bool = True) -> dict[str, str]:
    scopes = [DEFAULT_SERVICE_SCOPE]
    if include_scope:
        scopes.append(EOS_PROJECT_VERIFY_SCOPE)
    token = issue_mock_service_token(
        service_id=caller,
        audience="nex-eos",
        scopes=scopes,
    )
    return {"Authorization": f"Bearer {token.access_token}"}


def test_project_batch_verification_distinguishes_all_states() -> None:
    verifier, _projects, _memberships = _verifier()
    payload = {
        "tenant_id": TENANT,
        "project_ids": [
            ACTIVE_PROJECT,
            INACTIVE_PROJECT,
            OTHER_PROJECT,
            MISSING_PROJECT,
        ],
    }
    first = verifier.verify_projects(payload)
    second = verifier.verify_projects(payload)

    assert first == second
    assert first["requested_count"] == 4
    assert first["verified_count"] == 1
    assert first["rejected_count"] == 3
    assert [item["verification_status"] for item in first["results"]] == [
        "VERIFIED",
        "PROJECT_INACTIVE",
        "TENANT_MISMATCH",
        "PROJECT_NOT_FOUND",
    ]
    assert first["results"][0]["project_version"] == 3
    assert "project_version" not in first["results"][2]


def test_historical_membership_accepts_current_and_removed_after_event() -> None:
    verifier, _projects, memberships = _verifier()
    memberships.records[(TENANT, ACTIVE_PROJECT, "current")] = _membership(
        valid_from=EVENT_TIME - timedelta(days=10),
        valid_to=None,
    )
    memberships.records[(TENANT, ACTIVE_PROJECT, "removed-later")] = _membership(
        valid_from=EVENT_TIME - timedelta(days=10),
        valid_to=EVENT_TIME + timedelta(days=1),
    )

    for subject_id in ("current", "removed-later"):
        result = verifier.verify_membership_at(
            {
                "tenant_id": TENANT,
                "project_id": ACTIVE_PROJECT,
                "subject_id": subject_id,
                "occurred_at": EVENT_TIME.isoformat(),
            }
        )
        assert result["membership_valid"] is True
        assert result["verification_status"] == "VERIFIED"
        assert result["project_membership_id"] == MEMBERSHIP_ID
        assert result["member_role"] == "MEMBER"
        assert result["version"] == 4
        assert result["verification_evidence_hash"].startswith("sha256:")


def test_historical_membership_rejects_joined_after_and_expired() -> None:
    verifier, _projects, memberships = _verifier()
    memberships.records[(TENANT, ACTIVE_PROJECT, "joined-after")] = _membership(
        valid_from=EVENT_TIME + timedelta(seconds=1),
        valid_to=None,
    )
    memberships.records[(TENANT, ACTIVE_PROJECT, "expired")] = _membership(
        valid_from=EVENT_TIME - timedelta(days=2),
        valid_to=EVENT_TIME,
    )

    joined = verifier.verify_membership_at(
        {
            "tenant_id": TENANT,
            "project_id": ACTIVE_PROJECT,
            "subject_id": "joined-after",
            "occurred_at": EVENT_TIME,
        }
    )
    expired = verifier.verify_membership_at(
        {
            "tenant_id": TENANT,
            "project_id": ACTIVE_PROJECT,
            "subject_id": "expired",
            "occurred_at": EVENT_TIME,
        }
    )
    assert joined["verification_status"] == "MEMBERSHIP_NOT_YET_VALID"
    assert expired["verification_status"] == "MEMBERSHIP_EXPIRED"
    assert joined["membership_valid"] is False
    assert expired["membership_valid"] is False


@pytest.mark.parametrize(
    ("project_id", "expected"),
    [
        (INACTIVE_PROJECT, "PROJECT_INACTIVE"),
        (OTHER_PROJECT, "TENANT_MISMATCH"),
        (MISSING_PROJECT, "PROJECT_NOT_FOUND"),
    ],
)
def test_historical_membership_rejects_project_boundary(
    project_id: str,
    expected: str,
) -> None:
    verifier, _projects, _memberships = _verifier()
    result = verifier.verify_membership_at(
        {
            "tenant_id": TENANT,
            "project_id": project_id,
            "subject_id": "subject-a",
            "occurred_at": EVENT_TIME,
        }
    )
    assert result["membership_valid"] is False
    assert result["verification_status"] == expected
    if expected == "PROJECT_INACTIVE":
        assert result["project_version"] == 2


def test_historical_membership_returns_not_found_without_unbounded_data() -> None:
    verifier, _projects, _memberships = _verifier()
    result = verifier.verify_membership_at(
        {
            "tenant_id": TENANT,
            "project_id": ACTIVE_PROJECT,
            "subject_id": "missing",
            "occurred_at": "2026-10-28T09:00:00Z",
        }
    )
    assert result["verification_status"] == "MEMBERSHIP_NOT_FOUND"
    assert set(result) == {
        "verification_schema_version",
        "service_id",
        "tenant_id",
        "project_id",
        "subject_id",
        "occurred_at",
        "membership_valid",
        "verification_status",
        "verification_evidence_hash",
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"tenant_id": TENANT, "project_ids": []},
        {"tenant_id": TENANT, "project_ids": [ACTIVE_PROJECT] * 2},
        {"tenant_id": "bad tenant", "project_ids": [ACTIVE_PROJECT]},
        {"tenant_id": TENANT, "project_ids": "bad"},
        {"tenant_id": TENANT, "project_ids": ["bad"]},
        {
            "tenant_id": TENANT,
            "project_ids": [f"91000000-0000-4000-8000-{index:012d}" for index in range(51)],
        },
    ],
)
def test_project_verification_rejects_invalid_batches(payload: Any) -> None:
    verifier, _projects, _memberships = _verifier()
    with pytest.raises(EosWaVerificationError) as raised:
        verifier.verify_projects(payload)
    assert raised.value.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"tenant_id": TENANT, "project_id": ACTIVE_PROJECT, "subject_id": "s"},
        {
            "tenant_id": TENANT,
            "project_id": ACTIVE_PROJECT,
            "subject_id": "bad subject",
            "occurred_at": EVENT_TIME,
        },
        {
            "tenant_id": TENANT,
            "project_id": ACTIVE_PROJECT,
            "subject_id": "s",
            "occurred_at": "bad",
        },
        {
            "tenant_id": TENANT,
            "project_id": ACTIVE_PROJECT,
            "subject_id": "s",
            "occurred_at": EVENT_TIME.replace(tzinfo=None),
        },
    ],
)
def test_membership_verification_rejects_invalid_requests(payload: Any) -> None:
    verifier, _projects, _memberships = _verifier()
    with pytest.raises(EosWaVerificationError) as raised:
        verifier.verify_membership_at(payload)
    assert raised.value.status_code == 400


class _BrokenProjects(_Projects):
    def get_project(self, **_kwargs: Any):
        raise EosProjectError("BROKEN", "private", status_code=503)


class _BrokenTenantLookup(_Projects):
    def find_project_tenants(self, **_kwargs: Any):
        raise EosProjectError("BROKEN", "private", status_code=503)


class _BrokenMemberships(_Memberships):
    def get_subject_membership(self, **_kwargs: Any):
        raise EosProjectMembershipError("BROKEN", "private", status_code=503)


def test_verifier_fails_closed_on_dependencies_and_malformed_records() -> None:
    with pytest.raises(EosWaVerificationError, match="EosProjectError"):
        EosWaProjectVerifier(_BrokenProjects(), _Memberships()).verify_projects(
            {"tenant_id": TENANT, "project_ids": [ACTIVE_PROJECT]}
        )
    with pytest.raises(EosWaVerificationError, match="EosProjectError"):
        EosWaProjectVerifier(_BrokenTenantLookup(), _Memberships()).verify_projects(
            {"tenant_id": TENANT, "project_ids": [MISSING_PROJECT]}
        )
    with pytest.raises(EosWaVerificationError, match="EosProjectMembershipError"):
        EosWaProjectVerifier(_Projects(), _BrokenMemberships()).verify_membership_at(
            {
                "tenant_id": TENANT,
                "project_id": ACTIVE_PROJECT,
                "subject_id": "subject",
                "occurred_at": EVENT_TIME,
            }
        )

    projects = _Projects()
    projects.records[(TENANT, ACTIVE_PROJECT)] = {"status": "ACTIVE", "version": 0}
    with pytest.raises(EosWaVerificationError):
        EosWaProjectVerifier(projects, _Memberships()).verify_projects(
            {"tenant_id": TENANT, "project_ids": [ACTIVE_PROJECT]}
        )

    memberships = _Memberships()
    memberships.records[(TENANT, ACTIVE_PROJECT, "subject")] = {
        **_membership(valid_from=EVENT_TIME, valid_to=None),
        "member_role": "",
    }
    with pytest.raises(EosWaVerificationError):
        EosWaProjectVerifier(_Projects(), memberships).verify_membership_at(
            {
                "tenant_id": TENANT,
                "project_id": ACTIVE_PROJECT,
                "subject_id": "subject",
                "occurred_at": EVENT_TIME,
            }
        )


def test_sqlalchemy_repositories_support_verification_queries() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    projects = SqlAlchemyEosProjectRepository(factory)
    memberships = SqlAlchemyEosProjectMembershipRepository(factory)
    nvt_id = "93000000-0000-4000-8000-000000000001"
    projects.create_nvt_project(NvtProjectInput(TENANT, nvt_id, "NVT-S15", "NVT"))
    projects.create_project(
        ProjectInput(
            TENANT,
            ACTIVE_PROJECT,
            "PROJECT-S15",
            "Project",
            nvt_project_id=nvt_id,
        )
    )
    memberships.create_membership(
        ProjectMembershipInput(
            TENANT,
            MEMBERSHIP_ID,
            ACTIVE_PROJECT,
            "subject-a",
            "MEMBER",
            "operator-a",
            valid_from=EVENT_TIME - timedelta(days=1),
        )
    )

    assert projects.find_project_tenants(project_id=ACTIVE_PROJECT) == (TENANT,)
    stored = memberships.get_subject_membership(
        tenant_id=TENANT,
        project_id=ACTIVE_PROJECT,
        subject_id="subject-a",
    )
    assert stored is not None
    assert str(stored["project_membership_id"]) == MEMBERSHIP_ID
    assert memberships.get_subject_membership(
        tenant_id=OTHER_TENANT,
        project_id=ACTIVE_PROJECT,
        subject_id="subject-a",
    ) is None


def test_protected_routes_enforce_scope_caller_dependency_and_success() -> None:
    verifier, _projects, _memberships = _verifier()
    app = build_service_app(SERVICE_SPECS["nex-eos"])
    register_wa_project_verification_routes(app, verifier=verifier)
    client = TestClient(app)
    path = "/internal/v1/projects:verify-batch"
    payload = {"tenant_id": TENANT, "project_ids": [ACTIVE_PROJECT]}

    assert client.post(path, json=payload).status_code == 401
    assert client.post(
        path, headers=_headers(include_scope=False), json=payload
    ).status_code == 401
    denied = client.post(path, headers=_headers(caller="nex-ae-api"), json=payload)
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "EOS_PROJECT_VERIFY_CALLER_DENIED"
    accepted = client.post(path, headers=_headers(), json=payload)
    assert accepted.status_code == 200
    assert accepted.json()["verified_count"] == 1
    assert accepted.json()["request_id"]
    assert accepted.json()["trace_id"]

    unavailable_app = build_service_app(SERVICE_SPECS["nex-eos"])
    register_wa_project_verification_routes(unavailable_app, verifier=None)
    unavailable = TestClient(unavailable_app).post(
        "/internal/v1/project-memberships:verify-at",
        headers=_headers(),
        json={
            "tenant_id": TENANT,
            "project_id": ACTIVE_PROJECT,
            "subject_id": "subject",
            "occurred_at": EVENT_TIME.isoformat(),
        },
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["retryable"] is True


def test_route_maps_invalid_and_dependency_errors() -> None:
    invalid_app = build_service_app(SERVICE_SPECS["nex-eos"])
    verifier, _projects, _memberships = _verifier()
    register_wa_project_verification_routes(invalid_app, verifier=verifier)
    invalid = TestClient(invalid_app).post(
        "/internal/v1/projects:verify-batch",
        headers=_headers(),
        json={"tenant_id": TENANT, "project_ids": []},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "EOS_PROJECT_VERIFY_INVALID"

    broken_app = build_service_app(SERVICE_SPECS["nex-eos"])
    register_wa_project_verification_routes(
        broken_app,
        verifier=EosWaProjectVerifier(_BrokenProjects(), _Memberships()),
    )
    broken = TestClient(broken_app).post(
        "/internal/v1/projects:verify-batch",
        headers=_headers(),
        json={"tenant_id": TENANT, "project_ids": [ACTIVE_PROJECT]},
    )
    assert broken.status_code == 503
    assert broken.json()["error_code"] == "EOS_PROJECT_VERIFICATION_UNAVAILABLE"


def test_both_routes_cover_unavailable_auth_success_and_invalid_paths() -> None:
    unavailable_app = build_service_app(SERVICE_SPECS["nex-eos"])
    register_wa_project_verification_routes(unavailable_app, verifier=None)
    unavailable = TestClient(unavailable_app).post(
        "/internal/v1/projects:verify-batch",
        headers=_headers(),
        json={"tenant_id": TENANT, "project_ids": [ACTIVE_PROJECT]},
    )
    assert unavailable.status_code == 503

    verifier, _projects, memberships = _verifier()
    memberships.records[(TENANT, ACTIVE_PROJECT, "subject")] = _membership(
        valid_from=EVENT_TIME - timedelta(days=1),
        valid_to=None,
    )
    app = build_service_app(SERVICE_SPECS["nex-eos"])
    register_wa_project_verification_routes(app, verifier=verifier)
    client = TestClient(app)
    path = "/internal/v1/project-memberships:verify-at"
    payload = {
        "tenant_id": TENANT,
        "project_id": ACTIVE_PROJECT,
        "subject_id": "subject",
        "occurred_at": EVENT_TIME.isoformat(),
    }
    assert client.post(path, json=payload).status_code == 401
    accepted = client.post(path, headers=_headers(), json=payload)
    assert accepted.status_code == 200
    assert accepted.json()["membership_valid"] is True
    invalid = client.post(
        path,
        headers=_headers(),
        json={**payload, "occurred_at": "invalid"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "EOS_PROJECT_VERIFY_INVALID"


def test_eos_app_registers_both_verification_routes() -> None:
    from nex_eos.app import create_eos_app

    app = create_eos_app(environ={"NEX_PROFILE": "test"})
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/internal/v1/projects:verify-batch" in paths
    assert "/internal/v1/project-memberships:verify-at" in paths
