from __future__ import annotations

import json
from typing import Any, Mapping

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from nex_oa.auth_events import InMemoryOaAuthEventRepository
from nex_oa.federated_identities import OaFederationError, build_external_identity_link, build_federation_provider
from nex_oa.federated_identity_repository import InMemoryOaFederatedIdentityRepository
from nex_oa.federated_login import (
    CachingOidcVerifierProvider,
    HttpOidcDocumentSource,
    OaFederatedLoginService,
    build_federated_login_response,
    normalize_federated_login_request,
    register_federated_login_routes,
)
from nex_oa.oidc_verifier import VerifiedOidcIdentity
from nex_runtime import issue_mock_service_token
import run_oa_federated_login_orchestration as runner


ISSUER = "https://id.example.test"
SUBJECT_DIGEST = "1fe37e2c4f3041166edbf415c389921987cba9b5fe6edf1919dd8ed136b7b16f"


class _Verifier:
    error: OaFederationError | None = None

    def verify(self, _token: object, *, expected_nonce: object) -> VerifiedOidcIdentity:
        if self.error:
            raise self.error
        assert expected_nonce == "nonce-1"
        return VerifiedOidcIdentity("company-oidc", ISSUER, ("nex-platform",), "nex-platform", 10, 20, "key", SUBJECT_DIGEST, "0" * 64, "opaque-subject")


class _Verifiers:
    def __init__(self, verifier: _Verifier | None = None) -> None:
        self.verifier = verifier or _Verifier()

    def for_provider(self, _provider: Mapping[str, Any]) -> _Verifier:
        return self.verifier


class _Sessions:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    def issue_session(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self.payload = dict(payload)
        return {"session_id": "session-1", "tenant_id": payload["tenant_id"], "subject_id": payload["subject_id"], "roles": ["admin"], "scopes": ["workspace:use"], "metadata": {"existing": True}}


def _service(*, identity: bool = True, provider_status: str = "ACTIVE", verifier: _Verifier | None = None):
    provider = build_federation_provider({"provider_id": "company-oidc", "issuer": ISSUER, "client_id": "nex-platform", "discovery_url": f"{ISSUER}/.well-known/openid-configuration", "display_name": "Company OIDC", "status": provider_status})
    repository = InMemoryOaFederatedIdentityRepository()
    repository.save_provider(provider)
    if identity:
        repository.save_identity(build_external_identity_link({"provider_id": "company-oidc", "external_subject": "opaque-subject", "tenant_id": "company", "subject_id": "employee-1001"}, provider={**provider, "status": "ACTIVE"}))
    sessions = _Sessions()
    return OaFederatedLoginService(repository, sessions, _Verifiers(verifier)), sessions


def _payload(**overrides: object) -> dict[str, object]:
    return {"provider_id": "company-oidc", "id_token": "private-token", "nonce": "nonce-1", "requested_scopes": ["workspace:use"], "ttl_seconds": 600, **overrides}


def test_service_resolves_link_and_issues_existing_oa_session() -> None:
    service, sessions = _service()
    response = service.login(_payload())
    assert sessions.payload == {"tenant_id": "company", "subject_id": "employee-1001", "requested_scopes": ["workspace:use"], "ttl_seconds": 600}
    assert response["session_id"] == "session-1"
    assert response["metadata"]["existing"] is True
    assert response["metadata"]["auth_method"] == "federated_oidc"
    assert "private-token" not in json.dumps(response)
    assert "opaque-subject" not in json.dumps(response)


def test_service_fails_for_missing_inactive_unlinked_and_verifier_failure() -> None:
    service, _ = _service()
    service.repository.providers.clear()  # type: ignore[attr-defined]
    with pytest.raises(OaFederationError) as missing:
        service.login(_payload())
    assert missing.value.error_code == "oa.federated_login_provider_invalid"

    inactive, _ = _service(provider_status="DISABLED")
    with pytest.raises(OaFederationError):
        inactive.login(_payload())
    unlinked, _ = _service(identity=False)
    with pytest.raises(OaFederationError) as absent:
        unlinked.login(_payload())
    assert absent.value.error_code == "oa.federated_identity_not_linked"
    verifier = _Verifier()
    verifier.error = OaFederationError(401, "oa.oidc_nonce_invalid", "invalid")
    failed, _ = _service(verifier=verifier)
    with pytest.raises(OaFederationError) as rejected:
        failed.login(_payload())
    assert rejected.value.error_code == "oa.oidc_nonce_invalid"


@pytest.mark.parametrize("payload", ([], {}, {**_payload(), "unknown": True}, {**_payload(), "nonce": " spaced "}))
def test_request_normalization_rejects_invalid_input(payload) -> None:
    with pytest.raises(OaFederationError):
        normalize_federated_login_request(payload)


def test_response_handles_non_mapping_metadata() -> None:
    response = build_federated_login_response(
        {
            "session_id": "x",
            "tenant_id": "company",
            "subject_id": "employee-1001",
            "roles": ["admin"],
            "scopes": ["workspace:use"],
            "metadata": [],
        },
        provider_id="p",
    )
    assert response["metadata"]["provider_id"] == "p"


def test_http_document_source_success_and_failures() -> None:
    source = HttpOidcDocumentSource(requester=lambda *args, **kwargs: httpx.Response(200, json={"issuer": ISSUER}))
    assert source.fetch_json(ISSUER)["issuer"] == ISSUER
    for response in (
        httpx.Response(500, json={}),
        httpx.Response(200, content=b"x" * 70_000),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
    ):
        failing = HttpOidcDocumentSource(requester=lambda *args, response=response, **kwargs: response)
        with pytest.raises(OaFederationError):
            failing.fetch_json(ISSUER)

    def timeout(*_args, **_kwargs):
        raise httpx.ReadTimeout("private")

    with pytest.raises(OaFederationError):
        HttpOidcDocumentSource(requester=timeout).fetch_json(ISSUER)


def test_caching_verifier_provider_reuses_revision_and_evicts_old_revision() -> None:
    service, _sessions = _service()
    provider = service.repository.get_provider("company-oidc")

    class Source:
        def fetch_json(self, _url):
            return {}

    registry = CachingOidcVerifierProvider(Source())
    first = registry.for_provider(provider)
    assert registry.for_provider(provider) is first
    second = registry.for_provider({**provider, "revision": 2})
    assert second is not first
    assert len(registry._verifiers) == 1


def test_api_route_authorization_success_failure_and_audit() -> None:
    service, _ = _service()
    events = InMemoryOaAuthEventRepository()
    app = FastAPI()
    register_federated_login_routes(app, service=service, auth_event_repository=events)
    client = TestClient(app)
    unauthorized = client.post("/internal/v1/auth/federated-login", json=_payload())
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-oa").access_token
    headers = {"Authorization": f"Bearer {token}", "X-Request-ID": "request-1"}
    success = client.post("/internal/v1/auth/federated-login", json=_payload(), headers=headers)
    failure = client.post("/internal/v1/auth/federated-login", json={**_payload(), "provider_id": "missing"}, headers=headers)

    assert unauthorized.status_code == 401
    assert success.status_code == 200
    assert success.json()["request_id"] == "request-1"
    assert failure.status_code == 401
    assert [event["event_type"] for event in events.events] == ["FEDERATED_LOGIN_SUCCEEDED", "FEDERATED_LOGIN_FAILED"]
    assert "private-token" not in json.dumps(events.events)


def test_api_route_uses_configured_signed_token_admission_runtime() -> None:
    service, _ = _service()
    app = FastAPI()
    app.state.service_token_admission = object()
    register_federated_login_routes(app, service=service)
    token = issue_mock_service_token(
        service_id="nex-ae-api", audience="nex-oa"
    ).access_token

    response = TestClient(app).post(
        "/internal/v1/auth/federated-login",
        json=_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "nex.service_token_admission_unavailable"


def test_runner_and_cli(monkeypatch, capsys) -> None:
    evidence = runner.run_oa_federated_login_orchestration()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert runner.summary_line(evidence) == "oa_federated_login_orchestration=pass checks=7/7 session=True next=1287"
    monkeypatch.setattr(runner, "run_oa_federated_login_orchestration", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "next=1287" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(runner, "run_oa_federated_login_orchestration", lambda: {"status": "FAIL"})
    assert runner.main([]) == 1
