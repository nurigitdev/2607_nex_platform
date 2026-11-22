from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import psycopg
import pytest
from fastapi.testclient import TestClient
from nex_eos import project_entitlement_reconciliation, project_memberships
from nex_eos.business_transactions import EOS_METADATA
from nex_eos.outbox_publication import (
    EosOutboxPublishReceipt,
    SqlAlchemyEosOutboxPublisher,
)
from nex_eos.project_entitlement_events import (
    PROJECT_ENTITLEMENT_EVENT_TYPE,
    append_project_entitlement_snapshot,
)
from nex_eos.project_entitlement_reconciliation import (
    EosProjectEntitlementReconciliationError,
    EosProjectEntitlementReconciliationService,
    HttpOaProjectEntitlementProjectionSource,
)
from nex_eos.project_entitlement_reconciliation_api import (
    register_project_entitlement_reconciliation_routes,
)
from nex_eos.project_entitlement_state import (
    EosProjectEntitlementStateError,
    append_authoritative_project_entitlement_snapshot,
    append_managed_project_entitlement_snapshot,
    authoritative_project_entitlement_projection,
)
from nex_eos.project_memberships import (
    EOS_PROJECT_MEMBER_TABLE,
    ProjectMembershipInput,
    SqlAlchemyEosProjectMembershipRepository,
    deterministic_project_membership_id,
)
from nex_eos.projects import (
    EOS_PROJECT_TABLE,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosProjectRepository,
)
from nex_oa.project_entitlement_sync import (
    OA_PROJECT_ENTITLEMENT_WRITE_SCOPE,
    SqlAlchemyOaProjectEntitlementInbox,
    register_project_entitlement_sync_routes,
)
from nex_oa.project_entitlements import (
    InMemoryOaProjectGrantRepository,
    SqlAlchemyOaProjectGrantRepository,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    psycopg_database_url,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

TENANT = "VO00"
PROJECT_ID = "81111111-1111-4111-8111-111111111111"
NVT_ID = "82222222-2222-4222-8222-222222222222"
PROJECT_CODE = "VO00D260001"
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


def _approved_project(*, sync_state: str = "IN_SYNC") -> ProjectInput:
    return ProjectInput(
        TENANT,
        PROJECT_ID,
        PROJECT_CODE,
        "W40 S06",
        nvt_project_id=NVT_ID,
        origin="APPROVED_APPLICATION",
        project_request_code="VO00R260001",
        purpose_type="D",
        approval_evidence_ref="eos.approval:w40-s06",
        approval_evidence_hash="sha256:" + "1" * 64,
        project_owner_subject_id="owner-100",
        project_manager_subject_id="manager-100",
        authorization_sync_state=sync_state,
        authorization_version=1,
    )


def _members() -> tuple[tuple[str, str], ...]:
    return (
        ("manager-100", "MANAGER"),
        ("member-100", "MEMBER"),
        ("owner-100", "OWNER"),
    )


def _runtime(url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(url)
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    projects = SqlAlchemyEosProjectRepository(sessions)
    memberships = SqlAlchemyEosProjectMembershipRepository(sessions)
    projects.create_nvt_project(NvtProjectInput(TENANT, NVT_ID, "NVT-S06", "S06"))
    projects.create_project(_approved_project())
    for subject_id, role in _members():
        memberships.create_membership(
            ProjectMembershipInput(
                TENANT,
                deterministic_project_membership_id(TENANT, PROJECT_ID, subject_id),
                PROJECT_ID,
                subject_id,
                role,
                "owner-100",
            )
        )
    return engine, sessions, projects, memberships


def _observed(*, version: int = 1, status: str = "ACTIVE", members=None):
    return {
        "schema_version": "oa_project_entitlement_projection.v1",
        "tenant_id": TENANT,
        "project_code": PROJECT_CODE,
        "found": True,
        "source_project_id": PROJECT_ID,
        "source_version": version,
        "project_status": status,
        "members": members
        if members is not None
        else [
            {"subject_id": subject_id, "project_role": role}
            for subject_id, role in _members()
        ],
        "correlation_id": "corr-1",
    }


class _ProjectionSource:
    def __init__(self, value):
        self.value = value

    def resolve(self, **_kwargs):
        return self.value


def test_managed_role_change_emits_new_version_and_legacy_is_not_auto_granted() -> None:
    engine, sessions, projects, memberships = _runtime()
    with sessions.begin() as session:
        changed = memberships.change_membership_role_in_session(
            session,
            tenant_id=TENANT,
            project_id=PROJECT_ID,
            subject_id="member-100",
            member_role="VIEWER",
            changed_by_subject_id="manager-100",
        )
        synchronization = append_managed_project_entitlement_snapshot(
            session,
            tenant_id=TENANT,
            project_id=PROJECT_ID,
            correlation_id="role-change-1",
            causation_id="role-change-1",
            occurred_at=NOW,
        )
    assert changed["member_role"] == "VIEWER"
    assert synchronization is not None
    assert synchronization["source_version"] == 2
    assert {tuple(item.values()) for item in synchronization["members"]} == {
        ("manager-100", "MANAGER"),
        ("member-100", "VIEWER"),
        ("owner-100", "OWNER"),
    }
    with sessions() as session:
        project = session.execute(select(EOS_PROJECT_TABLE)).mappings().one()
        assert project["authorization_sync_state"] == "PENDING"
        assert project["authorization_version"] == 2

    legacy_id = "83333333-3333-4333-8333-333333333333"
    projects.create_project(
        ProjectInput(TENANT, legacy_id, "LEGACY-1", "Legacy", nvt_project_id=NVT_ID)
    )
    with sessions.begin() as session:
        assert (
            append_managed_project_entitlement_snapshot(
                session,
                tenant_id=TENANT,
                project_id=legacy_id,
                correlation_id="legacy-1",
                causation_id="legacy-1",
                occurred_at=NOW,
            )
            is None
        )
    engine.dispose()


def test_role_change_rejects_accountable_and_missing_members() -> None:
    engine, sessions, _projects, memberships = _runtime()
    with sessions.begin() as session:
        with pytest.raises(Exception, match="governed Project party workflow"):
            memberships.change_membership_role_in_session(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                subject_id="owner-100",
                member_role="MEMBER",
                changed_by_subject_id="manager-100",
            )
        with pytest.raises(Exception, match="not found"):
            memberships.change_membership_role_in_session(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                subject_id="missing-100",
                member_role="VIEWER",
                changed_by_subject_id="manager-100",
            )
    engine.dispose()


def test_role_change_fail_closed_branches_and_exact_replay() -> None:
    engine, sessions, _projects, memberships = _runtime()
    with sessions.begin() as session:
        with pytest.raises(Exception, match="member_role is invalid"):
            memberships.change_membership_role_in_session(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                subject_id="member-100",
                member_role="OWNER",
                changed_by_subject_id="manager-100",
            )
        with pytest.raises(Exception, match="OWNER or MANAGER"):
            memberships.change_membership_role_in_session(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                subject_id="member-100",
                member_role="VIEWER",
                changed_by_subject_id="member-100",
            )
        replay = memberships.change_membership_role_in_session(
            session,
            tenant_id=TENANT,
            project_id=PROJECT_ID,
            subject_id="member-100",
            member_role="MEMBER",
            changed_by_subject_id="manager-100",
        )
        assert replay["version"] == 1
        session.execute(EOS_PROJECT_TABLE.update().values(status="INACTIVE"))
        with pytest.raises(Exception, match="must be active"):
            memberships.change_membership_role_in_session(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                subject_id="member-100",
                member_role="VIEWER",
                changed_by_subject_id="manager-100",
            )
    engine.dispose()


def test_membership_batch_and_role_change_concurrency_guards() -> None:
    engine, sessions, _projects, memberships = _runtime()
    with sessions.begin() as session:
        with pytest.raises(Exception, match="at most 50 unique"):
            memberships.add_memberships_in_session(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                target_subject_ids=tuple(f"subject-{index:03d}" for index in range(51)),
                member_role="MEMBER",
                created_by_subject_id="manager-100",
                manager_subject_id="manager-100",
            )
        with pytest.raises(Exception, match="canonical byte order"):
            memberships.add_memberships_in_session(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                target_subject_ids=("subject-b", "subject-a"),
                member_role="MEMBER",
                created_by_subject_id="manager-100",
                manager_subject_id="manager-100",
            )
        session.execute(EOS_PROJECT_TABLE.update().values(status="INACTIVE"))
        with pytest.raises(Exception, match="must be active"):
            memberships.add_memberships_in_session(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                target_subject_ids=("subject-a",),
                member_role="MEMBER",
                created_by_subject_id="manager-100",
                manager_subject_id="manager-100",
            )
        session.execute(EOS_PROJECT_TABLE.update().values(status="ACTIVE"))

        class ConcurrentSession:
            def execute(self, statement):
                if (
                    getattr(statement, "is_update", False)
                    and statement.table is EOS_PROJECT_MEMBER_TABLE
                ):
                    return SimpleNamespace(rowcount=0)
                return session.execute(statement)

        with pytest.raises(Exception, match="concurrently"):
            memberships.change_membership_role_in_session(
                ConcurrentSession(),  # type: ignore[arg-type]
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                subject_id="member-100",
                member_role="VIEWER",
                changed_by_subject_id="manager-100",
            )
    with pytest.raises(Exception, match="outcome is invalid"):
        project_memberships._batch_item(
            "UNKNOWN",
            {
                "subject_id": "member-100",
                "project_membership_id": deterministic_project_membership_id(
                    TENANT, PROJECT_ID, "member-100"
                ),
                "member_role": "MEMBER",
                "status": "ACTIVE",
                "version": 1,
            },
        )
    engine.dispose()


def test_entitlement_state_rejects_missing_legacy_and_memberless_sources() -> None:
    engine, sessions, projects, _memberships = _runtime()
    missing = "84444444-4444-4444-8444-444444444444"
    with sessions.begin() as session:
        assert (
            authoritative_project_entitlement_projection(
                session, tenant_id=TENANT, project_id=missing
            )
            is None
        )
        with pytest.raises(EosProjectEntitlementStateError, match="not found"):
            append_authoritative_project_entitlement_snapshot(
                session,
                tenant_id=TENANT,
                project_id=missing,
                correlation_id="missing",
                causation_id="missing",
                occurred_at=NOW,
            )
        with pytest.raises(EosProjectEntitlementStateError, match="not found"):
            append_managed_project_entitlement_snapshot(
                session,
                tenant_id=TENANT,
                project_id=missing,
                correlation_id="missing",
                causation_id="missing",
                occurred_at=NOW,
            )
    legacy_id = "85555555-5555-4555-8555-555555555555"
    projects.create_project(
        ProjectInput(TENANT, legacy_id, "LEGACY-2", "Legacy", nvt_project_id=NVT_ID)
    )
    with sessions.begin() as session:
        with pytest.raises(EosProjectEntitlementStateError, match="Legacy"):
            append_authoritative_project_entitlement_snapshot(
                session,
                tenant_id=TENANT,
                project_id=legacy_id,
                correlation_id="legacy",
                causation_id="legacy",
                occurred_at=NOW,
            )
        session.execute(
            delete(EOS_PROJECT_MEMBER_TABLE).where(
                EOS_PROJECT_MEMBER_TABLE.c.project_id == PROJECT_ID
            )
        )
        with pytest.raises(EosProjectEntitlementStateError, match="membership"):
            append_authoritative_project_entitlement_snapshot(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                correlation_id="memberless",
                causation_id="memberless",
                occurred_at=NOW,
            )
    engine.dispose()


def test_entitlement_state_rejects_concurrent_authorization_version_change() -> None:
    engine, sessions, _projects, _memberships = _runtime()
    with sessions.begin() as session:

        class ConcurrentSession:
            def execute(self, statement):
                if (
                    getattr(statement, "is_update", False)
                    and statement.table is EOS_PROJECT_TABLE
                ):
                    return SimpleNamespace(rowcount=0)
                return session.execute(statement)

        with pytest.raises(EosProjectEntitlementStateError, match="concurrently"):
            append_authoritative_project_entitlement_snapshot(
                ConcurrentSession(),  # type: ignore[arg-type]
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                correlation_id="concurrent",
                causation_id="concurrent",
                occurred_at=NOW,
            )
    engine.dispose()


def test_reconciliation_detects_drift_and_repairs_from_eos_authority() -> None:
    engine, sessions, _projects, _memberships = _runtime()
    missing = {**_observed(), "found": False, "source_version": 0, "members": []}
    service = EosProjectEntitlementReconciliationService(
        session_factory=sessions, projection_source=_ProjectionSource(missing)
    )
    drift = service.reconcile(
        tenant_id=TENANT,
        project_id=PROJECT_ID,
        correlation_id="corr-1",
    )
    assert drift["state"] == "DRIFT"
    assert drift["drift_reasons"] == ["OA_PROJECTION_MISSING"]
    repaired = service.reconcile(
        tenant_id=TENANT,
        project_id=PROJECT_ID,
        correlation_id="corr-1",
        repair=True,
    )
    assert repaired["state"] == "REPAIR_PENDING"
    assert repaired["repair_snapshot"]["source_version"] == 2
    with sessions() as session:
        project = session.execute(select(EOS_PROJECT_TABLE)).mappings().one()
        assert project["authorization_version"] == 2
        assert project["authorization_sync_state"] == "PENDING"
    engine.dispose()


def test_reconciliation_exact_and_ack_pending_do_not_create_authority() -> None:
    engine, sessions, _projects, _memberships = _runtime()
    exact = EosProjectEntitlementReconciliationService(
        session_factory=sessions, projection_source=_ProjectionSource(_observed())
    )
    assert exact.reconcile(
        tenant_id=TENANT, project_id=PROJECT_ID, correlation_id="corr-1"
    )["state"] == "IN_SYNC"
    with sessions.begin() as session:
        session.execute(
            EOS_PROJECT_TABLE.update().values(authorization_sync_state="PENDING")
        )
    pending = exact.reconcile(
        tenant_id=TENANT,
        project_id=PROJECT_ID,
        correlation_id="corr-1",
        repair=True,
    )
    assert pending["state"] == "ACK_PENDING"
    assert pending["repair_scheduled"] is False
    engine.dispose()


def test_reconciliation_rejects_legacy_missing_and_memberless_repair() -> None:
    engine, sessions, projects, _memberships = _runtime()
    service = EosProjectEntitlementReconciliationService(
        session_factory=sessions,
        projection_source=_ProjectionSource(
            {**_observed(), "found": False, "source_version": 0, "members": []}
        ),
    )
    with pytest.raises(EosProjectEntitlementReconciliationError) as missing:
        service.reconcile(
            tenant_id=TENANT,
            project_id="86666666-6666-4666-8666-666666666666",
            correlation_id="missing",
        )
    assert missing.value.status_code == 404
    legacy_id = "87777777-7777-4777-8777-777777777777"
    projects.create_project(
        ProjectInput(TENANT, legacy_id, "LEGACY-3", "Legacy", nvt_project_id=NVT_ID)
    )
    with pytest.raises(EosProjectEntitlementReconciliationError) as legacy:
        service.reconcile(
            tenant_id=TENANT, project_id=legacy_id, correlation_id="legacy"
        )
    assert legacy.value.error_code == "EOS_PROJECT_ENTITLEMENT_IMPORT_REQUIRED"
    with sessions.begin() as session:
        session.execute(
            delete(EOS_PROJECT_MEMBER_TABLE).where(
                EOS_PROJECT_MEMBER_TABLE.c.project_id == PROJECT_ID
            )
        )
    with pytest.raises(EosProjectEntitlementReconciliationError) as memberless:
        service.reconcile(
            tenant_id=TENANT,
            project_id=PROJECT_ID,
            correlation_id="memberless",
            repair=True,
        )
    assert memberless.value.error_code == "EOS_PROJECT_ENTITLEMENT_STATE_INVALID"
    engine.dispose()


def test_reconciliation_drift_reason_matrix_and_unavailable_source() -> None:
    source = {
        "project_id": PROJECT_ID,
        "project_code": PROJECT_CODE,
        "project_status": "ACTIVE",
        "source_version": 1,
        "members": [
            {"subject_id": subject_id, "project_role": role}
            for subject_id, role in _members()
        ],
    }
    mismatched = {
        **_observed(version=2, status="CLOSING"),
        "source_project_id": "88888888-8888-4888-8888-888888888888",
        "project_code": "VO00D260002",
    }
    assert project_entitlement_reconciliation._drift_reasons(
        source, mismatched
    ) == [
        "PROJECT_ID_MISMATCH",
        "PROJECT_CODE_MISMATCH",
        "PROJECT_STATUS_MISMATCH",
        "SOURCE_VERSION_MISMATCH",
    ]
    member_drift = {
        **_observed(),
        "members": [{"subject_id": "owner-100", "project_role": "OWNER"}],
    }
    assert project_entitlement_reconciliation._drift_reasons(
        source, member_drift
    ) == ["MEMBERSHIP_MISMATCH"]

    def failing_factory():
        raise SQLAlchemyError("down")

    unavailable = EosProjectEntitlementReconciliationService(
        session_factory=failing_factory,  # type: ignore[arg-type]
        projection_source=_ProjectionSource(_observed()),
    )
    with pytest.raises(EosProjectEntitlementReconciliationError) as caught:
        unavailable.reconcile(
            tenant_id=TENANT, project_id=PROJECT_ID, correlation_id="down"
        )
    assert caught.value.retryable is True


def test_oa_projection_route_is_signed_and_hash_bound() -> None:
    repository = InMemoryOaProjectGrantRepository()
    for index, (subject_id, role) in enumerate(_members(), start=1):
        repository.apply_grant(
            {
                "tenant_id": TENANT,
                "project_code": PROJECT_CODE,
                "subject_id": subject_id,
                "project_role": role,
                "grant_status": "ACTIVE",
                "project_status": "ACTIVE",
                "source_project_id": PROJECT_ID,
                "source_version": 1,
                "source_event_id": f"90000000-0000-4000-8000-{index:012d}",
                "source_event_hash": "sha256:" + f"{index}" * 64,
                "occurred_at": NOW,
            }
        )
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_project_entitlement_sync_routes(
        app, inbox=SimpleNamespace(), repository=repository
    )
    client = TestClient(app)
    path = "/internal/v1/auth/project-entitlement-projections:resolve"
    assert client.post(path, json={}).status_code == 401
    forbidden = issue_mock_service_token(
        service_id="nex-wc",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, OA_PROJECT_ENTITLEMENT_WRITE_SCOPE],
    )
    assert client.post(
        path,
        json={"tenant_id": TENANT, "project_code": PROJECT_CODE, "correlation_id": "corr-1"},
        headers={"Authorization": f"Bearer {forbidden.access_token}"},
    ).status_code == 403
    token = issue_mock_service_token(
        service_id="nex-eos",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, OA_PROJECT_ENTITLEMENT_WRITE_SCOPE],
    )
    response = client.post(
        path,
        json={"tenant_id": TENANT, "project_code": PROJECT_CODE, "correlation_id": "corr-1"},
        headers={"Authorization": f"Bearer {token.access_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    semantics = {
        key: value
        for key, value in body.items()
        if key not in {"schema_version", "projection_hash"}
    }
    assert body["projection_hash"] == semantic_sha256_hash_ref(semantics)


class _HttpResponse:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        import json

        return json.dumps(self.value).encode("utf-8")


def test_http_projection_source_rejects_tamper_and_configuration() -> None:
    value = _observed()
    value["projection_hash"] = semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != "schema_version"}
    )
    source = HttpOaProjectEntitlementProjectionSource(
        base_url="http://oa",
        service_token="signed",
        opener=lambda *_args, **_kwargs: _HttpResponse(value),
    )
    assert source.resolve(
        tenant_id=TENANT, project_code=PROJECT_CODE, correlation_id="corr-1"
    )["found"] is True
    tampered = {**value, "source_version": 2}
    bad = HttpOaProjectEntitlementProjectionSource(
        base_url="http://oa",
        service_token="signed",
        opener=lambda *_args, **_kwargs: _HttpResponse(tampered),
    )
    with pytest.raises(EosProjectEntitlementReconciliationError) as caught:
        bad.resolve(
            tenant_id=TENANT, project_code=PROJECT_CODE, correlation_id="corr-1"
        )
    assert caught.value.error_code == "EOS_PROJECT_ENTITLEMENT_PROJECTION_MALFORMED"
    with pytest.raises(ValueError):
        HttpOaProjectEntitlementProjectionSource(
            base_url="", service_token="signed"
        )
    with pytest.raises(ValueError, match="timeout"):
        HttpOaProjectEntitlementProjectionSource(
            base_url="http://oa", service_token="signed", timeout_seconds=0
        )
    malformed = HttpOaProjectEntitlementProjectionSource(
        base_url="http://oa",
        service_token="signed",
        opener=lambda *_args, **_kwargs: _HttpResponse(["not", "a", "mapping"]),
    )
    with pytest.raises(EosProjectEntitlementReconciliationError) as malformed_error:
        malformed.resolve(
            tenant_id=TENANT, project_code=PROJECT_CODE, correlation_id="corr-1"
        )
    assert (
        malformed_error.value.error_code
        == "EOS_PROJECT_ENTITLEMENT_PROJECTION_MALFORMED"
    )


@pytest.mark.parametrize(
    ("failure", "expected_detail"),
    [
        (
            HTTPError("http://oa", 503, "unavailable", {}, BytesIO()),
            "HTTP 503",
        ),
        (URLError("network down"), "is unavailable"),
    ],
)
def test_http_projection_source_maps_transport_failures(
    failure: Exception, expected_detail: str
) -> None:
    def fail(*_args, **_kwargs):
        raise failure

    source = HttpOaProjectEntitlementProjectionSource(
        base_url="http://oa", service_token="signed", opener=fail
    )
    with pytest.raises(EosProjectEntitlementReconciliationError) as caught:
        source.resolve(
            tenant_id=TENANT, project_code=PROJECT_CODE, correlation_id="corr-1"
        )
    assert caught.value.status_code == 503
    assert caught.value.retryable is True
    assert expected_detail in caught.value.detail


def test_reconciliation_api_is_protected_and_maps_boundary_failures() -> None:
    app = build_service_app(SERVICE_SPECS["nex-eos"])
    register_project_entitlement_reconciliation_routes(app)
    client = TestClient(app)
    route = f"/internal/v1/projects/{PROJECT_ID}/authorization:reconcile"
    assert client.post(route, json={}).status_code == 401

    token = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-eos",
        scopes=[DEFAULT_SERVICE_SCOPE],
    )
    headers = {"Authorization": f"Bearer {token.access_token}"}
    unavailable = client.post(
        route,
        json={"tenant_id": TENANT, "correlation_id": "api-1"},
        headers=headers,
    )
    assert unavailable.status_code == 503

    class StubService:
        outcome: object

        def reconcile(self, **kwargs):
            assert kwargs["project_id"] == PROJECT_ID
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome

    service = StubService()
    app.state.eos_project_entitlement_reconciliation = service
    invalid = client.post(route, json={}, headers=headers)
    assert invalid.status_code == 422
    invalid_repair = client.post(
        route,
        json={
            "tenant_id": TENANT,
            "correlation_id": "api-invalid",
            "repair": "true",
        },
        headers=headers,
    )
    assert invalid_repair.status_code == 422

    service.outcome = EosProjectEntitlementReconciliationError(
        "EOS_PROJECT_ENTITLEMENT_IMPORT_REQUIRED",
        "legacy Project requires import",
        status_code=409,
    )
    rejected = client.post(
        route,
        json={"tenant_id": TENANT, "correlation_id": "api-2"},
        headers=headers,
    )
    assert rejected.status_code == 409
    assert rejected.json()["error_code"] == "EOS_PROJECT_ENTITLEMENT_IMPORT_REQUIRED"

    service.outcome = {"state": "IN_SYNC", "repair_scheduled": False}
    accepted = client.post(
        route,
        json={
            "tenant_id": TENANT,
            "correlation_id": "api-3",
            "repair": True,
        },
        headers=headers,
    )
    assert accepted.status_code == 200
    assert accepted.json()["state"] == "IN_SYNC"


EOS_DATABASE_URL = os.getenv(
    "NEX_EOS_TEST_DATABASE_URL",
    "postgresql+psycopg://nex_eos_user:nuri1004@127.0.0.1:5432/nex_eos_test",
)
OA_DATABASE_URL = os.getenv(
    "NEX_OA_TEST_DATABASE_URL",
    "postgresql+psycopg://nex_oa_user:nuri1004@127.0.0.1:5432/nex_oa_test",
)
POSTGRES_SMOKE = os.getenv("NEX_MYBEE_W40_CA01_S06_POSTGRES_SMOKE") == "1"


@pytest.mark.skipif(
    not POSTGRES_SMOKE,
    reason="Protected W40-CA01-S06 EOS/OA PostgreSQL smoke is disabled",
)
def test_actual_postgres_lifecycle_reconciliation_and_zero_residue() -> None:
    eos_schema = f"mybee_w40ca01s06_eos_{uuid.uuid4().hex}"
    oa_schema = f"mybee_w40ca01s06_oa_{uuid.uuid4().hex}"
    eos_psycopg = psycopg_database_url(EOS_DATABASE_URL)
    oa_psycopg = psycopg_database_url(OA_DATABASE_URL)
    for url, expected, schema_name in (
        (eos_psycopg, ("nex_eos_test", "nex_eos_user"), eos_schema),
        (oa_psycopg, ("nex_oa_test", "nex_oa_user"), oa_schema),
    ):
        with psycopg.connect(url, autocommit=True) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            assert cursor.fetchone() == expected
            cursor.execute(f'CREATE SCHEMA "{schema_name}"')
    eos_url = make_url(EOS_DATABASE_URL).update_query_dict(
        {"options": f"-csearch_path={eos_schema}"}
    ).render_as_string(hide_password=False)
    oa_url = make_url(OA_DATABASE_URL).update_query_dict(
        {"options": f"-csearch_path={oa_schema}"}
    ).render_as_string(hide_password=False)
    eos_engine = oa_engine = None
    try:
        run_service_migrations("nex-eos", database_url=eos_url, profile="test")
        run_service_migrations("nex-oa", database_url=oa_url, profile="test")
        eos_engine = create_engine(eos_url, pool_pre_ping=True)
        oa_engine = create_engine(oa_url, pool_pre_ping=True)
        eos_sessions = sessionmaker(bind=eos_engine, expire_on_commit=False)
        oa_sessions = sessionmaker(bind=oa_engine, expire_on_commit=False)
        with oa_engine.begin() as connection:
            connection.execute(
                text("INSERT INTO oa_tenants (tenant_id, display_name) VALUES (:id, 'S06')"),
                {"id": TENANT},
            )
        projects = SqlAlchemyEosProjectRepository(eos_sessions)
        memberships = SqlAlchemyEosProjectMembershipRepository(eos_sessions)
        projects.create_nvt_project(NvtProjectInput(TENANT, NVT_ID, "NVT-S06", "S06"))
        projects.create_project(_approved_project(sync_state="PENDING"))
        for subject_id, role in _members():
            memberships.create_membership(
                ProjectMembershipInput(
                    TENANT,
                    deterministic_project_membership_id(TENANT, PROJECT_ID, subject_id),
                    PROJECT_ID,
                    subject_id,
                    role,
                    "owner-100",
                )
            )
        with eos_sessions.begin() as session:
            append_project_entitlement_snapshot(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                project_code=PROJECT_CODE,
                project_status="ACTIVE",
                source_version=1,
                members=(
                    {"subject_id": subject_id, "project_role": role}
                    for subject_id, role in _members()
                ),
                correlation_id="initial-1",
                causation_id="initial-1",
                occurred_at=NOW,
            )
        inbox = SqlAlchemyOaProjectEntitlementInbox(oa_sessions)
        grants = SqlAlchemyOaProjectGrantRepository(oa_sessions)

        class Transport:
            def publish(self, event):
                if event.event_type != PROJECT_ENTITLEMENT_EVENT_TYPE:
                    return EosOutboxPublishReceipt(
                        event.event_id,
                        event.event_payload_hash,
                        f"ae.project-lifecycle:{event.event_id}",
                    )
                receipt = inbox.apply_event(
                    {
                        "event_id": event.event_id,
                        "tenant_id": event.tenant_id,
                        "business_operation_id": event.business_operation_id,
                        "event_type": event.event_type,
                        "event_payload": event.event_payload,
                        "event_payload_hash": event.event_payload_hash,
                    }
                )
                return EosOutboxPublishReceipt(
                    event.event_id, event.event_payload_hash, receipt["receipt_ref"]
                )

        publisher = SqlAlchemyEosOutboxPublisher(eos_sessions)
        assert publisher.publish_next(Transport()).delivery_state == "PUBLISHED"
        oa_app = build_service_app(SERVICE_SPECS["nex-oa"])
        register_project_entitlement_sync_routes(
            oa_app, inbox=inbox, repository=grants
        )
        oa_client = TestClient(oa_app)
        oa_token = issue_mock_service_token(
            service_id="nex-eos",
            audience="nex-oa",
            scopes=[DEFAULT_SERVICE_SCOPE, OA_PROJECT_ENTITLEMENT_WRITE_SCOPE],
        )

        class ProtectedSource:
            def resolve(self, *, tenant_id, project_code, correlation_id):
                response = oa_client.post(
                    "/internal/v1/auth/project-entitlement-projections:resolve",
                    json={
                        "tenant_id": tenant_id,
                        "project_code": project_code,
                        "correlation_id": correlation_id,
                    },
                    headers={"Authorization": f"Bearer {oa_token.access_token}"},
                )
                assert response.status_code == 200
                return response.json()

        reconciliation = EosProjectEntitlementReconciliationService(
            session_factory=eos_sessions, projection_source=ProtectedSource()
        )
        eos_app = build_service_app(SERVICE_SPECS["nex-eos"])
        eos_app.state.eos_project_entitlement_reconciliation = reconciliation
        register_project_entitlement_reconciliation_routes(eos_app)
        eos_client = TestClient(eos_app)
        eos_token = issue_mock_service_token(
            service_id="nex-ag",
            audience="nex-eos",
            scopes=[DEFAULT_SERVICE_SCOPE],
        )
        route = f"/internal/v1/projects/{PROJECT_ID}/authorization:reconcile"
        headers = {"Authorization": f"Bearer {eos_token.access_token}"}
        exact = eos_client.post(
            route,
            json={"tenant_id": TENANT, "correlation_id": "pg-1"},
            headers=headers,
        )
        assert exact.status_code == 200
        assert exact.json()["state"] == "IN_SYNC"

        with oa_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM oa_project_grant "
                    "WHERE tenant_id = :tenant AND project_code = :code "
                    "AND subject_id = 'member-100'"
                ),
                {"tenant": TENANT, "code": PROJECT_CODE},
            )
        drift = eos_client.post(
            route,
            json={"tenant_id": TENANT, "correlation_id": "pg-2"},
            headers=headers,
        )
        assert drift.json()["state"] == "DRIFT"
        repair = eos_client.post(
            route,
            json={"tenant_id": TENANT, "correlation_id": "pg-2", "repair": True},
            headers=headers,
        )
        assert repair.json()["state"] == "REPAIR_PENDING"
        assert publisher.publish_next(Transport()).delivery_state == "PUBLISHED"
        assert reconciliation.reconcile(
            tenant_id=TENANT, project_id=PROJECT_ID, correlation_id="pg-3"
        )["state"] == "IN_SYNC"

        with eos_sessions.begin() as session:
            memberships.change_membership_role_in_session(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                subject_id="member-100",
                member_role="VIEWER",
                changed_by_subject_id="manager-100",
            )
            append_managed_project_entitlement_snapshot(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                correlation_id="pg-role",
                causation_id="pg-role",
                occurred_at=NOW,
            )
        assert publisher.publish_next(Transport()).delivery_state == "PUBLISHED"
        assert grants.get_grant(
            tenant_id=TENANT,
            project_code=PROJECT_CODE,
            subject_id="member-100",
        )["project_role"] == "VIEWER"

        with eos_sessions.begin() as session:
            memberships.remove_membership_in_session(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                subject_id="member-100",
                removed_by_subject_id="manager-100",
                manager_subject_id="manager-100",
            )
            append_managed_project_entitlement_snapshot(
                session,
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                correlation_id="pg-remove",
                causation_id="pg-remove",
                occurred_at=NOW,
            )
        assert publisher.publish_next(Transport()).delivery_state == "PUBLISHED"
        assert grants.get_grant(
            tenant_id=TENANT,
            project_code=PROJECT_CODE,
            subject_id="member-100",
        )["grant_status"] == "REVOKED"

        transitioned = projects.transition_project_status(
            tenant_id=TENANT,
            project_code=PROJECT_CODE,
            target_status="INACTIVE",
            expected_version=1,
            profile_policy_ref="policy:project-agent:v1",
            correlation_id="pg-inactive",
            causation_id="pg-inactive",
        )
        assert transitioned["authorization_sync_state"] == "PENDING"
        assert publisher.publish_next(Transport()).delivery_state == "PUBLISHED"
        assert publisher.publish_next(Transport()).delivery_state == "PUBLISHED"
        rows = grants.list_project_grants(
            tenant_id=TENANT, project_code=PROJECT_CODE
        )
        assert {row["project_status"] for row in rows} == {"INACTIVE"}
        assert reconciliation.reconcile(
            tenant_id=TENANT, project_id=PROJECT_ID, correlation_id="pg-final"
        )["state"] == "IN_SYNC"
    finally:
        if eos_engine is not None:
            eos_engine.dispose()
        if oa_engine is not None:
            oa_engine.dispose()
        for url, schema_name in (
            (eos_psycopg, eos_schema),
            (oa_psycopg, oa_schema),
        ):
            with psycopg.connect(url, autocommit=True) as connection, connection.cursor() as cursor:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
                cursor.execute(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s"
                    ")",
                    (schema_name,),
                )
                assert cursor.fetchone() == (False,)
