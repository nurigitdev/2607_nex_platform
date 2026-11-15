from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import test_nex_eos_mybee_project_pnl as fixture
import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from nex_eos import (
    PROJECT_PNL_READ_ACTION,
    EosProjectPnlPersistenceError,
    EosProjectPnlPrivacyGuard,
    EosProjectPnlQueryError,
    EosProjectPnlQueryService,
    InMemoryPnlPrivacyRepository,
    PnlPrivacyPopulationFact,
    project_pnl_api,
)
from nex_eos.project_authorization import EosProjectAuthorizationError
from nex_eos.project_pnl_api import register_project_pnl_routes

SUBJECT = "employee-pnl-reader"
CORRELATION = "w60-s7-02f-query"


class Authorizer:
    def __init__(self, *, project_code: str = "W601D260001", failure=None) -> None:
        self.project_code = project_code
        self.failure = failure
        self.calls: list[dict[str, object]] = []

    def authorize(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return SimpleNamespace(
            decision_ref="oa-decision:s7-03",
            project_code=self.project_code,
            project_role="MANAGER",
            project_status="ACTIVE",
            source_version=1,
            projection_event_hash="sha256:" + "1" * 64,
            authorization_revision_hash="sha256:" + "2" * 64,
            decided_at="2026-11-15T00:00:00+00:00",
        )


def _query_service(runtime, *, authorizer=None):
    privacy_repository = InMemoryPnlPrivacyRepository(
        facts=(
            PnlPrivacyPopulationFact(
                snapshot_id="10000000-0000-0000-0000-000000000001",
                line_no=1,
                population_count=5,
                minimum_population=3,
                ordinary_view_suppressed=False,
                line_hash="sha256:" + "3" * 64,
            ),
        )
    )
    return EosProjectPnlQueryService(
        repository=runtime.repository,
        project_authorizer=authorizer or Authorizer(),
        privacy_guard=EosProjectPnlPrivacyGuard(privacy_repository),
    )


def _get(service, **overrides):
    values = {
        "tenant_id": fixture.TENANT,
        "company_id": fixture.COMPANY_ID,
        "project_id": fixture.PROJECT_ID,
        "period_id": fixture.PERIOD_ID,
        "requester_subject_id": SUBJECT,
        "correlation_id": CORRELATION,
    }
    values.update(overrides)
    return service.get(**values)


def test_query_service_returns_latest_and_denies_payroll_history() -> None:
    runtime = fixture._runtime()
    first = runtime.repository.append(fixture._draft(), fixture._components())
    authorizer = Authorizer()
    service = _query_service(runtime, authorizer=authorizer)

    assert _get(service) == first
    with pytest.raises(EosProjectPnlQueryError) as historical:
        _get(service, projection_version=1)
    assert historical.value.error_code == "PAYROLL_PRIVACY_DENIED"
    assert historical.value.status_code == 403
    assert authorizer.calls == [
        {
            "tenant_id": fixture.TENANT,
            "subject_id": SUBJECT,
            "project_id": fixture.PROJECT_ID,
            "action": PROJECT_PNL_READ_ACTION,
            "correlation_id": CORRELATION,
        },
        {
            "tenant_id": fixture.TENANT,
            "subject_id": SUBJECT,
            "project_id": fixture.PROJECT_ID,
            "action": PROJECT_PNL_READ_ACTION,
            "correlation_id": CORRELATION,
        },
    ]
    runtime.engine.dispose()


def test_query_authorizes_before_lookup_and_maps_denial() -> None:
    runtime = fixture._runtime()
    denied = EosProjectAuthorizationError(
        "EOS_PROJECT_AUTHORIZATION_DENIED",
        "denied",
        status_code=403,
        reason_code="PROJECT_ROLE_DENIED",
    )
    service = _query_service(runtime, authorizer=Authorizer(failure=denied))

    with pytest.raises(EosProjectPnlQueryError) as caught:
        _get(service)
    assert caught.value.status_code == 403
    assert caught.value.error_code == "EOS_PROJECT_AUTHORIZATION_DENIED"
    runtime.engine.dispose()


def test_query_missing_projection_and_binding_drift_fail_closed() -> None:
    runtime = fixture._runtime()
    with pytest.raises(EosProjectPnlQueryError) as missing:
        _get(_query_service(runtime))
    assert missing.value.status_code == 404

    runtime.repository.append(fixture._draft(), fixture._components())
    with pytest.raises(EosProjectPnlQueryError) as drift:
        _get(_query_service(runtime, authorizer=Authorizer(project_code="W601D269999")))
    assert drift.value.error_code == "PROJECT_PNL_QUERY_BINDING_DRIFT"
    assert drift.value.retryable is True
    runtime.engine.dispose()


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"tenant_id": "bad space"}, "tenant_id"),
        ({"company_id": "bad"}, "company_id"),
        ({"project_id": "bad"}, "project_id"),
        ({"period_id": "bad"}, "period_id"),
        ({"requester_subject_id": ""}, "requester_subject_id"),
        ({"correlation_id": ""}, "correlation_id"),
        ({"projection_version": True}, "projection_version"),
        ({"projection_version": 0}, "projection_version"),
        ({"projection_version": "bad"}, "projection_version"),
    ],
)
def test_query_rejects_invalid_scope_before_authorization(overrides, expected) -> None:
    runtime = fixture._runtime()
    authorizer = Authorizer()
    with pytest.raises(EosProjectPnlQueryError, match=expected) as caught:
        _get(_query_service(runtime, authorizer=authorizer), **overrides)
    assert caught.value.status_code == 400
    assert authorizer.calls == []
    runtime.engine.dispose()


def test_query_maps_repository_failure() -> None:
    repository = SimpleNamespace(
        get=lambda **_kwargs: (_ for _ in ()).throw(
            EosProjectPnlPersistenceError(
                "PROJECT_PNL_UNAVAILABLE", "offline", status_code=503
            )
        )
    )
    service = EosProjectPnlQueryService(
        repository=repository,
        project_authorizer=Authorizer(),
        privacy_guard=EosProjectPnlPrivacyGuard(InMemoryPnlPrivacyRepository()),
    )
    with pytest.raises(EosProjectPnlQueryError, match="offline") as caught:
        _get(service)
    assert caught.value.status_code == 503


def test_api_route_returns_no_store_projection_and_forwards_scope(monkeypatch) -> None:
    projection = {"schema_version": "eos_project_pnl_projection.v1"}
    calls = []
    app = FastAPI()
    app.state.eos_project_pnl_query_service = SimpleNamespace(
        get=lambda **kwargs: calls.append(kwargs) or projection
    )
    monkeypatch.setattr(
        project_pnl_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: object(),
    )
    register_project_pnl_routes(app)
    client = TestClient(app)
    response = client.get(
        f"/internal/v2/finance/projects/{fixture.PROJECT_ID}/pnl/{fixture.PERIOD_ID}",
        params={"projection_version": 2},
        headers={
            "X-NeX-Tenant-Id": fixture.TENANT,
            "X-NeX-Company-Id": fixture.COMPANY_ID,
            "X-NeX-Subject-Id": SUBJECT,
            "X-NeX-Correlation-Id": CORRELATION,
        },
    )
    assert response.status_code == 200
    assert response.json() == projection
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert calls == [
        {
            "tenant_id": fixture.TENANT,
            "company_id": fixture.COMPANY_ID,
            "project_id": fixture.PROJECT_ID,
            "period_id": fixture.PERIOD_ID,
            "requester_subject_id": SUBJECT,
            "correlation_id": CORRELATION,
            "projection_version": 2,
        }
    ]

    denied_shape = client.get(
        f"/internal/v2/finance/projects/{fixture.PROJECT_ID}/pnl/{fixture.PERIOD_ID}",
        params={"work_code": "FL0012044"},
        headers={
            "X-NeX-Tenant-Id": fixture.TENANT,
            "X-NeX-Company-Id": fixture.COMPANY_ID,
            "X-NeX-Subject-Id": SUBJECT,
            "X-NeX-Correlation-Id": CORRELATION,
        },
    )
    assert denied_shape.status_code == 400
    assert denied_shape.json()["error_code"] == "PROJECT_PNL_QUERY_SHAPE_DENIED"


def test_api_route_covers_admission_domain_error_and_unavailable(monkeypatch) -> None:
    app = FastAPI()
    app.state.eos_project_pnl_query_service = SimpleNamespace(
        get=lambda **_kwargs: (_ for _ in ()).throw(
            EosProjectPnlQueryError(
                "EOS_PROJECT_AUTHORIZATION_DENIED",
                "denied",
                status_code=403,
            )
        )
    )
    monkeypatch.setattr(
        project_pnl_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: object(),
    )
    register_project_pnl_routes(app)
    client = TestClient(app)
    path = f"/internal/v2/finance/projects/{fixture.PROJECT_ID}/pnl/{fixture.PERIOD_ID}"
    headers = {
        "X-NeX-Tenant-Id": fixture.TENANT,
        "X-NeX-Company-Id": fixture.COMPANY_ID,
        "X-NeX-Subject-Id": SUBJECT,
        "X-NeX-Correlation-Id": CORRELATION,
    }
    denied = client.get(path, headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "EOS_PROJECT_AUTHORIZATION_DENIED"
    assert denied.headers["cache-control"] == "no-store, max-age=0"

    app.state.eos_project_pnl_query_service = None
    assert client.get(path, headers=headers).status_code == 503

    admission = JSONResponse({"detail": "bad token"}, status_code=401)
    monkeypatch.setattr(
        project_pnl_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: admission,
    )
    rejected = client.get(path, headers=headers)
    assert rejected.status_code == 401
    assert rejected.headers["cache-control"] == "no-store, max-age=0"
    assert rejected.headers["pragma"] == "no-cache"
    assert client.get(
        path, params={"work_code": "FL0012044"}, headers=headers
    ).status_code == 401


def test_openapi_and_runtime_catalog_publish_project_pnl_read_boundary() -> None:
    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    operation = spec["paths"][
        "/internal/v2/finance/projects/{project_id}/pnl/{period_id}"
    ]["get"]
    assert operation["operationId"] == "FINANCE.PROJECT_PNL.GET"
    assert operation["x-nex-business-scope"] == PROJECT_PNL_READ_ACTION
    assert operation["x-nex-query-shape"] == "PROJECT_PERIOD_LATEST_NO_FILTERS"
    assert operation["x-nex-payroll-privacy-policy"] == "project-pnl-privacy.v1"
    assert operation["x-nex-side-effect-free"] is True
    assert spec["components"]["schemas"]["ProjectPnlProjection"][
        "x-nex-canonical-json-schema"
    ].endswith("project_pnl_projection.v1.schema.json")


def test_api_rejects_missing_required_headers_without_calling_service(
    monkeypatch,
) -> None:
    calls = []
    app = FastAPI()
    app.state.eos_project_pnl_query_service = SimpleNamespace(
        get=lambda **kwargs: calls.append(kwargs)
    )
    monkeypatch.setattr(
        project_pnl_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: object(),
    )
    register_project_pnl_routes(app)
    response = TestClient(app).get(
        f"/internal/v2/finance/projects/{fixture.PROJECT_ID}/pnl/{fixture.PERIOD_ID}"
    )
    assert response.status_code == 422
    assert calls == []
