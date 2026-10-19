from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest
import yaml
from fastapi.testclient import TestClient
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_wc import coordination_clients as client_module
from nex_wc.authorization import AuthorizationSubjectDenied, require_active_scope
from nex_wc.coordination_clients import HttpAuthorizationSource
from nex_wc.work_item_api import register_work_item_routes
from nex_wc.work_items import (
    InMemoryWorkItemRepository,
    WorkItemError,
    WorkItemService,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 19, 3, 4, 5, tzinfo=UTC)
WORK_ITEM_ID = "11111111-1111-4111-8111-111111111202"


class _Authorization:
    def __init__(self, value=None, *, error: Exception | None = None) -> None:
        self.value = value or {
            "active": True,
            "scopes": ["work:delegate"],
            "revision_hash": "a" * 64,
        }
        self.error = error
        self.calls: list[dict[str, str]] = []

    def effective_authorization(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return self.value


def _payload(*, requester: str = "ia-ca02") -> dict[str, object]:
    return {
        "work_item_id": WORK_ITEM_ID,
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-ca02",
            "tenant_id": "tenant-ca02",
            "parent_agent_execution_id": "execution-ca02",
            "parent_executable_plan_id": "plan-ca02",
            "parent_executable_step_id": "step-ca02",
            "delegation_revision": 1,
            "goal": "Prepare a bounded delegated report.",
            "work_class": "REPORTING",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.PROJECT_BUDGET_CHECK",
            "project_ref": {"entity_type": "PROJECT", "entity_id": "project-ca02"},
            "project_scope_ref": "project-ca02",
            "result_contract_ref": "urn:nex:result:ca02:1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "trace-ca02",
            "causation_id": "cause-ca02",
        },
        "requester": {"entity_type": "AGENT", "entity_id": requester},
        "accountable_owner": {"entity_type": "USER", "entity_id": "owner-ca02"},
    }


def _service(repository, authorization):
    return WorkItemService(
        repository,
        authorization_source=authorization,
        id_factory=lambda: WORK_ITEM_ID,
        clock=lambda: NOW,
    )


def test_ca02_authorized_create_persists_metadata_safe_evidence_and_rechecks_replay():
    repository = InMemoryWorkItemRepository()
    authorization = _Authorization()
    service = _service(repository, authorization)

    created = service.create(_payload())
    replayed = service.create(_payload())
    stored = repository.get(tenant_id="tenant-ca02", work_item_id=WORK_ITEM_ID)

    assert created["created"] is True
    assert replayed["created"] is False
    assert authorization.calls == [
        {"tenant_id": "tenant-ca02", "subject_id": "ia-ca02"},
        {"tenant_id": "tenant-ca02", "subject_id": "ia-ca02"},
    ]
    assert stored is not None
    assert stored["create_authorization_revision_hash"] == "a" * 64
    assert stored["create_authorization_checked_at"] == "2026-10-19T03:04:05Z"
    assert stored["create_authorized_subject_id"] == "ia-ca02"
    assert "create_authorization_revision_hash" not in created["work_item"]


@pytest.mark.parametrize(
    "authorization",
    (
        None,
        {"active": False, "scopes": ["work:delegate"], "revision_hash": "a"},
        {"active": True, "scopes": [], "revision_hash": "a"},
        {"active": True, "scopes": "work:delegate", "revision_hash": "a"},
        {"active": True, "scopes": ["work:delegate"], "revision_hash": ""},
        {"active": True, "scopes": ["work:delegate"], "revision_hash": "a" * 257},
    ),
)
def test_ca02_inactive_missing_scope_and_malformed_authorization_fail_closed(
    authorization,
):
    repository = InMemoryWorkItemRepository()
    source = _Authorization(authorization)
    if authorization is None:
        source.value = None
    with pytest.raises(WorkItemError) as denied:
        _service(repository, source).create(_payload())
    assert denied.value.error_code == "wc.work_item_authorization_denied"
    assert denied.value.status_code == 403
    assert denied.value.retryable is False
    assert repository.get(tenant_id="tenant-ca02", work_item_id=WORK_ITEM_ID) is None


@pytest.mark.parametrize(
    "error",
    (
        AuthorizationSubjectDenied("inactive membership"),
        AuthorizationSubjectDenied("membership not found"),
    ),
)
def test_ca02_typed_subject_denial_maps_to_403(error):
    with pytest.raises(WorkItemError) as denied:
        _service(InMemoryWorkItemRepository(), _Authorization(error=error)).create(
            _payload()
        )
    assert denied.value.error_code == "wc.work_item_authorization_denied"
    assert denied.value.status_code == 403


def test_ca02_dependency_failure_maps_to_retryable_503_with_zero_mutation():
    repository = InMemoryWorkItemRepository()
    with pytest.raises(WorkItemError) as unavailable:
        _service(
            repository,
            _Authorization(error=RuntimeError("OA connection failed")),
        ).create(_payload())
    assert unavailable.value.error_code == "wc.work_item_authorization_unavailable"
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True
    assert repository.get(tenant_id="tenant-ca02", work_item_id=WORK_ITEM_ID) is None


def test_ca02_revoked_idempotent_replay_rechecks_authorization_first():
    repository = InMemoryWorkItemRepository()
    authorization = _Authorization()
    service = _service(repository, authorization)
    service.create(_payload())
    original = repository.get(tenant_id="tenant-ca02", work_item_id=WORK_ITEM_ID)
    authorization.value = {
        "active": True,
        "scopes": ["work:claim", "work:result:submit"],
        "revision_hash": "b" * 64,
    }

    with pytest.raises(WorkItemError) as denied:
        service.create(_payload())

    assert denied.value.error_code == "wc.work_item_authorization_denied"
    assert (
        repository.get(tenant_id="tenant-ca02", work_item_id=WORK_ITEM_ID) == original
    )
    assert len(authorization.calls) == 2


def test_ca02_different_authorized_requester_replay_is_semantic_conflict():
    repository = InMemoryWorkItemRepository()
    authorization = _Authorization()
    service = _service(repository, authorization)
    service.create(_payload(requester="requester-a"))

    with pytest.raises(WorkItemError) as conflict:
        service.create(_payload(requester="requester-b"))

    stored = repository.get(tenant_id="tenant-ca02", work_item_id=WORK_ITEM_ID)
    assert conflict.value.error_code == "wc.work_item_idempotency_conflict"
    assert conflict.value.status_code == 409
    assert stored is not None
    assert stored["work_item"]["requester"]["entity_id"] == "requester-a"
    assert len(authorization.calls) == 2


@pytest.mark.parametrize(
    "status,error_code",
    (
        (403, "oa.authorization_membership_inactive"),
        (404, "oa.authorization_membership_not_found"),
    ),
)
def test_ca02_http_authorization_source_preserves_oa_subject_denial(
    monkeypatch, status, error_code
):
    problem = BytesIO(json.dumps({"error_code": error_code}).encode())
    error = HTTPError("http://oa", status, "denied", {}, problem)
    monkeypatch.setattr(
        client_module,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(AuthorizationSubjectDenied):
        HttpAuthorizationSource(
            base_url="http://oa", service_token="service-token"
        ).effective_authorization(tenant_id="tenant", subject_id="subject")


def test_ca02_http_authorization_source_keeps_service_trust_failure_unavailable(
    monkeypatch,
):
    problem = BytesIO(json.dumps({"error_code": "SERVICE_SCOPE_MISSING"}).encode())
    error = HTTPError("http://oa", 403, "denied", {}, problem)
    monkeypatch.setattr(
        client_module,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(RuntimeError, match="HTTP 403"):
        HttpAuthorizationSource(
            base_url="http://oa", service_token="service-token"
        ).effective_authorization(tenant_id="tenant", subject_id="subject")


def test_ca02_work_item_api_surfaces_denied_and_unavailable_statuses():
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-wc")
    headers = {"Authorization": f"Bearer {token.access_token}"}
    for source, expected_status, expected_code in (
        (
            _Authorization({"active": True, "scopes": [], "revision_hash": "a"}),
            403,
            "wc.work_item_authorization_denied",
        ),
        (
            _Authorization(error=RuntimeError("down")),
            503,
            "wc.work_item_authorization_unavailable",
        ),
    ):
        app = build_service_app(SERVICE_SPECS["nex-wc"])
        register_work_item_routes(
            app,
            service=_service(InMemoryWorkItemRepository(), source),
        )
        response = TestClient(app).post(
            "/api/v1/work-items", json=_payload(), headers=headers
        )
        assert response.status_code == expected_status
        assert response.json()["error_code"] == expected_code


def test_ca02_migration_is_additive_nullable_and_records_new_head():
    migration = (
        ROOT / "database/nex-wc/migrations/1003_wc_work_item_authorization.sql"
    ).read_text(encoding="utf-8")
    assert (
        "ADD COLUMN IF NOT EXISTS create_authorization_revision_hash TEXT NULL"
        in migration
    )
    assert (
        "ADD COLUMN IF NOT EXISTS create_authorization_checked_at TIMESTAMPTZ NULL"
        in migration
    )
    assert (
        "ADD COLUMN IF NOT EXISTS create_authorized_subject_id TEXT NULL" in migration
    )
    assert "1003_wc_work_item_authorization" in migration


def test_ca02_wc_openapi_matches_all_p7_runtime_work_routes():
    from nex_wc.main import app

    contract = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-wc.openapi.yaml").read_text(encoding="utf-8")
    )
    expected = {
        "/api/v1/work-items",
        "/api/v1/work-items/{work_item_id}",
        "/api/v1/work-items/{work_item_id}/status",
        "/api/v1/work-items/{work_item_id}/route",
        "/api/v1/work-items/{work_item_id}/claim",
        "/api/v1/work-items/{work_item_id}/results",
    }
    assert expected <= set(contract["paths"])
    assert expected <= set(app.openapi()["paths"])
    create = contract["paths"]["/api/v1/work-items"]["post"]
    result = contract["paths"]["/api/v1/work-items/{work_item_id}/results"]["post"]
    assert set(create["responses"]) >= {"201", "200", "401", "403", "409", "503"}
    assert result["x-nex-allowed-service-ids"] == ["nex-ae-api"]
    assert set(result["responses"]) >= {"201", "200", "401", "403", "409", "503"}


def test_ca02_authorization_helper_rejects_non_mapping_and_bytes_scopes():
    with pytest.raises(AuthorizationSubjectDenied):
        require_active_scope([], required_scope="work:delegate")
    with pytest.raises(AuthorizationSubjectDenied):
        require_active_scope(
            {"active": True, "scopes": b"work:delegate", "revision_hash": "a"},
            required_scope="work:delegate",
        )
