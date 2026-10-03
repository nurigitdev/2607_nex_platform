from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from nex_oa.service_principal_api import (
    OA_SERVICE_PRINCIPAL_ADMIN_SCOPE,
    OA_SERVICE_PRINCIPAL_READ_SCOPE,
    _payload,
    register_service_principal_routes,
)
from nex_oa.service_principal_repository import InMemoryOaServicePrincipalRepository
from nex_oa.service_principal_service import OaServicePrincipalService
from nex_oa.service_principals import OaServicePrincipalError
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


def _client(*, emitter: OperationalEventEmitter | None = None):
    repository = InMemoryOaServicePrincipalRepository()
    service = OaServicePrincipalService(repository)
    store = InMemoryOperationalEventStore()
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_service_principal_routes(
        app,
        service=service,
        audit_emitter=emitter or OperationalEventEmitter(service_id="nex-oa", store=store),
    )
    return TestClient(app), service, store


def _headers(*scopes: str) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-1258",
        "traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
    }


def _principal_payload() -> dict[str, object]:
    return {
        "principal_id": "ae-runtime",
        "service_id": "nex-ae-api",
        "display_name": "AE Runtime",
        "allowed_audiences": ["nex-cx"],
        "allowed_scopes": ["document:read"],
        "expected_revision": 0,
    }


def test_routes_enforce_distinct_read_and_admin_scopes() -> None:
    client, _, _ = _client()
    path = "/internal/v1/service-principals"

    assert client.get(path).status_code == 401
    assert client.post(path, json=_principal_payload()).status_code == 401
    assert client.get(path, headers=_headers(OA_SERVICE_PRINCIPAL_ADMIN_SCOPE)).status_code == 403
    assert client.post(
        path,
        json=_principal_payload(),
        headers=_headers(OA_SERVICE_PRINCIPAL_READ_SCOPE),
    ).status_code == 403


def test_principal_and_credential_routes_cover_full_lifecycle() -> None:
    client, _, store = _client()
    admin = _headers(OA_SERVICE_PRINCIPAL_ADMIN_SCOPE)
    read = _headers(OA_SERVICE_PRINCIPAL_READ_SCOPE)

    created = client.post(
        "/internal/v1/service-principals",
        json=_principal_payload(),
        headers=admin,
    )
    assert created.status_code == 200
    assert created.json()["audit_event"]["ok"] is True
    assert created.json()["request_id"] == "request-1258"

    listed = client.get(
        "/internal/v1/service-principals?service_id=nex-ae-api", headers=read
    )
    detail = client.get(
        "/internal/v1/service-principals/ae-runtime", headers=read
    )
    assert listed.json()["count"] == 1
    assert detail.json()["principal"]["service_id"] == "nex-ae-api"

    disabled = client.patch(
        "/internal/v1/service-principals/ae-runtime/status",
        json={"target_status": "DISABLED", "expected_revision": 1},
        headers=admin,
    )
    assert disabled.json()["principal"]["status"] == "DISABLED"
    client.patch(
        "/internal/v1/service-principals/ae-runtime/status",
        json={"target_status": "ACTIVE", "expected_revision": 2},
        headers=admin,
    )

    issued = client.post(
        "/internal/v1/service-principals/ae-runtime/credentials",
        json={"lifetime_days": 30},
        headers=admin,
    )
    assert issued.status_code == 200
    credential_id = issued.json()["credential"]["credential_id"]
    assert issued.json()["client_secret"]
    assert "secret_hash" not in issued.json()["credential"]

    credentials = client.get(
        "/internal/v1/service-principals/ae-runtime/credentials", headers=read
    )
    credential = client.get(
        f"/internal/v1/service-credentials/{credential_id}", headers=read
    )
    assert credentials.json()["count"] == 1
    assert credential.json()["credential"]["credential_id"] == credential_id

    rotated = client.post(
        f"/internal/v1/service-credentials/{credential_id}/rotate",
        json={"expected_revision": 1, "lifetime_days": 30, "grace_seconds": 60},
        headers=admin,
    )
    assert rotated.status_code == 200
    new_id = rotated.json()["credential"]["credential_id"]
    revoked = client.patch(
        f"/internal/v1/service-credentials/{new_id}/status",
        json={"target_status": "REVOKED", "expected_revision": 1},
        headers=admin,
    )
    assert revoked.json()["credential"]["status"] == "REVOKED"
    assert len(store.events) == 6
    serialized = str(store.events)
    assert issued.json()["client_secret"] not in serialized
    assert "secret_hash" not in serialized


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/internal/v1/service-principals", {**_principal_payload(), "secret": "x"}),
        ("patch", "/internal/v1/service-principals/missing/status", {"target_status": "ACTIVE"}),
        ("post", "/internal/v1/service-principals/missing/credentials", {}),
        ("post", "/internal/v1/service-credentials/missing/rotate", {}),
        ("patch", "/internal/v1/service-credentials/missing/status", {}),
    ],
)
def test_mutation_routes_reject_unsafe_or_incomplete_payloads(
    method: str, path: str, payload: dict[str, object]
) -> None:
    client, _, _ = _client()
    response = getattr(client, method)(
        path, json=payload, headers=_headers(OA_SERVICE_PRINCIPAL_ADMIN_SCOPE)
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "oa.service_principal_payload_invalid"


def test_read_and_mutation_service_errors_are_problem_details() -> None:
    client, _, _ = _client()
    read = _headers(OA_SERVICE_PRINCIPAL_READ_SCOPE)
    admin = _headers(OA_SERVICE_PRINCIPAL_ADMIN_SCOPE)

    assert client.get(
        "/internal/v1/service-principals?service_id=unknown", headers=read
    ).status_code == 400
    assert client.get(
        "/internal/v1/service-principals/missing", headers=read
    ).status_code == 404
    assert client.get(
        "/internal/v1/service-credentials/missing", headers=read
    ).status_code == 404
    assert client.get(
        "/internal/v1/service-principals/!/credentials", headers=read
    ).status_code == 400

    created = client.post(
        "/internal/v1/service-principals",
        json=_principal_payload(),
        headers=admin,
    )
    assert created.status_code == 200
    stale = client.post(
        "/internal/v1/service-principals",
        json=_principal_payload(),
        headers=admin,
    )
    assert stale.status_code == 409

    assert client.post(
        "/internal/v1/service-principals/missing/credentials",
        json={"lifetime_days": 30},
        headers=admin,
    ).status_code == 404
    assert client.post(
        "/internal/v1/service-credentials/missing/rotate",
        json={"expected_revision": 1, "lifetime_days": 30, "grace_seconds": 60},
        headers=admin,
    ).status_code == 404
    assert client.patch(
        "/internal/v1/service-credentials/missing/status",
        json={"target_status": "REVOKED", "expected_revision": 1},
        headers=admin,
    ).status_code == 404


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/internal/v1/service-principals/ae-runtime", None),
        ("patch", "/internal/v1/service-principals/ae-runtime/status", {}),
        ("post", "/internal/v1/service-principals/ae-runtime/credentials", {}),
        ("get", "/internal/v1/service-principals/ae-runtime/credentials", None),
        ("get", "/internal/v1/service-credentials/missing", None),
        ("post", "/internal/v1/service-credentials/missing/rotate", {}),
        ("patch", "/internal/v1/service-credentials/missing/status", {}),
    ],
)
def test_each_route_rejects_missing_authorization(
    method: str, path: str, payload: dict[str, object] | None
) -> None:
    client, _, _ = _client()
    kwargs = {"json": payload} if payload is not None else {}

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401


def test_audit_failure_is_visible_without_leaking_or_masking_mutation() -> None:
    class FailingStore:
        def append(self, _event):
            raise RuntimeError("private audit failure")

    emitter = OperationalEventEmitter(service_id="nex-oa", store=FailingStore())
    client, _, _ = _client(emitter=emitter)
    response = client.post(
        "/internal/v1/service-principals",
        json=_principal_payload(),
        headers=_headers(OA_SERVICE_PRINCIPAL_ADMIN_SCOPE),
    )

    assert response.status_code == 200
    assert response.json()["audit_event"] == {
        "ok": False,
        "error_code": "operational_event.emit_failed",
        "detail": "operational event emission failed",
        "status_code": 503,
    }


def test_payload_helper_reports_unknown_and_missing_fields() -> None:
    with pytest.raises(OaServicePrincipalError, match="unsupported"):
        _payload({"secret": "x"}, allowed=frozenset(), required=())
    with pytest.raises(OaServicePrincipalError, match="required"):
        _payload({}, allowed=frozenset({"name"}), required=("name",))
    assert _payload({"name": "x"}, allowed=frozenset({"name"}), required=("name",)) == {
        "name": "x"
    }


def test_main_registers_service_principal_routes() -> None:
    from nex_oa.main import app

    paths = {route.path for route in app.routes}
    assert "/internal/v1/service-principals" in paths
    assert "/internal/v1/service-credentials/{credential_id}/rotate" in paths
