from __future__ import annotations

from collections.abc import Mapping

import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_METADATA,
    EOS_NVT_PROJECT_TABLE,
    NVT_PROJECT_ADMIN_SCOPE,
    NVT_PROJECT_CREATE_OPERATION,
    NVT_PROJECT_CREATE_SCOPE,
    NVT_PROJECT_READ_SCOPE,
    NVT_PROJECT_UPDATE_OPERATION,
    EosGovernedProjectError,
    EosGovernedProjectService,
    EosServiceCaller,
    SqlAlchemyEosBusinessTransactionCoordinator,
    create_eos_app,
    project_operation_payload_hash,
)
from nex_runtime import issue_mock_service_token
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT_ID = "tenant-s105"
NVT_ID = "a5000000-0000-4000-8000-000000000001"
CALLER = EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))


class AuthorizationSource:
    def __init__(self) -> None:
        self.scopes = {
            "admin": {
                NVT_PROJECT_CREATE_SCOPE,
                NVT_PROJECT_READ_SCOPE,
                NVT_PROJECT_ADMIN_SCOPE,
            },
            "reader": {NVT_PROJECT_READ_SCOPE},
            "denied": set(),
        }
        self.unavailable = False

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.unavailable:
            raise RuntimeError("private OA detail")
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": sorted(self.scopes.get(subject_id, set())),
            "revision_hash": "a" * 64,
        }


@pytest.fixture
def governed():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    source = AuthorizationSource()
    service = EosGovernedProjectService(
        session_factory=factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=source,
    )
    return factory, source, service


def _write_payload(
    operation: str,
    sequence: int,
    *,
    requester: str = "admin",
    **values,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "eos_nvt_project_operation.v1",
        "tenant_id": TENANT_ID,
        "business_operation_id": f"a5100000-0000-4000-8000-{sequence:012d}",
        "idempotency_key": f"p8-s105-{sequence:04d}",
        "requester_subject_id": requester,
        **values,
    }
    payload["payload_hash"] = project_operation_payload_hash(payload, operation)
    return payload


def _create_payload(sequence: int = 1, *, requester: str = "admin"):
    return _write_payload(
        NVT_PROJECT_CREATE_OPERATION,
        sequence,
        requester=requester,
        nvt_project={
            "nvt_project_id": NVT_ID,
            "nvt_project_code": "NVT-S105",
            "name": "NVT S105",
            "status": "ACTIVE",
        },
    )


def _update_payload(sequence: int = 2, *, requester: str = "admin", **changes):
    return _write_payload(
        NVT_PROJECT_UPDATE_OPERATION,
        sequence,
        requester=requester,
        nvt_project_id=NVT_ID,
        expected_version=1,
        changes=changes or {"name": "NVT S105 Revised"},
    )


def test_create_and_update_are_atomic_and_exactly_replayable(governed) -> None:
    factory, _source, service = governed

    created = service.create_nvt_project(_create_payload(), caller=CALLER)
    create_replay = service.create_nvt_project(_create_payload(), caller=CALLER)
    updated = service.update_nvt_project(_update_payload(), caller=CALLER)
    update_replay = service.update_nvt_project(_update_payload(), caller=CALLER)

    assert created["created"] is True
    assert create_replay["created"] is False
    assert created["result"] == create_replay["result"]
    assert updated["created"] is True
    assert update_replay["created"] is False
    assert updated["result"] == update_replay["result"]
    assert updated["result"]["nvt_project"]["name"] == "NVT S105 Revised"
    assert updated["result"]["nvt_project"]["version"] == 2
    assert updated["result"]["canonical_operation"] == NVT_PROJECT_UPDATE_OPERATION
    with factory() as session:
        assert session.execute(
            select(func.count()).select_from(EOS_NVT_PROJECT_TABLE)
        ).scalar_one() == 1
        assert session.execute(
            select(func.count()).select_from(EOS_BUSINESS_OPERATION_TABLE)
        ).scalar_one() == 2


def test_read_and_list_require_fresh_nvt_scope_without_project_membership(
    governed,
) -> None:
    _factory, _source, service = governed
    service.create_nvt_project(_create_payload(), caller=CALLER)

    found = service.get_nvt_project(
        tenant_id=TENANT_ID,
        nvt_project_id=NVT_ID,
        requester_subject_id="reader",
    )
    listed = service.list_nvt_projects(
        tenant_id=TENANT_ID,
        requester_subject_id="reader",
        status="ACTIVE",
    )

    assert found["nvt_project_code"] == "NVT-S105"
    assert [item["nvt_project_id"] for item in listed] == [NVT_ID]

    with pytest.raises(EosGovernedProjectError) as denied:
        service.list_nvt_projects(
            tenant_id=TENANT_ID,
            requester_subject_id="denied",
        )
    assert denied.value.error_code == "EOS_PROJECT_AUTHORIZATION_DENIED"

    with pytest.raises(EosGovernedProjectError) as absent:
        service.get_nvt_project(
            tenant_id="tenant-other",
            nvt_project_id=NVT_ID,
            requester_subject_id="reader",
        )
    assert absent.value.error_code == "EOS_NVT_PROJECT_NOT_FOUND"


def test_write_scopes_hash_service_trust_and_patch_shape_fail_closed(governed) -> None:
    factory, source, service = governed

    with pytest.raises(EosGovernedProjectError) as denied:
        service.create_nvt_project(
            _create_payload(requester="reader"), caller=CALLER
        )
    assert denied.value.status_code == 403

    bad_hash = _create_payload()
    bad_hash["nvt_project"] = {
        **bad_hash["nvt_project"],  # type: ignore[arg-type]
        "name": "tampered",
    }
    with pytest.raises(EosGovernedProjectError) as mismatch:
        service.create_nvt_project(bad_hash, caller=CALLER)
    assert mismatch.value.error_code == "EOS_PROJECT_PAYLOAD_HASH_MISMATCH"

    with pytest.raises(EosGovernedProjectError) as trust:
        service.create_nvt_project(
            _create_payload(),
            caller=EosServiceCaller("bad", "nex-eos", ()),
        )
    assert trust.value.error_code == "EOS_SERVICE_TRUST_DENIED"

    source.unavailable = True
    with pytest.raises(EosGovernedProjectError) as unavailable:
        service.create_nvt_project(_create_payload(), caller=CALLER)
    assert unavailable.value.status_code == 503
    source.unavailable = False

    service.create_nvt_project(_create_payload(), caller=CALLER)
    immutable = _update_payload(nvt_project_code="CHANGED")
    with pytest.raises(EosGovernedProjectError) as invalid:
        service.update_nvt_project(immutable, caller=CALLER)
    assert invalid.value.error_code == "EOS_PROJECT_OPERATION_INVALID"
    with factory() as session:
        assert session.execute(
            select(EOS_NVT_PROJECT_TABLE.c.nvt_project_code)
        ).scalar_one() == "NVT-S105"


class FakeNvtService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def create_nvt_project(self, payload, *, caller):
        self.calls.append(("create", payload))
        assert caller.audience == "nex-eos"
        return {"created": True, "result": {}}

    def update_nvt_project(self, payload, *, caller):
        self.calls.append(("update", payload))
        return {"created": True, "result": {}}

    def get_nvt_project(self, **kwargs):
        self.calls.append(("get", kwargs))
        return {"nvt_project_id": kwargs["nvt_project_id"]}

    def list_nvt_projects(self, **kwargs):
        self.calls.append(("list", kwargs))
        return [{"nvt_project_id": NVT_ID}]


def test_nvt_routes_are_service_protected_and_keep_update_status_semantics() -> None:
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "p8-s105",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    service = FakeNvtService()
    app.state.eos_project_operations = service
    client = TestClient(app)
    collection = "/internal/v1/nvt-projects"
    member = f"{collection}/{NVT_ID}"
    read_headers = {
        "X-NeX-Tenant-Id": TENANT_ID,
        "X-NeX-Subject-Id": "reader",
    }
    assert client.get(collection, headers=read_headers).status_code == 401

    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    authorization = {"Authorization": f"Bearer {token.access_token}"}
    read_headers.update(authorization)
    assert client.get(member, headers=read_headers).status_code == 200
    assert client.get(
        collection,
        headers=read_headers,
        params={"status": "ACTIVE", "limit": 10, "offset": 0},
    ).status_code == 200
    assert client.post(collection, json={"a": 1}, headers=authorization).status_code == 201
    assert client.patch(member, json={"a": 1}, headers=authorization).status_code == 200
    assert {name for name, _payload in service.calls} == {
        "create",
        "update",
        "get",
        "list",
    }
