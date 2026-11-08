from __future__ import annotations

from collections.abc import Mapping

import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_METADATA,
    EOS_PROJECT_MEMBER_TABLE,
    EOS_PROJECT_TABLE,
    PROJECT_CREATE_OPERATION,
    PROJECT_DEACTIVATE_OPERATION,
    PROJECT_MEMBERSHIP_ADD_OPERATION,
    PROJECT_MEMBERSHIP_REMOVE_OPERATION,
    EosGovernedProjectError,
    EosGovernedProjectService,
    EosServiceCaller,
    InMemoryEosBusinessTransactionCoordinator,
    NvtProjectInput,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosProjectRepository,
    create_eos_app,
    project_operation_payload_hash,
)
from nex_eos import project_operations as project_module
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_runtime import issue_mock_service_token
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT_ID = "tenant-a"
NVT_ID = "8d000000-0000-4000-8000-000000000001"
PROJECT_ID = "8e000000-0000-4000-8000-000000000001"
OWNER_MEMBERSHIP_ID = "8f000000-0000-4000-8000-000000000001"
MEMBER_MEMBERSHIP_ID = "8f000000-0000-4000-8000-000000000002"
CALLER = EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))


class AuthorizationSource:
    def __init__(self) -> None:
        self.denied: set[str] = set()
        self.unavailable: set[str] = set()
        self.project_ids: dict[str, list[str]] = {}
        self.scopes = {
            "owner-a": {
                "project:project:create",
                "project:project:read",
                "project:project:admin",
                "project:membership:manage",
            },
            "member-a": {"project:project:read"},
            "outsider": {"project:project:read"},
            "target-a": set(),
        }

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if subject_id in self.unavailable:
            raise RuntimeError("private OA failure")
        result = {
            "active": subject_id not in self.denied,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": sorted(self.scopes.get(subject_id, set())),
            "revision_hash": "a" * 64,
        }
        if subject_id in self.project_ids:
            result["project_ids"] = self.project_ids[subject_id]
        return result


@pytest.fixture
def governed():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    projects = SqlAlchemyEosProjectRepository(factory)
    projects.create_nvt_project(
        NvtProjectInput(TENANT_ID, NVT_ID, "NVT-S96", "NVT S96")
    )
    source = AuthorizationSource()
    service = EosGovernedProjectService(
        session_factory=factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=source,
    )
    return engine, factory, source, service


def _write_payload(operation: str, sequence: int, **values) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "eos_project_operation.v1",
        "tenant_id": TENANT_ID,
        "business_operation_id": f"90000000-0000-4000-8000-{sequence:012d}",
        "idempotency_key": f"p8-s96-{sequence:04d}",
        "requester_subject_id": "owner-a",
        **values,
    }
    payload["payload_hash"] = project_operation_payload_hash(payload, operation)
    return payload


def _create_payload(sequence: int = 1) -> dict[str, object]:
    return _write_payload(
        PROJECT_CREATE_OPERATION,
        sequence,
        project={
            "project_id": PROJECT_ID,
            "project_code": "PROJECT-S96",
            "name": "Project S96",
            "nvt_project_id": NVT_ID,
            "currency": "KRW",
        },
        initial_owner_subject_id="owner-a",
        initial_owner_membership_id=OWNER_MEMBERSHIP_ID,
    )


def _create(service) -> dict[str, object]:
    return service.create_project(_create_payload(), caller=CALLER)


def test_project_and_initial_owner_commit_atomically_and_replay(governed) -> None:
    _engine, factory, _source, service = governed
    created = _create(service)
    replay = _create(service)

    assert created["created"] is True
    assert replay["created"] is False
    assert created["result"] == replay["result"]
    assert created["result"]["requested_operation"] == PROJECT_CREATE_OPERATION
    assert created["result"]["canonical_operation"] == PROJECT_CREATE_OPERATION
    with factory() as session:
        assert session.execute(select(func.count()).select_from(EOS_PROJECT_TABLE)).scalar_one() == 1
        assert session.execute(select(func.count()).select_from(EOS_PROJECT_MEMBER_TABLE)).scalar_one() == 1
        assert session.execute(select(func.count()).select_from(EOS_BUSINESS_OPERATION_TABLE)).scalar_one() == 1


def test_inactive_owner_or_hash_mismatch_leaves_no_project_residue(governed) -> None:
    _engine, factory, source, service = governed
    source.denied.add("owner-a")
    with pytest.raises(EosGovernedProjectError) as denied:
        _create(service)
    assert denied.value.error_code == "EOS_PROJECT_AUTHORIZATION_DENIED"

    source.denied.clear()
    payload = _create_payload()
    payload["project"] = {**payload["project"], "name": "tampered"}  # type: ignore[arg-type]
    with pytest.raises(EosGovernedProjectError) as mismatch:
        service.create_project(payload, caller=CALLER)
    assert mismatch.value.error_code == "EOS_PROJECT_PAYLOAD_HASH_MISMATCH"
    with factory() as session:
        assert session.execute(select(func.count()).select_from(EOS_PROJECT_TABLE)).scalar_one() == 0


def test_target_subject_must_be_active_and_available(governed) -> None:
    _engine, factory, source, service = governed
    payload = _create_payload()
    payload["initial_owner_subject_id"] = "target-a"
    payload["payload_hash"] = project_operation_payload_hash(
        payload, PROJECT_CREATE_OPERATION
    )
    source.denied.add("target-a")
    with pytest.raises(EosGovernedProjectError) as denied:
        service.create_project(payload, caller=CALLER)
    assert denied.value.error_code == "EOS_PROJECT_AUTHORIZATION_DENIED"

    source.denied.clear()
    source.unavailable.add("target-a")
    with pytest.raises(EosGovernedProjectError) as unavailable:
        service.create_project(payload, caller=CALLER)
    assert unavailable.value.error_code == "EOS_PROJECT_AUTHORIZATION_UNAVAILABLE"
    with factory() as session:
        assert session.execute(select(func.count()).select_from(EOS_PROJECT_TABLE)).scalar_one() == 0


def test_membership_management_requires_oa_scope_and_owner_or_manager(governed) -> None:
    _engine, _factory, source, service = governed
    _create(service)
    add = _write_payload(
        PROJECT_MEMBERSHIP_ADD_OPERATION,
        2,
        project_id=PROJECT_ID,
        target_subject_id="member-a",
        project_membership_id=MEMBER_MEMBERSHIP_ID,
        member_role="MEMBER",
    )
    added = service.add_membership(add, caller=CALLER)
    assert added["result"]["membership"]["status"] == "ACTIVE"

    source.scopes["member-a"].add("project:membership:manage")
    denied_add = _write_payload(
        PROJECT_MEMBERSHIP_ADD_OPERATION,
        3,
        requester_subject_id="member-a",
        project_id=PROJECT_ID,
        target_subject_id="target-a",
        project_membership_id="8f000000-0000-4000-8000-000000000003",
        member_role="VIEWER",
    )
    with pytest.raises(EosGovernedProjectError) as denied:
        service.add_membership(denied_add, caller=CALLER)
    assert denied.value.error_code == "EOS_PROJECT_MEMBERSHIP_MANAGEMENT_DENIED"

    remove = _write_payload(
        PROJECT_MEMBERSHIP_REMOVE_OPERATION,
        4,
        project_id=PROJECT_ID,
        target_subject_id="member-a",
    )
    removed = service.remove_membership(remove, caller=CALLER)
    assert removed["result"]["membership"]["status"] == "REMOVED"


def test_last_owner_and_duplicate_project_conflicts_are_typed(governed) -> None:
    _engine, _factory, _source, service = governed
    _create(service)
    remove_owner = _write_payload(
        PROJECT_MEMBERSHIP_REMOVE_OPERATION,
        6,
        project_id=PROJECT_ID,
        target_subject_id="owner-a",
    )
    with pytest.raises(EosGovernedProjectError) as last_owner:
        service.remove_membership(remove_owner, caller=CALLER)
    assert last_owner.value.error_code == "EOS_PROJECT_LAST_OWNER_REQUIRED"

    duplicate = _create_payload(sequence=7)
    duplicate["idempotency_key"] = "p8-s96-duplicate"
    duplicate["payload_hash"] = project_operation_payload_hash(
        duplicate, PROJECT_CREATE_OPERATION
    )
    with pytest.raises(EosGovernedProjectError) as conflict:
        service.create_project(duplicate, caller=CALLER)
    assert conflict.value.error_code == "EOS_PROJECT_OPERATION_CONFLICT"


def test_read_is_membership_filtered_with_explicit_admin_override(governed) -> None:
    _engine, _factory, source, service = governed
    _create(service)
    assert service.get_project(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        requester_subject_id="owner-a",
    )["project_id"] == PROJECT_ID
    assert len(
        service.list_projects(
            tenant_id=TENANT_ID, requester_subject_id="owner-a"
        )
    ) == 1
    assert len(
        service.list_memberships(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="owner-a",
        )
    ) == 1

    with pytest.raises(EosGovernedProjectError) as denied:
        service.get_project(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="outsider",
        )
    assert denied.value.error_code == "EOS_PROJECT_MEMBERSHIP_REQUIRED"

    source.scopes["owner-a"].remove("project:project:admin")
    assert len(
        service.list_projects(
            tenant_id=TENANT_ID, requester_subject_id="owner-a"
        )
    ) == 1
    assert len(
        service.list_memberships(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="owner-a",
        )
    ) == 1
    source.scopes["owner-a"].add("project:project:admin")

    source.scopes["outsider"].add("project:project:admin")
    assert service.get_project(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        requester_subject_id="outsider",
    )["project_id"] == PROJECT_ID
    assert len(
        service.list_projects(
            tenant_id=TENANT_ID,
            requester_subject_id="outsider",
            limit=1,
            offset=0,
        )
    ) == 1

    source.project_ids["owner-a"] = []
    with pytest.raises(EosGovernedProjectError) as scoped:
        service.get_project(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="owner-a",
        )
    assert scoped.value.error_code == "EOS_PROJECT_AUTHORIZATION_DENIED"


def test_deactivate_requires_fresh_admin_scope_and_owner_membership(governed) -> None:
    _engine, _factory, source, service = governed
    _create(service)
    payload = _write_payload(
        PROJECT_DEACTIVATE_OPERATION,
        5,
        project_id=PROJECT_ID,
        expected_version=1,
    )
    source.scopes["owner-a"].remove("project:project:admin")
    with pytest.raises(EosGovernedProjectError) as denied:
        service.deactivate_project(payload, caller=CALLER)
    assert denied.value.error_code == "EOS_PROJECT_AUTHORIZATION_DENIED"

    source.scopes["owner-a"].add("project:project:admin")
    wrong_version = {**payload, "expected_version": 2}
    wrong_version["payload_hash"] = project_operation_payload_hash(
        wrong_version, PROJECT_DEACTIVATE_OPERATION
    )
    with pytest.raises(EosGovernedProjectError) as conflict:
        service.deactivate_project(wrong_version, caller=CALLER)
    assert conflict.value.error_code == "EOS_PROJECT_VERSION_CONFLICT"

    result = service.deactivate_project(payload, caller=CALLER)
    assert result["result"]["project"]["status"] == "INACTIVE"
    assert result["result"]["project"]["version"] == 2

    second = _write_payload(
        PROJECT_DEACTIVATE_OPERATION,
        8,
        project_id=PROJECT_ID,
        expected_version=2,
    )
    terminal = service.deactivate_project(second, caller=CALLER)
    assert terminal["result"]["project"]["status"] == "INACTIVE"
    assert terminal["result"]["project"]["version"] == 2


def test_service_trust_oa_unavailable_and_input_guards(governed) -> None:
    _engine, _factory, source, service = governed
    with pytest.raises(EosGovernedProjectError) as trust:
        service.create_project(
            _create_payload(),
            caller=EosServiceCaller("browser", "nex-eos", ()),
        )
    assert trust.value.error_code == "EOS_SERVICE_TRUST_DENIED"

    source.unavailable.add("owner-a")
    with pytest.raises(EosGovernedProjectError) as unavailable:
        _create(service)
    assert unavailable.value.error_code == "EOS_PROJECT_AUTHORIZATION_UNAVAILABLE"

    with pytest.raises(EosGovernedProjectError):
        service.list_projects(
            tenant_id=TENANT_ID,
            requester_subject_id="owner-a",
            limit=501,
        )
    with pytest.raises(EosGovernedProjectError):
        service.list_projects(
            tenant_id=TENANT_ID,
            requester_subject_id="owner-a",
            offset=-1,
        )


def test_authorization_and_parser_negative_matrix(governed) -> None:
    _engine, _factory, source, service = governed
    base = _create_payload()

    source.project_ids["owner-a"] = ["8e000000-0000-4000-8000-000000000099"]
    with pytest.raises(EosGovernedProjectError):
        service.get_project(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="owner-a",
        )
    source.project_ids.clear()

    for authorization in (
        {"active": True, "tenant_id": "wrong", "subject_id": "owner-a", "scopes": [], "revision_hash": "a" * 64},
        {"active": True, "tenant_id": TENANT_ID, "subject_id": "owner-a", "scopes": "bad", "revision_hash": "a" * 64},
        {"active": True, "tenant_id": TENANT_ID, "subject_id": "owner-a", "scopes": [""], "revision_hash": "a" * 64},
        {"active": True, "tenant_id": TENANT_ID, "subject_id": "owner-a", "scopes": ["project:project:create"], "revision_hash": "bad"},
    ):
        source.effective_authorization = (  # type: ignore[method-assign]
            lambda value=authorization, **_kwargs: value
        )
        with pytest.raises(EosGovernedProjectError):
            service.create_project(base, caller=CALLER)

    invalid_payloads = (
        [],
        {**base, "project": None},
        {**base, "tenant_id": " "},
        {**base, "business_operation_id": "bad"},
        {**base, "idempotency_key": ""},
        {**base, "project": {**base["project"], "start_date": "not-a-date"}},  # type: ignore[arg-type]
    )
    fresh_source = AuthorizationSource()
    service._authorization_source = fresh_source
    for payload in invalid_payloads:
        with pytest.raises(EosGovernedProjectError):
            service.create_project(payload, caller=CALLER)  # type: ignore[arg-type]

    mismatched_operation = {
        **base,
        "requested_operation": "PROJECT.GET_PROJECT",
    }
    mismatched_operation["payload_hash"] = project_operation_payload_hash(
        mismatched_operation, PROJECT_CREATE_OPERATION
    )
    with pytest.raises(EosGovernedProjectError) as mismatch:
        service.create_project(mismatched_operation, caller=CALLER)
    assert mismatch.value.error_code == "EOS_PROJECT_OPERATION_INVALID"


def test_typed_oa_denial_and_non_transactional_coordinator_fail_closed(governed) -> None:
    _engine, factory, _source, _service = governed

    class DeniedSource:
        def effective_authorization(self, **_kwargs):
            raise AuthorizationSubjectDenied("inactive")

    denied_service = EosGovernedProjectService(
        session_factory=factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=DeniedSource(),
    )
    with pytest.raises(EosGovernedProjectError) as denied:
        denied_service.create_project(_create_payload(), caller=CALLER)
    assert denied.value.error_code == "EOS_PROJECT_AUTHORIZATION_DENIED"

    memory_service = EosGovernedProjectService(
        session_factory=factory,
        coordinator=InMemoryEosBusinessTransactionCoordinator(),
        authorization_source=AuthorizationSource(),
    )
    with pytest.raises(EosGovernedProjectError) as transaction_required:
        memory_service.create_project(_create_payload(), caller=CALLER)
    assert transaction_required.value.error_code == "EOS_BUSINESS_MUTATION_FAILED"

    payloads = (
        (
            memory_service.add_membership,
            _write_payload(
                PROJECT_MEMBERSHIP_ADD_OPERATION,
                20,
                project_id=PROJECT_ID,
                target_subject_id="target-a",
                project_membership_id=MEMBER_MEMBERSHIP_ID,
                member_role="MEMBER",
            ),
        ),
        (
            memory_service.remove_membership,
            _write_payload(
                PROJECT_MEMBERSHIP_REMOVE_OPERATION,
                21,
                project_id=PROJECT_ID,
                target_subject_id="target-a",
            ),
        ),
        (
            memory_service.deactivate_project,
            _write_payload(
                PROJECT_DEACTIVATE_OPERATION,
                22,
                project_id=PROJECT_ID,
                expected_version=1,
            ),
        ),
    )
    for operation, payload in payloads:
        with pytest.raises(EosGovernedProjectError) as required:
            operation(payload, caller=CALLER)
        assert required.value.error_code == "EOS_BUSINESS_MUTATION_FAILED"


def test_missing_project_and_persistence_failures_are_typed(governed) -> None:
    _engine, factory, source, service = governed
    with pytest.raises(EosGovernedProjectError) as missing:
        service.get_project(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="owner-a",
        )
    assert missing.value.error_code == "EOS_PROJECT_NOT_FOUND"

    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            from sqlalchemy.exc import SQLAlchemyError

            raise SQLAlchemyError("private project detail")

    broken = EosGovernedProjectService(
        session_factory=lambda: BrokenSession(),  # type: ignore[arg-type]
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=source,
    )
    for operation in (
        lambda: broken.get_project(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="owner-a",
        ),
        lambda: broken.list_projects(
            tenant_id=TENANT_ID, requester_subject_id="owner-a"
        ),
        lambda: broken.list_memberships(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="owner-a",
        ),
    ):
        with pytest.raises(EosGovernedProjectError) as failed:
            operation()
        assert failed.value.error_code == "EOS_PROJECT_OPERATION_PERSISTENCE_FAILED"
        assert "private project detail" not in failed.value.detail


def test_target_typed_denial_is_distinct_from_unavailability(governed) -> None:
    _engine, factory, _source, _service = governed

    class TargetDeniedSource(AuthorizationSource):
        def effective_authorization(self, *, tenant_id: str, subject_id: str):
            if subject_id == "target-a":
                raise AuthorizationSubjectDenied("inactive")
            return super().effective_authorization(
                tenant_id=tenant_id, subject_id=subject_id
            )

    service = EosGovernedProjectService(
        session_factory=factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=TargetDeniedSource(),
    )
    payload = _create_payload()
    payload["initial_owner_subject_id"] = "target-a"
    payload["payload_hash"] = project_operation_payload_hash(
        payload, PROJECT_CREATE_OPERATION
    )
    with pytest.raises(EosGovernedProjectError) as denied:
        service.create_project(payload, caller=CALLER)
    assert denied.value.error_code == "EOS_PROJECT_AUTHORIZATION_DENIED"


@pytest.mark.parametrize(
    ("helper", "value"),
    (
        (lambda value: project_module._scoped_id("field", value), " "),
        (lambda value: project_module._uuid("field", value), "bad"),
        (lambda value: project_module._text("field", value), ""),
        (lambda value: project_module._positive_int("field", value), True),
        (lambda value: project_module._optional_date(value), "bad"),
    ),
)
def test_project_operation_validation_helpers_fail_closed(helper, value) -> None:
    with pytest.raises(EosGovernedProjectError):
        helper(value)


class FakeProjectService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def get_project(self, **kwargs):
        self.calls.append(("get", kwargs))
        return kwargs

    def list_projects(self, **kwargs):
        self.calls.append(("list", kwargs))
        return [{"project_id": PROJECT_ID}]

    def list_memberships(self, **kwargs):
        self.calls.append(("memberships", kwargs))
        return [{"subject_id": "owner-a"}]

    def create_project(self, payload, *, caller):
        self.calls.append(("create", payload))
        assert caller.subject == "service:nex-ae-api"
        return {"created": True, "result": {}}

    def deactivate_project(self, payload, *, caller):
        self.calls.append(("deactivate", payload))
        return {"created": False, "result": {}}

    def add_membership(self, payload, *, caller):
        self.calls.append(("add", payload))
        return {"created": True, "result": {}}

    def add_memberships(self, payload, *, caller):
        self.calls.append(("add-many", payload))
        return {"created": True, "result": {}}

    def remove_membership(self, payload, *, caller):
        self.calls.append(("remove", payload))
        return {"created": True, "result": {}}


class FailingProjectService(FakeProjectService):
    def get_project(self, **kwargs):
        raise EosGovernedProjectError("DENIED", "denied", status_code=403)

    def create_project(self, payload, *, caller):
        raise EosGovernedProjectError("DENIED", "denied", status_code=403)


def test_project_routes_require_service_token_and_expose_read_boundary() -> None:
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "p8-s96",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    service = FakeProjectService()
    app.state.eos_project_operations = service
    client = TestClient(app)
    path = f"/internal/v1/projects/{PROJECT_ID}"
    headers = {"X-NeX-Tenant-Id": TENANT_ID, "X-NeX-Subject-Id": "owner-a"}
    assert client.get(path, headers=headers).status_code == 401

    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers["Authorization"] = f"Bearer {token.access_token}"
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    assert response.json()["project_id"] == PROJECT_ID

    assert client.get("/internal/v1/projects", headers=headers).status_code == 200
    assert client.get(
        f"/internal/v1/projects/{PROJECT_ID}/memberships", headers=headers
    ).status_code == 200
    write_headers = {"Authorization": headers["Authorization"]}
    assert client.post("/internal/v1/projects", json={"a": 1}).status_code == 401
    assert client.post(
        "/internal/v1/projects", json={"a": 1}, headers=write_headers
    ).status_code == 201
    assert client.post(
        f"/internal/v1/projects/{PROJECT_ID}:deactivate",
        json={"a": 1},
        headers=write_headers,
    ).status_code == 200
    assert client.post(
        f"/internal/v1/projects/{PROJECT_ID}/memberships",
        json={"a": 1},
        headers=write_headers,
    ).status_code == 201
    assert client.post(
        f"/internal/v1/projects/{PROJECT_ID}/memberships:add-many",
        json={"a": 1},
        headers=write_headers,
    ).status_code == 201
    assert client.post(
        f"/internal/v1/projects/{PROJECT_ID}/memberships/member-a:remove",
        json={"a": 1},
        headers=write_headers,
    ).status_code == 201
    assert {name for name, _payload in service.calls} == {
        "get",
        "list",
        "memberships",
        "create",
        "deactivate",
        "add",
        "add-many",
        "remove",
    }

    app.state.eos_project_operations = None
    assert client.get(path, headers=headers).status_code == 503
    assert client.post(
        "/internal/v1/projects", json={"a": 1}, headers=write_headers
    ).status_code == 503

    app.state.eos_project_operations = FailingProjectService()
    assert client.get(path, headers=headers).status_code == 403
    assert client.post(
        "/internal/v1/projects", json={"a": 1}, headers=write_headers
    ).status_code == 403
